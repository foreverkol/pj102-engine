"""PJ-102-LLM-MeetingKB · 主入口 v4.0-refactor

用法:
    python pipeline.py                       # 跑全部(受 sample_limit 限制, 默认 10)
    python pipeline.py --limit 13           # 跑 13 个样本(上限可放宽)
    python pipeline.py --no-llm             # mock 模式(不调 LLM)
    python pipeline.py --clear              # 先清空 WIKI
    python pipeline.py --provider minimax   # 指定 provider
    python pipeline.py --dry-run            # 干跑, 不写文件
    python pipeline.py --no-integrate       # 跳过集成钩子(只跑主干+S12)
    python pipeline.py --resume             # 断点续跑(跳过已处理)

v4.0 重构修复:
  - WIKI_BASE 硬编码 /mnt/d/... -> AppConfig 跨平台路径(Windows 可跑)
  - 8 集成模块 pipeline 零调用 -> process_one 末尾 _run_integrations 钩子链
  - print+emoji -> 结构化 logging
  - 无断点续跑 -> --resume 基于 processed_files.json 跳过
  - SAMPLE_LIMIT 硬编码 -> config 可配(守SAMPLE_LIMIT<=10 铁律)
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

# 添加 code 目录到 path(支持 import core / llm_client / steps)
sys.path.insert(0, str(Path(__file__).parent))

from core import AppConfig, get_logger, setup_logging
from llm_client import LLMClient
from steps import (
    s1_basic_info, s2_scene_recognition, s3_standard_summary,
    s4_fjv, s5_implicit_knowledge, s6_entity_extraction,
    s7_action_decision, s8_risk_blindspot, s9_knowledge_classify,
    s10_cognitive_refine, s11_value_rating, s12_write_wiki,
    s12_write_all_5_types,
    s13_financial_params, s14_scenario,
)


def load_index(cfg: AppConfig) -> dict:
    """加载样本索引(跨平台路径)"""
    if not cfg.paths.data_index.exists():
        logger = get_logger()
        logger.error(f"找不到 index: {cfg.paths.data_index}")
        logger.info("请先运行: python scripts/build_index.py")
        sys.exit(1)
    return json.loads(cfg.paths.data_index.read_text(encoding="utf-8"))


def is_processed(cfg: AppConfig, content_hash: str) -> bool:
    """断点续跑: 检查 content_hash 是否已处理

    P4 T-P4.7: 仅 status=="ok" 的条目视为已处理. 历史墓碑条目
    (如 skipped_invalid, 旧校验规则拒绝的文件) 不阻塞复检——
    摄入校验规则升级(如 v1.1 file_class 分型)后, 被误杀文件可重新入队.
    """
    if not cfg.paths.processed_state.exists():
        return False
    try:
        state = json.loads(cfg.paths.processed_state.read_text(encoding="utf-8"))
        return any(p.get("content_hash") == content_hash
                   and p.get("status", "ok") == "ok"
                   for p in state.get("processed", []))
    except Exception:
        return False


def mark_processed(cfg: AppConfig, filename: str, content_hash: str,
                   result: dict) -> None:
    """记录已处理(用于断点续跑 + daily_incremental 复用)

    v2.2.4 (2026-09-15, 分叉 #1 清账): 原实现只 append、从不同步 count 元数据,
    导致 count 永久冻结在最后一次 ingest_source 运行时的值 (实例实测 39 vs 实际 43)。
    本版同时补重跑幂等 —— 清掉同 content_hash 的旧 ok 条目;
    墓碑 (skipped_invalid 等) 一律保留, 因 is_processed() 只认 status=="ok",
    墓碑是"校验规则升级后可重新入队"的刻意设计。
    """
    state = {"version": "1.0", "processed": []}
    if cfg.paths.processed_state.exists():
        try:
            state = json.loads(cfg.paths.processed_state.read_text(encoding="utf-8"))
        except Exception:
            pass
    proc = state.setdefault("processed", [])
    # 重跑幂等: 同 content_hash 的旧 ok 条目先出栈 (墓碑保留)
    proc[:] = [x for x in proc
               if not (x.get("content_hash") == content_hash
                       and x.get("status", "ok") == "ok")]
    proc.append({
        "filename": filename,
        "content_hash": content_hash,
        "processed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "s2_scene_type": result.get("s2", {}).get("scene_type"),
        "s11_value_score": result.get("s11", {}).get("value_score"),
        "wiki_files_written": sum(
            len(v) for v in result.get("_integrations", {}).values()
            if isinstance(v, dict)
        ),
        "status": "ok",
    })
    state["count"] = len(proc)  # v2.2.4: 与 ingest_source.py 口径一致 (含墓碑)
    state["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    cfg.paths.processed_state.parent.mkdir(parents=True, exist_ok=True)
    cfg.paths.processed_state.write_text(
        json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


# ============================================================================
# B3 缓存熔断 (2026-09-16)
# ----------------------------------------------------------------------------
# 实证背景: 2 个样本的 s3 产出为哨兵值 "未提取" 仍被照写盘 → 下游 s15 重放抛
# S15MissingS3, 重放链断裂, 而批跑依然报"成功"。缓存是「可信重放」的契约,
# 写入退化产物即违约。结论: 补跑治标, 熔断治本。
#
# 判据保守(只判明确退化):
#   ① s3: one_sentence 为空/占位 (已实证的哨兵签名)
#   ② 任意 dict 步: 全字段空/占位
#   s13/s14 合法产物是 list, 空 list **不**判退化 (2026-09-16 实测修正, 防误报)
# 兜底开关: PJ102_FUSE_DISABLE=1 临时关闭(应急), 默认启用。
# ============================================================================
FUSE_PLACEHOLDERS = {"", "未提取", "N/A", "n/a", "null", "None",
                     "无", "未知", "待补充"}
FUSE_LIST_STEPS = {"s13", "s14"}


def _fuse_deg(v) -> bool:
    if v is None:
        return True
    if isinstance(v, str):
        return v.strip() in FUSE_PLACEHOLDERS
    if isinstance(v, (list, dict)):
        return len(v) == 0
    return False


def fuse_check(step: str, data):
    """缓存熔断判据 — 两级, 避免误伤合法空产出。

    返回 (level, reason):
      ('hard', why)  —— 已实证的确定性退化, **中止该样本** (不写缓存)
      ('soft', why)  —— 可疑空产出, **不写缓存但不中止** (下次可重试; 不误伤批次)
      (None, None)   —— 放行

    分级理由: "确实无风险/无决策"是合法业务形态 (如 s8 risks 空), 若一律中止
    会误伤批次; 但结论是「缓存只应存可信产物」—— 故软级也拒绝落盘。
    """
    if os.environ.get("PJ102_FUSE_DISABLE") == "1":
        return None, None
    if step in FUSE_LIST_STEPS or isinstance(data, list):
        return None, None
    if not isinstance(data, dict):
        return "hard", f"非预期类型 {type(data).__name__}"
    if not data:
        return "hard", "空 dict (无任何产出)"
    if step == "s3" and _fuse_deg(data.get("one_sentence")):
        return "hard", f"s3.one_sentence 为空/占位: {data.get('one_sentence')!r}"
    if all(_fuse_deg(v) for v in data.values()):
        return "soft", "全字段空/占位 (可能确无产出, 也可能退化 —— 不落盘待复核)"
    return None, None


def fuse_reason(step: str, data):
    """兼容入口: 返回退化理由字符串或 None"""
    return fuse_check(step, data)[1]


def process_one(sample: dict, llm: LLMClient, cfg: AppConfig,
                integrate: bool = True) -> dict:
    """处理一个样本的 12+2 步全流程 + 集成钩子

    v4.0 新增: integrate 参数控制是否跑集成钩子链(默认 True)
    """
    logger = get_logger()
    raw_file = cfg.paths.data_raw / sample["filename"]
    if not raw_file.exists():
        raise FileNotFoundError(f"找不到源文件: {raw_file}")
    content = raw_file.read_text(encoding="utf-8")

    # v4.1 step 缓存: 沙箱 30s reap 后 retry 时跳过已成功步骤
    # 目录: system/cache/steps/{content_hash}/s1.json, s2.json ...
    cache_dir = (cfg.paths.system_dir / "cache" / "steps" / sample["content_hash"]).resolve()
    cache_dir.mkdir(parents=True, exist_ok=True)

    def _cache_get(step):
        p = cache_dir / f"{step}.json"
        if p.exists():
            try:
                return json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                return None
        return None

    # === B3 缓存熔断接线 (判据见模块级 fuse_check, 可单测) ===
    def _cache_put(step, data):
        level, why = fuse_check(step, data)
        if level == "hard":
            msg = (f"缓存熔断[中止] {step} [{sample['filename'][:30]}]: {why}"
                   f" —— 拒绝写入退化产物(下游重放链会因此断裂)")
            sys.stderr.write(f"FUSE  {msg}\n")
            sys.stderr.flush()
            raise RuntimeError(msg)
        if level == "soft":
            sys.stderr.write(
                f"FUSE  [软熔断·不落盘] {step} [{sample['filename'][:30]}]: "
                f"{why} —— 本次不写缓存, 保持可重试\n")
            sys.stderr.flush()
            return
        try:
            (cache_dir / f"{step}.json").write_text(
                json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        except Exception as e:
            sys.stderr.write(f"WARN  缓存写入失败 {step}: {e}\n")

    # 主干 12+2 步(守正, 不改业务逻辑)
    import time as _t, threading as _th
    _pulse_stop = _th.Event()
    def _pulse():
        n = 0
        while not _pulse_stop.is_set():
            n += 1
            sys.stdout.write(f"  [pulse {n}] {sample['filename'][:25]} alive t={_t.time()-_t0:.0f}s\n"); sys.stdout.flush()
            _pulse_stop.wait(5)
    _t0 = _t.time()
    _th.Thread(target=_pulse, daemon=True).start()
    def _hb(step): sys.stdout.write(f"  [heartbeat] {sample['filename'][:30]} {step} t={_t.time()-_t0:.0f}s\n"); sys.stdout.flush()
    # D-74 (2026-09-17 实证): 脉冲线程的停止必须放在 `finally`。
    #   原实现只在成功路径末尾 `_pulse_stop.set()`，而**抛异常的样本会让这个
    #   daemon 线程永久泄漏**（pipeline 由 driver 长驻进程串行调用 30 次也不回收）。
    #   后果不止日志噪声 —— 泄漏线程以 5s 周期继续写
    #   `  [pulse n] <样本名> alive t=NNNNs`，多个不同 `_t0` 的线程叠加后，
    #   日志呈现出「多个样本同时在跑」的假象。E1 复盘时据此一度误判为**并发跑批**，
    #   查证 run_full 无任何 Thread/Pool 后才定位到泄漏（通则：观测装置自身会污染判断）。
    try:
        # s1 不调 LLM(纯规则), 直接缓存
        _hb("s1");  s1 = s1_basic_info(sample["filename"], content); _cache_put("s1", s1)
        # s2-s14 先查缓存, 跳过已成功步骤
        def _step(step, fn):
            cached = _cache_get(step)
            if cached is not None:
                sys.stdout.write(f"  [cache-hit] {step}\n"); sys.stdout.flush()
                return cached
            _hb(step)
            val = fn()
            _cache_put(step, val)
            return val

        s2 = _step("s2", lambda: s2_scene_recognition(content, llm))
        s3 = _step("s3", lambda: s3_standard_summary(content, llm))
        s4 = _step("s4", lambda: s4_fjv(content, llm))
        s5 = _step("s5", lambda: s5_implicit_knowledge(content, llm))
        s6 = _step("s6", lambda: s6_entity_extraction(content, llm))
        s7 = _step("s7", lambda: s7_action_decision(content, llm))
        s8 = _step("s8", lambda: s8_risk_blindspot(content, llm))
        s9 = _step("s9", lambda: s9_knowledge_classify(content, llm))
        s10 = _step("s10", lambda: s10_cognitive_refine(content, llm))
        s11 = _step("s11", lambda: s11_value_rating(content, llm))
        s13 = _step("s13", lambda: s13_financial_params(content, llm))
        s14 = _step("s14", lambda: s14_scenario(content, llm))
        sys.stdout.write(f"  [heartbeat] {sample['filename'][:30]} s1-s14 done in {_t.time()-_t0:.0f}s\n"); sys.stdout.flush()
    finally:
        _pulse_stop.set()

    state = {
        "sample": sample["filename"],
        "content_hash": sample["content_hash"],
        "s1": s1, "s2": s2, "s3": s3, "s4": s4, "s5": s5,
        "s6": s6, "s7": s7, "s8": s8, "s9": s9, "s10": s10, "s11": s11,
        "s13": s13, "s14": s14,
        "_meta": {
            "llm_provider": llm.provider,
            "llm_model": llm.model,
            "version": cfg.version,
        },
    }

    # 集成钩子链(v4.0 新增: 8 模块真正接入, 容错不阻断)
    if integrate:
        _run_integrations(state, cfg, logger)

    # v4.2 W2-T2.1: s15 摘要锚点页 (0 LLM, 读 s3 渲染; 集成后调用以便实体页就位)
    # 容错不阻断主干; 失败可由 backfill_s15.py / 重跑(缓存) 补
    try:
        from steps.s15_summary_page import s15_summary_page
        s15 = _cache_get("s15")
        if s15 is None:
            _hb("s15")
            s15 = s15_summary_page(
                {**state, "file_type": sample.get("file_type", "")}, cfg)
            _cache_put("s15", s15)
        state["s15"] = s15
    except Exception as e:
        sys.stderr.write(f"WARN  s15 摘要页生成失败(不阻断): {e}\n")

    return state


def _run_integrations(state: dict, cfg: AppConfig, logger) -> None:
    """集成钩子链: entity_resolver / citations / scenario_extractor / review_queue

    每个模块独立 try/except, 失败记日志不阻断主干.
    回写 entity_id 到 s6 persons/organizations, 供 s12 写入 frontmatter.
    """
    integ = {}

    # 1. entity_resolver - v7.0 实体统一编号 + 消歧
    try:
        from entity_resolver import EntityResolver
        resolver = EntityResolver(cfg.paths.registry_path)
        counter = {"resolved": 0, "skipped_junk": 0}

        def _assign(items, etype):
            """编号并**剔除机器标签**（源稿口条/占位符），返回过滤后的列表。

            为什么必须剔除而不是只打标记：s12 是"遍历 persons 建页"的，
            留下就会生成 `发言人2.md` 这类垃圾实体页（2026-09-16 实测：
            registry 9 个垃圾 canonical + wiki 同名页）。
            """
            out = []
            for it in items:
                if not (isinstance(it, dict) and it.get("name")):
                    continue
                r = resolver.resolve_or_create(
                    etype, it["name"], it.get("aliases", []))
                if r.get("action") == "skip":
                    counter["skipped_junk"] += 1
                    continue
                it["entity_id"] = r["entity_id"]      # 回写, s12 写 frontmatter
                it["canonical_name"] = r.get("canonical_name", it["name"])
                counter["resolved"] += 1
                out.append(it)
            return out

        s6 = state.get("s6") or {}
        if isinstance(s6.get("persons"), list):
            s6["persons"] = _assign(s6["persons"], "person")
        if isinstance(s6.get("organizations"), list):
            s6["organizations"] = _assign(s6["organizations"], "organization")
        resolver.save()
        integ["entity_resolver"] = dict(counter)
    except Exception as e:
        logger.warning(f"entity_resolver 集成失败: {e}", step="integration")

    # 2. citations - v7.0 extraction_patch YAML 中间层
    try:
        from citations import write_citations_intermediate
        citations_dir = cfg.paths.system_dir / "citations"
        ldamc = state.get("s10", {}).get("ldamc")
        written = write_citations_intermediate(state, citations_dir, ldamc=ldamc)
        integ["citations"] = {"written": len(written)}
    except Exception as e:
        logger.warning(f"citations 集成失败: {e}", step="integration")

    # 3. scenario_extractor - v7.0 scenario 写 Knowledge/Scenarios/
    try:
        from scenario_extractor import write_scenarios
        scenarios = state.get("s14", [])
        if scenarios:
            written = write_scenarios(
                scenarios, cfg.paths.wiki_base,
                source_ref=state.get("sample", ""),
                meeting_date=state.get("s1", {}).get("date", ""))
            integ["scenario_extractor"] = {"written": len(written)}
    except Exception as e:
        logger.warning(f"scenario_extractor 集成失败: {e}", step="integration")

    # 4. review_queue - 三级分流
    try:
        from review_queue import enqueue
        queue_root = cfg.paths.system_dir / "review_queue"
        enqueued = 0
        for j in state.get("s4", {}).get("judgments", []):
            if isinstance(j, str):
                enqueue({
                    "type": "judgment",
                    "title": j[:60],
                    "source_ref": state.get("sample", ""),
                    "status_stage": "compiled",
                    "judgment": j,
                    "topic_key": state.get("s7", {}).get("topic_key", ""),
                }, queue_root)
                enqueued += 1
        integ["review_queue"] = {"enqueued": enqueued}
    except Exception as e:
        logger.warning(f"review_queue 集成失败: {e}", step="integration")

    state["_integrations"] = integ


def clear_wiki(cfg: AppConfig) -> None:
    """清空所有 WIKI(跨平台)"""
    logger = get_logger()
    if cfg.paths.wiki_base.exists():
        for sub in [cfg.paths.wiki_meetings, cfg.paths.wiki_persons,
                    cfg.paths.wiki_organizations, cfg.paths.wiki_concepts,
                    cfg.paths.wiki_judgments, cfg.paths.wiki_comparisons,
                    cfg.paths.wiki_scenarios]:
            if sub.exists():
                for f in sub.glob("*.md"):
                    f.unlink()
        logger.info("已清空 WIKI")


def main() -> int:
    parser = argparse.ArgumentParser(description="PJ-102-LLM-MeetingKB Pipeline v4.0")
    parser.add_argument("--limit", type=int, default=0,
                        help="限制样本数(0=全部, 受 config sample_limit 上限)")
    parser.add_argument("--no-llm", action="store_true", help="跳过 LLM(mock)")
    parser.add_argument("--clear", action="store_true", help="先清空 WIKI")
    parser.add_argument("--provider", type=str, default="auto", help="LLM provider")
    parser.add_argument("--dry-run", action="store_true", help="干跑, 不写文件")
    parser.add_argument("--no-integrate", action="store_true",
                        help="跳过集成钩子(只跑主干+S12)")
    parser.add_argument("--resume", action="store_true",
                        help="断点续跑, 跳过已处理")
    args = parser.parse_args()

    cfg = AppConfig()
    logger = setup_logging(cfg.paths.logs_dir)
    cfg.paths.ensure_dirs()

    if args.clear:
        clear_wiki(cfg)

    if args.no_llm:
        for k in ["DEEPSEEK_API_KEY", "MINIMAX_API_KEY",
                  "MINIMAX_CN_API_KEY",  # 本项目适配: hermes 命名
                  "OPENAI_API_KEY", "ANTHROPIC_API_KEY"]:
            os.environ[k] = ""

    llm = LLMClient(provider=args.provider)
    logger.info(f"LLM Provider: {llm.provider} / {llm.model}")
    logger.info(f"WIKI 输出: {cfg.paths.wiki_base}")
    logger.info(f"集成钩子: {'OFF' if args.no_integrate else 'ON'}")

    index = load_index(cfg)
    samples = index.get("samples", [])
    limit = args.limit if args.limit > 0 else cfg.sample_limit
    if args.resume:
        # v4.0.1 修复: resume 模式先过滤已处理样本再取 limit 个.
        # 原逻辑窗口固定在前 N 个, 已处理的占位导致批量续跑无法前进.
        samples = [s for s in samples
                   if not is_processed(cfg, s.get("content_hash", ""))]
    samples = samples[:limit]
    logger.info(f"共 {len(samples)} 个样本待处理(limit={limit})")

    success = 0
    fail = 0
    skipped = 0
    total_time = 0.0

    for i, sample in enumerate(samples, 1):
        short = sample["filename"][:40]

        # 断点续跑
        if args.resume and is_processed(cfg, sample["content_hash"]):
            skipped += 1
            logger.info(f"[{i}/{len(samples)}] {short} 已处理, 跳过",
                        sample=short)
            continue

        logger.info(f"[{i}/{len(samples)}] {short} 开始处理", sample=short)
        start = time.time()
        try:
            result = process_one(sample, llm, cfg,
                                 integrate=not args.no_integrate)
            if not args.dry_run:
                out_paths = s12_write_all_5_types(result, cfg)
                total = sum(len(v) for v in out_paths.values())
                elapsed = time.time() - start
                total_time += elapsed
                parts = [f"{k[0]}:{len(v)}" for k, v in out_paths.items()]
                logger.info(
                    f"[{i}/{len(samples)}] {short} 完成 "
                    f"({elapsed:.1f}s) 产出 {total} 个 [{', '.join(parts)}]",
                    sample=short)
                # 记录已处理(断点续跑)
                if not args.no_integrate or True:
                    mark_processed(cfg, sample["filename"],
                                   sample["content_hash"], result)
            else:
                logger.info(f"[{i}/{len(samples)}] {short} dry-run", sample=short)
            success += 1
        except Exception as e:
            logger.error(f"[{i}/{len(samples)}] {short} 失败: {e}", sample=short)
            fail += 1

    avg = total_time / success if success else 0
    logger.info(f"完成: {success} 成功 / {fail} 失败 / {skipped} 跳过, "
                f"总耗时 {total_time:.1f}s, 平均 {avg:.1f}s/文件")
    return 0 if fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
