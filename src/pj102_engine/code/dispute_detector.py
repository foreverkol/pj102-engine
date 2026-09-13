"""
v7.0 §v7.0-002 + §v7.0-006 矛盾检测器

核心:
  - judgments_master.json 按 topic_key 分组(§v7.0-006)
  - 同 topic_key + cross stance (support vs oppose) → 自动加
    <!-- Status: Disputed -->
  - 输出 v7.0 contradictions 字段格式
"""

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path


# v7.0 stance 取值
STANCE_VALUES = {"support", "caution", "oppose", "mixed"}


def detect_disputes(judgments_master_path: Path, wiki_dir: Path) -> list:
    """主入口:返回 dispute 列表

    Returns: [{"topic_key": str, "type": "conflict",
                "judgments": [j1, j2, ...],
                "resolution": "pending_review",
                "meeting_ids": [m1, m2]}]
    """
    jm_path = Path(judgments_master_path)
    if not jm_path.exists():
        return []

    jm = json.loads(jm_path.read_text(encoding="utf-8"))

    # 按 topic_key 分组
    by_topic = {}
    for j_id, j_data in jm.get("judgments", {}).items():
        topic_key = j_data.get("topic_key")
        stance = j_data.get("stance", "mixed")
        if not topic_key:
            continue
        by_topic.setdefault(topic_key, []).append({
            "id": j_id,
            "topic_key": topic_key,
            "stance": stance,
            "meeting_id": j_data.get("meeting_id"),
            "judgment": j_data.get("judgment", ""),
            "topic": j_data.get("topic", ""),
        })

    # 检测 cross stance
    disputes = []
    for topic_key, judgments in by_topic.items():
        stances = {j["stance"] for j in judgments}
        if "support" in stances and "oppose" in stances:
            disputes.append({
                "topic_key": topic_key,
                "type": "conflict",
                "judgments": judgments,
                "resolution": "pending_review",
                "meeting_ids": [j["meeting_id"] for j in judgments if j.get("meeting_id")],
            })

    # 写文件:在对应 judgment md 中加 <!-- Status: Disputed -->
    _mark_disputed_in_wiki(disputes, wiki_dir)
    return disputes


def _mark_disputed_in_wiki(disputes: list, wiki_dir: Path) -> int:
    """在 judgments/ 目录对应 md 文件加 Disputed 块"""
    wiki_dir = Path(wiki_dir)
    judgments_dir = wiki_dir / "Knowledge" / "Judgments"
    if not judgments_dir.exists():
        return 0

    marked = 0
    for d in disputes:
        topic_key = d["topic_key"]
        # topic_key → slug 反查文件名
        for j in d["judgments"]:
            jid = j.get("id", "")
            # 找 md 文件(可能含 judgment_id 或 topic slug)
            for md_file in judgments_dir.glob(f"*{jid}*.md"):
                _add_disputed_block(md_file, d)
                marked += 1
    return marked


def _add_disputed_block(md_file: Path, dispute: dict):
    """在 md 文件加 Disputed 块(v7.0 §一)"""
    text = md_file.read_text(encoding="utf-8")

    # 已标记过就不重复
    if "Status: Disputed" in text and "by meeting" in text:
        return

    meeting_ids = dispute.get("meeting_ids", [])
    topic_key = dispute.get("topic_key", "")

    # 找到 Status: Disputed 行,在其后追加具体信息
    if "Status: Disputed" in text:
        new_text = re.sub(
            r"(<!-- Status: Disputed -->)",
            f"\\1\n  - topic_key: {topic_key}\n"
            f"  - conflicting meetings: {meeting_ids}\n"
            f"  - resolution: {dispute.get('resolution', 'pending_review')}",
            text, count=1
        )
    else:
        # 没有就追加到末尾
        new_text = text.rstrip() + f"\n\n<!-- Status: Disputed -->\n  - topic_key: {topic_key}\n  - conflicting meetings: {meeting_ids}\n  - resolution: {dispute.get('resolution', 'pending_review')}\n"

    md_file.write_text(new_text, encoding="utf-8")


# ============ CLI ============

if __name__ == "__main__":
    import sys
    if len(sys.argv) < 3:
        print("Usage: python3 dispute_detector.py <judgments_master.json> <wiki_dir>")
        sys.exit(1)

    disputes = detect_disputes(Path(sys.argv[1]), Path(sys.argv[2]))
    print(json.dumps(disputes, ensure_ascii=False, indent=2))
    print(f"\n📊 发现 {len(disputes)} 个矛盾 topic", file=sys.stderr)
