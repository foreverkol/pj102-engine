"""
v3.0 daily_incremental.py - 增量调度器(§v7.0 + FR-006)

工作流:
  1. 加载 processed_files.json(已处理文件清单)
  2. 扫描 source_dir 新文件
  3. 只对新增文件跑完整 pipeline(12+2 步)
  4. 追加到 processed_files.json
  5. 触发 lint_wiki.py 巡检

不重处理已存在文件(content_hash 跳过)

v3.0 修复:
  - 自定义 compute_content_hash -> 从 core 导入(统一)
  - CLI 硬编码 SYSTEM/state/ -> cfg.paths(跨平台)
  - placeholder_pipeline -> 真实调用 pipeline.process_one
  - 接入 core.config + core.logging
"""

import json
import sys
from pathlib import Path
from datetime import datetime, timezone
from typing import List

sys.path.insert(0, str(Path(__file__).parent))

from core import AppConfig, compute_content_hash, get_logger, setup_logging


def load_processed(state_file: Path) -> dict:
    """加载已处理文件状态"""
    if not state_file.exists():
        return {"version": "1.0", "last_updated": "", "processed": []}
    return json.loads(state_file.read_text(encoding="utf-8"))


def save_processed(state_file: Path, state: dict):
    """持久化"""
    state["last_updated"] = datetime.now(timezone.utc).isoformat()
    state_file.parent.mkdir(parents=True, exist_ok=True)
    state_file.write_text(
        json.dumps(state, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def find_new_files(source_dir: Path, state: dict) -> List[Path]:
    """扫描 source_dir,返回新文件列表"""
    processed_hashes = {p["content_hash"] for p in state.get("processed", [])}
    new_files = []
    for md_file in source_dir.glob("*.md"):
        try:
            content = md_file.read_text(encoding="utf-8")
        except Exception:
            continue
        h = compute_content_hash(content)
        if h not in processed_hashes:
            new_files.append(md_file)
    return new_files


def mark_processed(state: dict, file_path: Path, content_hash: str,
                  result: dict):
    """追加 processed 清单"""
    state.setdefault("processed", []).append({
        "filename": file_path.name,
        "content_hash": content_hash,
        "processed_at": datetime.now(timezone.utc).isoformat(),
        "s2_scene_type": result.get("s2", {}).get("scene_type"),
        "s11_value_score": result.get("s11", {}).get("value_score"),
        "wiki_files_written": result.get("wiki_files_written", 0),
        "status": "ok",
    })


def run_incremental(
    source_dir: Path,
    state_file: Path,
    pipeline_fn=None,
    lint_fn=None,
    feishu_alert_fn=None,
    dry_run: bool = False,
) -> dict:
    """主入口

    Args:
        source_dir: 源文件目录(放 _原文.md)
        state_file: processed_files.json
        pipeline_fn: 单文件处理函数(pipeline.process_one 等价)
        lint_fn: lint_wiki.lint_wiki 函数
        feishu_alert_fn: 飞书告警函数
        dry_run: 只报告不处理

    Returns:
        {
            "new_files": [...],
            "processed_count": int,
            "skipped_count": int,
            "errors": [...],
            "started_at": str,
            "finished_at": str,
        }
    """
    source_dir = Path(source_dir)
    state_file = Path(state_file)
    state = load_processed(state_file)
    new_files = find_new_files(source_dir, state)
    report = {
        "new_files": [str(f) for f in new_files],
        "processed_count": 0,
        "skipped_count": 0,
        "errors": [],
        "started_at": datetime.now(timezone.utc).isoformat(),
        "finished_at": "",
    }

    if dry_run:
        report["finished_at"] = datetime.now(timezone.utc).isoformat()
        return report

    if not pipeline_fn:
        report["errors"].append("pipeline_fn not provided")
        report["finished_at"] = datetime.now(timezone.utc).isoformat()
        return report

    processed_count = 0
    for f in new_files:
        try:
            content = f.read_text(encoding="utf-8")
            content_hash = compute_content_hash(content)
            result = pipeline_fn(f, content, content_hash)
            if result.get("ok"):
                mark_processed(state, f, content_hash, result)
                processed_count += 1
        except Exception as e:
            report["errors"].append(f"{f.name}: {e}")

    save_processed(state_file, state)
    report["processed_count"] = processed_count
    report["skipped_count"] = len(new_files) - processed_count
    report["finished_at"] = datetime.now(timezone.utc).isoformat()

    # 触 lint
    if lint_fn and processed_count > 0:
        try:
            lint_report = lint_fn()
            report["lint_summary"] = {
                "graph_orphans": len(lint_report.get("1_graph_orphans", [])),  # T-P5.4 更名
                "content_orphans": len(lint_report.get("12_content_orphans", [])),
                "missing_sources": len(lint_report.get("3_missing_sources", [])),
                "required_violations": len(
                    lint_report.get("8_required_field_violations", [])
                ),
            }
            if feishu_alert_fn:
                feishu_alert_fn(lint_report)
        except Exception as e:
            report["errors"].append(f"lint failed: {e}")

    # v4.0 缺口7: 关联页面更新 (知识复利闭环)
    # 新文件处理后, 触发 concept_merger + backlink_builder + index_builder
    if processed_count > 0:
        post_report = _run_post_processing(cfg)
        if post_report:
            report["post_processing"] = post_report

    return report


def _run_post_processing(cfg) -> dict:
    """关联页面更新: concept_merger + backlink_builder + index_builder

    实现 Karpathy 缺口7: 新资料触发关联页面更新 (知识复利飞轮)
    """
    report = {"concepts_merged": 0, "backlinks_updated": 0, "index_rebuilt": False}
    try:
        # 1. concept_merger (合并同名概念)
        try:
            from concept_merger import merge_all_concepts
            from llm_client import LLMClient
            llm = LLMClient()
            merge_result = merge_all_concepts(cfg=cfg, llm_client=llm)
            report["concepts_merged"] = merge_result.get("merged_count", 0)
        except Exception as e:
            report["concept_merger_error"] = str(e)
    except Exception:
        pass

    # 2. backlink_builder (重建反向链接)
    try:
        from backlink_builder import build_backlinks
        bl_result = build_backlinks(cfg)
        report["backlinks_updated"] = bl_result.get("backlinks_added", 0)
    except Exception as e:
        report["backlink_error"] = str(e)

    # 3. index_builder (更新主索引)
    try:
        from index_builder import build_index
        idx_result = build_index(cfg, action="daily_incremental post-processing")
        report["index_rebuilt"] = idx_result.get("total", 0) > 0
        report["index_total"] = idx_result.get("total", 0)
    except Exception as e:
        report["index_error"] = str(e)

    return report


# ============ CLI ============

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="PJ-102 daily_incremental.py v3.0")
    parser.add_argument("--source", default=None,
                       help="源文件目录(默认 cfg.paths.data_raw)")
    parser.add_argument("--state", default=None,
                       help="已处理文件状态(默认 cfg.paths.processed_state)")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args()

    cfg = AppConfig()
    logger = setup_logging(cfg.paths.logs_dir)

    source_dir = Path(args.source) if args.source else cfg.paths.data_raw
    state_file = Path(args.state) if args.state else cfg.paths.processed_state

    logger.info(f"增量调度: source={source_dir}, state={state_file}",
                step="daily_incremental")

    # 真实 pipeline 注入(调用 pipeline.process_one)
    def real_pipeline(file_path, content, content_hash):
        """真实调用 pipeline.process_one + s12 写入"""
        try:
            from pipeline import process_one, _run_integrations
            from llm_client import LLMClient
            from steps.s12_wiki import s12_write_all_5_types

            llm = LLMClient()
            sample = {
                "filename": file_path.name,
                "content_hash": content_hash,
            }
            result = process_one(sample, llm, cfg, integrate=True)
            out_paths = s12_write_all_5_types(result, cfg)
            total = sum(len(v) for v in out_paths.values())
            return {
                "ok": True,
                "wiki_files_written": total,
                "s2": result.get("s2", {}),
                "s11": result.get("s11", {}),
            }
        except Exception as e:
            logger.error(f"pipeline 处理失败 {file_path.name}: {e}",
                         step="daily_incremental")
            return {"ok": False, "error": str(e)}

    # 真实 lint 注入
    def real_lint():
        try:
            from lint_wiki import lint_wiki
            return lint_wiki(cfg.paths.wiki_base)
        except Exception as e:
            logger.error(f"lint 失败: {e}", step="daily_incremental")
            return {}

    report = run_incremental(
        source_dir=source_dir,
        state_file=state_file,
        pipeline_fn=real_pipeline if not args.dry_run else None,
        lint_fn=real_lint,
        dry_run=args.dry_run,
    )

    print(json.dumps(report, ensure_ascii=False, indent=2))
