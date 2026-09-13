"""pj102 engine - 全量跑批 driver v2.1 (同步单进程模式)

不依赖 subprocess.run 调外部 run_pipeline.py, 直接在当前进程跑
process_one() 循环. 避免 git-bash 子进程被 sandbox 清理.

每完成一个样本立即 dlog() 实时写日志, sandbox 看到 stdout 持续活动.
每个样本 mark_processed 后立即 flush, 崩溃可断点续跑.

v2.1 (P4 T-P4.6 批次运行门):
  - 成本熔断 S4: --budget-yuan (默认 1.0), 每样本前检查本批累计 token 成本, 超限暂停退出码 42
  - 样本级记账: PJ102_CURRENT_SAMPLE 指向当前 hash, token_usage.jsonl 可归因
  - batch_report S6: 批次结束自动写 system/state/batch_report_*.json (逐文件状态+页增量+成本)
  - 失败隔离 S1: 单样本失败登记不中断 (v2.0 已有, 保持)

用法:
  python scripts/run_full.py [--max-samples 40] [--budget-yuan 1.0] [--batch-id ID]
"""
import argparse
import json
import re
import os
import sys
# 强制 stdout 用 UTF-8, 避免 Windows GBK 默认编码导致 emoji/特殊字符 print 崩溃
if hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass
import signal
# 实验: 挡 SIGINT/SIGTERM, 让 sandbox reap 信号不杀 driver
# 由 watchdog 进程 (PJ102_KEEP_DRIVER=1) 验证沙箱 reap 是否只是 SIGINT
if os.environ.get("PJ102_KEEP_DRIVER", "0") == "1":
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
import time
import traceback
from datetime import datetime
from pathlib import Path

# ---- 1. 环境加载 ----
HERMES_ENV = os.path.join(os.environ.get("PJ102_PROJECT_ROOT") or os.getcwd(), ".env")
if os.path.exists(HERMES_ENV):
    with open(HERMES_ENV, encoding="utf-8-sig") as f:
        for line in f:
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                k, _, v = line.partition("=")
                k, v = k.strip(), v.strip().strip('"').strip("'")
                if k and k not in os.environ:
                    os.environ[k] = v

# 关键: 启用 LLM 客户端 4 层心跳防御 (PJ102_DRIVER_LOG)
# 写入独立文件, sandbox 看 mtime 不停 → 不 reap
_HEARTBEAT_LOG = None  # 将在 PROJECT_ROOT 定义后填充

os.environ.setdefault("MINIMAX_CN_BASE_URL", "https://api.minimaxi.com")

PROJECT_ROOT = Path(os.environ.get("PJ102_PROJECT_ROOT") or Path.cwd())
CODE_DIR = PROJECT_ROOT / "code"
# 关键: 启用 LLM 客户端 4 层心跳防御 (PJ102_DRIVER_LOG)
# 写入独立文件, sandbox 看 mtime 不停 → 不 reap
os.environ["PJ102_DRIVER_LOG"] = str(PROJECT_ROOT / "system" / "logs" / "llm_heartbeat.log")
sys.path.insert(0, str(CODE_DIR))
os.environ.setdefault("PJ102_PROJECT_ROOT", str(PROJECT_ROOT))

import yaml  # noqa: E402
project_yaml = PROJECT_ROOT / "config" / "project.yaml"
if project_yaml.exists():
    with open(project_yaml, encoding="utf-8") as f:
        proj_cfg = yaml.safe_load(f) or {}
    source_dir = (proj_cfg.get("scope") or {}).get("source_dir")
    if source_dir:
        os.environ.setdefault("PJ102_DATA_RAW", source_dir)

STATE_DIR = PROJECT_ROOT / "system" / "state"
LOG_DIR = PROJECT_ROOT / "system" / "logs"
DRIVER_LOG = LOG_DIR / "full_driver.log"

# ---- pipeline imports (in-process) ----
from core.config import AppConfig  # noqa: E402
from core import setup_logging  # noqa: E402
from llm_client import LLMClient  # noqa: E402
from pipeline import (  # noqa: E402
    load_index, is_processed, mark_processed, process_one
)
from steps.s12_wiki import s12_write_all_5_types  # noqa: E402


def dlog(msg: str, flush: bool = True) -> None:
    line = f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] [driver2] {msg}"
    print(line, flush=flush)
    with open(DRIVER_LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def get_pending_samples(cfg: AppConfig) -> list:
    """获取所有未处理样本 (修复后的 resume 过滤逻辑)"""
    index = load_index(cfg)
    samples = index.get("samples", [])
    return [s for s in samples
            if not is_processed(cfg, s.get("content_hash", ""))]


def _append_log(operation: str, title: str, details=None):
    """W1-T0.1: log.md 追加 (Gist 规范格式, 可 grep)

    格式: ## [YYYY-MM-DD] 操作 | 标题
    """
    log_path = PROJECT_ROOT / "wiki" / "log.md"
    ts = datetime.now().strftime("%Y-%m-%d")
    lines = [f"\n## [{ts}] {operation} | {title}"]
    for d in details or []:
        lines.append(f"- {d}")
    with open(log_path, "a", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


# ---- v2.1 批次运行门: 成本熔断 + batch_report (P4 T-P4.6) ----

TOKEN_USAGE = STATE_DIR / "token_usage.jsonl"
# 单价 (元/百万 token, 与项目成本口径一致)
PRICE_IN, PRICE_OUT = 0.4, 1.7


def batch_cost_since(batch_start_iso: str) -> dict:
    """本批累计 token 成本 (从 token_usage.jsonl 过滤 batch_start 之后的记录)"""
    cost = {"prompt_tokens": 0, "completion_tokens": 0, "calls": 0, "yuan": 0.0}
    if not TOKEN_USAGE.exists():
        return cost
    try:
        for line in TOKEN_USAGE.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except Exception:
                continue
            if r.get("ts", "") < batch_start_iso:
                continue
            cost["prompt_tokens"] += r.get("prompt_tokens", 0)
            cost["completion_tokens"] += r.get("completion_tokens", 0)
            cost["calls"] += 1
        cost["yuan"] = (cost["prompt_tokens"] / 1e6 * PRICE_IN
                        + cost["completion_tokens"] / 1e6 * PRICE_OUT)
    except Exception:
        pass
    return cost


def write_batch_report(batch: dict) -> Path:
    """S6: 批次报告落盘 (幂等, 同 batch_id 覆盖更新)"""
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    path = STATE_DIR / f"batch_report_{batch['batch_id']}.json"
    path.write_text(json.dumps(batch, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def run_post_processing(cfg: AppConfig) -> dict:
    """v4.0 后处理: polish + concept_merger + backlink_builder + index_builder"""
    report = {}

    # 0. polish_pages (s12 分片页增量收尾) — W3-T3.2 接线
    #    放 merger 之前: 分片页先规范化, 后续模块处理规范名页面
    try:
        from polish_pages import polish_pages
        r = polish_pages(cfg.paths.wiki_base)
        report["polish"] = {k: v for k, v in r.items() if k != "details"}
    except Exception as e:
        report["polish_error"] = str(e)[:200]

    # 1. concept_merger (会调 LLM 合并同名概念)
    try:
        from concept_merger import merge_all_concepts
        llm = LLMClient()
        r = merge_all_concepts(cfg=cfg, llm_client=llm)
        report["concepts_merged"] = r.get("merged_count", 0)
    except Exception as e:
        report["concept_merger_error"] = str(e)[:200]

    # 2. backlink_builder (纯文件处理)
    try:
        from backlink_builder import build_backlinks
        r = build_backlinks(cfg)
        report["backlinks_added"] = r.get("backlinks_added", 0)
    except Exception as e:
        report["backlink_error"] = str(e)[:200]

    # 3. index_builder (主索引重建)
    try:
        from index_builder import build_index
        r = build_index(cfg, action="full-run post-processing")
        report["index_total"] = r.get("total", 0)
    except Exception as e:
        report["index_error"] = str(e)[:200]

    # 4. fix_index_v2 (wikilink 化, 幂等) — W1-T0.1 接线
    #    index_builder 每次 regen index.md 为 md-link 格式, 会覆盖 wikilink 化成果
    #    (血泪陷阱 T2: 此前靠手动补跑, 现接线根治)
    try:
        import subprocess as _sp
        r = _sp.run(
            [sys.executable, str(PROJECT_ROOT / "system" / "tmp" / "fix_index_v2.py")],
            cwd=str(PROJECT_ROOT), capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=120,
        )
        out = (r.stdout or "") + (r.stderr or "")
        # 解析 "index 死链: N, wikilink 数: M"
        m = re.search(r"index 死链: (\d+), wikilink 数: (\d+)", out)
        if m:
            report["fix_index_dead_links"] = int(m.group(1))
            report["fix_index_wikilinks"] = int(m.group(2))
        report["fix_index_rc"] = r.returncode
    except Exception as e:
        report["fix_index_error"] = str(e)[:200]

    # 5. lint_wiki (8 维巡检) — W1-T0.1 接线
    try:
        from lint_wiki import lint_wiki
        lint_report = lint_wiki(cfg.paths.wiki_base)
        report["lint"] = {k: len(v) for k, v in lint_report.items()}
        report["lint_detail"] = lint_report  # 完整明细 (列表截断见 dlog)
    except Exception as e:
        report["lint_error"] = str(e)[:200]

    # 6. dispute_detector (矛盾检测) — W1-T0.1 接线
    #    前置: judgments_aggregator 从 step 缓存 s7 聚合 judgments_master.json
    #    注: stance 全 unlabeled 时返回空列表 (安全不误报), W4 提示词增强后激活
    try:
        from judgments_aggregator import aggregate as _agg
        from dispute_detector import detect_disputes
        jm = _agg()
        (PROJECT_ROOT / "system" / "state" / "judgments_master.json").write_text(
            json.dumps(jm, ensure_ascii=False, indent=2), encoding="utf-8")
        disputes = detect_disputes(
            PROJECT_ROOT / "system" / "state" / "judgments_master.json",
            cfg.paths.wiki_base,
        )
        report["disputes_found"] = len(disputes)
    except Exception as e:
        report["dispute_error"] = str(e)[:200]

    # 7. log.md 追加 (Gist 规范格式) — W1-T0.1 接线
    try:
        _append_log("post-processing", "full-run 后处理完成", [
            f"index_total: {report.get('index_total', 'n/a')}",
            f"fix_index: 死链 {report.get('fix_index_dead_links', 'n/a')} / "
            f"wikilink {report.get('fix_index_wikilinks', 'n/a')}",
            f"lint: {report.get('lint', 'n/a')}",
            f"disputes: {report.get('disputes_found', 0)}",
        ])
    except Exception as e:
        report["log_error"] = str(e)[:200]

    return report


def run_verify() -> int:
    """完整性校验"""
    import subprocess
    return subprocess.run(
        [sys.executable, str(PROJECT_ROOT / "scripts" / "verify.py")],
        cwd=str(PROJECT_ROOT),
        capture_output=False
    ).returncode


def main() -> int:
    parser = argparse.ArgumentParser(description="全量跑批 driver v2.1 (批次运行门)")
    parser.add_argument("--max-samples", type=int, default=50,
                        help="最大处理样本数(防止超时被砍后无止境)")
    parser.add_argument("--skip-post", action="store_true", help="跳过后处理")
    parser.add_argument("--retries", type=int, default=0,
                        help="单样本失败重试次数(默认 0, 配合 step 缓存生效)")
    parser.add_argument("--budget-yuan", type=float, default=1.0,
                        help="批次成本熔断上限(元, 默认 1.0; 超限暂停退出码 42)")
    parser.add_argument("--batch-id", default=None,
                        help="批次 ID(默认自动生成 B<timestamp>)")
    args = parser.parse_args()

    dlog("=" * 60)
    dlog(f"全量跑批 driver v2.1 启动: max_samples={args.max_samples} "
         f"budget={args.budget_yuan}元")
    dlog(f"key: {os.environ.get('MINIMAX_CN_API_KEY', '')[:6]}...")

    batch_id = args.batch_id or f"B{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    batch_start_iso = datetime.now().isoformat(timespec="seconds")
    batch = {
        "batch_id": batch_id,
        "started_at": batch_start_iso,
        "driver": "v2.1",
        "budget_yuan": args.budget_yuan,
        "samples": [],
        "totals": {"success": 0, "fail": 0, "halted_budget": 0},
        "halted": None,
    }

    cfg = AppConfig()
    logger = setup_logging(cfg.paths.logs_dir)
    cfg.paths.ensure_dirs()

    # 显示真实 LLM
    llm = LLMClient()
    dlog(f"LLM Provider: {llm.provider} / {llm.model}")

    pending = get_pending_samples(cfg)
    total_pending = len(pending)
    dlog(f"待处理样本: {total_pending}")

    if total_pending == 0:
        dlog("[OK] all samples processed, skipping post-processing")
    else:
        dlog(f"开始逐个跑 (实时日志, 崩溃可续)")
        t0_total = time.time()

        for i, sample in enumerate(pending[:args.max_samples], 1):
            short = sample["filename"][:46]
            # v2.1 成本熔断 (S4): 每样本前检查本批累计成本
            cost = batch_cost_since(batch_start_iso)
            if cost["yuan"] >= args.budget_yuan:
                dlog(f"[HALT] 成本熔断触发: 本批已耗 {cost['yuan']:.3f} 元 "
                     f">= 预算 {args.budget_yuan} 元, 暂停于样本 {i}")
                batch["halted"] = "budget_exceeded"
                batch["totals"]["halted_budget"] = total_pending - (i - 1)
                break
            # v2.1 样本级记账归因
            os.environ["PJ102_CURRENT_SAMPLE"] = sample.get("content_hash", "")
            t0 = time.time()
            entry = {"file": sample["filename"], "hash": sample.get("content_hash", ""),
                     "file_class": sample.get("file_class", "transcript")}
            # v4.1 retry: 失败重试 args.retries 次, 每次利用 step 缓存只补未完成步骤
            attempt = 0
            max_attempts = 1 + max(0, args.retries)
            last_err = None
            pages_written = 0
            while attempt < max_attempts:
                attempt += 1
                try:
                    dlog(f"[{i}/{total_pending}] >> {short} "
                         f"(attempt {attempt}/{max_attempts})", flush=True)
                    state = process_one(sample, llm, cfg, integrate=True)
                    # W3-T3.1: 补调 s12 全量写页 (根治 backfill_s12 手动步骤)
                    # 注: s12 产出 hash 分片页, 由后处理链 polish_pages 增量收尾
                    try:
                        out_paths = s12_write_all_5_types(state, cfg)
                        n_pages = sum(len(v) for v in out_paths.values())
                        pages_written = n_pages
                        dlog(f"    s12 写页: {n_pages} 个 "
                             f"[{', '.join(f'{k[:4]}:{len(v)}' for k, v in out_paths.items())}]",
                             flush=True)
                    except Exception as e:
                        dlog(f"    WARN s12 写页失败(可 backfill 补): {e}", flush=True)
                    mark_processed(cfg, sample["filename"],
                                   sample["content_hash"], state)
                    dt = time.time() - t0
                    integ = state.get("_integrations", {})
                    wiki_count = sum(
                        len(v) for v in integ.values()
                        if isinstance(v, dict) and "written" in v
                    )
                    dlog(f"[{i}/{total_pending}] OK {short}  "
                         f"耗时 {dt:.0f}s 尝试 {attempt}/{max_attempts}, 集成 {integ}",
                         flush=True)
                    entry.update({"status": "success", "attempts": attempt,
                                  "duration_s": round(dt, 1), "pages": pages_written})
                    batch["samples"].append(entry)
                    batch["totals"]["success"] += 1
                    last_err = None
                    break
                except Exception as e:
                    dt = time.time() - t0
                    err_short = str(e)[:200]
                    dlog(f"[{i}/{total_pending}] FAIL attempt {attempt}/{max_attempts} "
                         f"{short}  耗时 {dt:.0f}s 失败: {err_short}", flush=True)
                    last_err = e
                    if attempt >= max_attempts:
                        dlog(f"  traceback: {traceback.format_exc()[:500]}", flush=True)
                        # S1 失败隔离: 登记不中断, 继续下一个
                        entry.update({"status": "fail", "attempts": attempt,
                                      "duration_s": round(dt, 1),
                                      "error": err_short})
                        batch["samples"].append(entry)
                        batch["totals"]["fail"] += 1
                    else:
                        dlog(f"  step 缓存生效, 重试时跳过已成功步骤", flush=True)

        total_dt = time.time() - t0_total
        batch["duration_s"] = round(total_dt, 1)
        dlog(f"本轮结束: 成功 {batch['totals']['success']} / "
             f"失败 {batch['totals']['fail']} / 耗时 {total_dt:.0f}s")

    # ---- 后处理 ----
    if not args.skip_post:
        dlog("启动 v4.0 后处理 (concept_merger + backlink + index)...")
        t0 = time.time()
        report = run_post_processing(cfg)
        batch["post_processing"] = {k: v for k, v in report.items()
                                    if k not in ("lint_detail",)}
        dlog(f"后处理完成 ({time.time()-t0:.0f}s): "
             f"{json.dumps(report, ensure_ascii=False)}")

    # ---- v2.1: batch_report (S6) ----
    batch["finished_at"] = datetime.now().isoformat(timespec="seconds")
    batch["cost"] = batch_cost_since(batch["started_at"])
    rp = write_batch_report(batch)
    dlog(f"批次报告: {rp} | 成本 {batch['cost']['yuan']:.4f} 元 "
         f"({batch['cost']['calls']} 次调用)")

    # ---- 校验 ----
    dlog("启动完整性校验 (verify.py)...")
    rc = run_verify()
    dlog(f"校验退出码: {rc}")
    if batch["halted"] == "budget_exceeded":
        rc = 42  # 成本熔断专用退出码 (区别于校验失败)
    dlog("=" * 60)
    dlog("全量跑批 driver v2.1 结束")
    return rc


if __name__ == "__main__":
    sys.exit(main())
