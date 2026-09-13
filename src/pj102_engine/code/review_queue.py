"""
v3.0 review_queue.py - ReviewQueue 三级分流(借鉴 PJ-001 v6.0 §9)

三级:
  - auto_pass       — 无风险 / 格式合规 / 索引,直接入库
  - batch_confirm   — 新实体/判断草案,主理人扫一眼即可
  - forced_review   — 高价值/冲突/覆盖,逐条确认

数据结构(SYSTEM/review_queue/{YYYY-MM-DD}/):
  - batch_info.json    # 本批次元信息
  - items/             # 待审核 items
  - decisions.log      # 决策流水
"""

import hashlib
import json
import sys
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import Optional


# 阈值定义
AUTO_PASS_RULES = {
    # 字段必填都满足 → auto_pass
    "all_required_fields_present": True,
    "no_high_value_keywords": True,
    "no_contradiction": True,
}

FORCED_REVIEW_KEYWORDS = [
    "推翻", "取消", "否定", "终止", "重要决策",
    "重要变更", "战略调整", "大额", "100万", "500万",
    "1000万", "千万", "亿", "颠覆", "改变方向",
]


def classify_item(item: dict) -> str:
    """三级分流主入口

    Returns: "auto_pass" | "batch_confirm" | "forced_review"
    """
    text = _extract_text(item)
    text_lower = text.lower()

    # forced_review 优先(任何高价值关键词触发)
    for kw in FORCED_REVIEW_KEYWORDS:
        if kw in text or kw.lower() in text_lower:
            return "forced_review"

    # 字段必填缺失 → batch_confirm(主理人扫一眼)
    if not _all_required_fields(item):
        return "batch_confirm"

    # contradictions 待验证 → forced_review
    contradictions = item.get("contradictions", [])
    for c in contradictions:
        if isinstance(c, dict) and c.get("resolution") == "pending_review":
            return "forced_review"

    # 都过 → auto_pass
    return "auto_pass"


def _extract_text(item: dict) -> str:
    """从 item 抽取所有文本字段拼接"""
    parts = []
    for v in item.values():
        if isinstance(v, str):
            parts.append(v)
        elif isinstance(v, list):
            for x in v:
                if isinstance(x, str):
                    parts.append(x)
                elif isinstance(x, dict):
                    for vv in x.values():
                        if isinstance(vv, str):
                            parts.append(vv)
        elif isinstance(v, dict):
            for vv in v.values():
                if isinstance(vv, str):
                    parts.append(vv)
    return " ".join(parts)


def _all_required_fields(item: dict) -> bool:
    """v7.0 §8.1 必填字段检查(简化版)"""
    required = ["type", "title", "source_ref", "status_stage"]
    return all(item.get(k) for k in required)


def _already_queued(item: dict, queue_root: Path) -> Optional[Path]:
    """按 title+source_ref 全队列查重 (v4.0 修复: 曾出现同判断重复入队)"""
    title = item.get("title", "")
    source = item.get("source_ref", "")
    if not title or not source:
        return None
    if not queue_root.exists():
        return None
    for p in queue_root.rglob("*.json"):
        if p.name == "batch_info.json":
            continue
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        inner = d.get("item", d)
        if (inner.get("title") == title
                and inner.get("source_ref") == source):
            return p
    return None


def enqueue(item: dict, queue_root: Path,
            batch_id: Optional[str] = None,
            force: bool = False) -> dict:
    """把 item 入队到对应级别目录

    v4.0: 默认按 title+source_ref 去重, 重复项跳过并返回 skipped=True;
          force=True 可强制入队。

    Returns: {batch_id, level, item_path, skipped}
    """
    # 去重检查
    dup = _already_queued(item, queue_root)
    if dup is not None and not force:
        return {"batch_id": "", "level": classify_item(item),
                "item_path": str(dup), "skipped": True,
                "reason": "duplicate title+source_ref"}

    level = classify_item(item)
    today = datetime.now(timezone.utc).date().isoformat()
    # batch_id 用 md5 前 8 位(hash() 返回 int 不能切片)
    raw = item.get('source_ref', '') + str(datetime.now(timezone.utc))
    batch_id = batch_id or f"rq-{today}-{hashlib.md5(raw.encode('utf-8')).hexdigest()[:8]}"
    batch_dir = queue_root / today / batch_id / level
    batch_dir.mkdir(parents=True, exist_ok=True)

    # 写 item
    item_id = item.get("title", "item")[:30].replace("/", "_").replace(":", "_")
    item_path = batch_dir / f"{item_id}.json"
    item_path.write_text(
        json.dumps({
            "batch_id": batch_id,
            "level": level,
            "enqueued_at": datetime.now(timezone.utc).isoformat(),
            "item": item,
        }, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    # 写 batch_info(首次)
    info_path = batch_dir.parent / "batch_info.json"
    if not info_path.exists():
        info = {
            "batch_id": batch_id,
            "date": today,
            "summary": {"auto_pass": 0, "batch_confirm": 0, "forced_review": 0},
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        info["summary"][level] = 1
        info_path.write_text(json.dumps(info, ensure_ascii=False, indent=2),
                            encoding="utf-8")
    else:
        info = json.loads(info_path.read_text(encoding="utf-8"))
        info["summary"][level] = info["summary"].get(level, 0) + 1
        info_path.write_text(json.dumps(info, ensure_ascii=False, indent=2),
                            encoding="utf-8")

    return {"batch_id": batch_id, "level": level, "item_path": str(item_path),
            "skipped": False}


# ============ CLI ============

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--item-json", required=True,
                       help="item dict as JSON string")
    parser.add_argument("--queue-root",
                       default="/mnt/d/BaiduSyncdisk/hermes/02-知识库/PJ-102-LLM-MeetingKB/SYSTEM/review_queue")
    parser.add_argument("--batch-id")
    args = parser.parse_args()

    item = json.loads(args.item_json)
    queue_root = Path(args.queue_root)
    result = enqueue(item, queue_root, batch_id=args.batch_id)
    print(json.dumps(result, ensure_ascii=False, indent=2))
