"""judgments_master 聚合器 — dispute_detector 通电前置 (W1-T0.1b)

从 41 个 step 缓存的 s7.json 聚合决策/判断数据为 system/state/judgments_master.json，
对齐 code/dispute_detector.py 的读取结构 {"judgments": {id: {...}}}。

字段映射说明（尽调核实 2026-09-09）：
- s7.decisions[].topic_key → judgments.{id}.topic_key   （唯一对齐字段）
- s7.decisions[].decision  → judgments.{id}.judgment
- meeting_id               ← index.json 的源文件名（hash 反查）
- stance                   → "unlabeled"（⚠️ 数据链路无 stance 字段：
                              s7 提取提示词未产出、判断页 frontmatter 亦无。
                              dispute_detector 需要 support+oppose 才触发冲突检测，
                              "unlabeled" 安全不误报。激活路径：W4 改 s7 提示词加 stance 提取。）

幂等：重跑覆盖输出文件，无副作用。用法：
    python code/judgments_aggregator.py
"""
import json
import sys
from pathlib import Path
from datetime import datetime, timezone

PROJECT_ROOT = Path(os.environ.get("PJ102_PROJECT_ROOT") or Path.cwd())
CACHE_STEPS = PROJECT_ROOT / "system" / "cache" / "steps"
INDEX_JSON = PROJECT_ROOT / "system" / "state" / "index.json"
OUT_JSON = PROJECT_ROOT / "system" / "state" / "judgments_master.json"


def _load_hash_to_meeting() -> dict:
    """hash → 源文件名（作 meeting_id）"""
    if not INDEX_JSON.exists():
        return {}
    ix = json.loads(INDEX_JSON.read_text(encoding="utf-8"))
    return {s["content_hash"]: s["filename"] for s in ix.get("samples", []) if s.get("content_hash")}


def aggregate() -> dict:
    h2m = _load_hash_to_meeting()
    judgments = {}
    n_samples = 0

    for hash_dir in sorted(CACHE_STEPS.iterdir()) if CACHE_STEPS.exists() else []:
        s7 = hash_dir / "s7.json"
        if not s7.exists():
            continue
        try:
            data = json.loads(s7.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        decisions = data.get("decisions") or []
        if not decisions:
            continue
        n_samples += 1
        meeting_id = h2m.get(hash_dir.name, hash_dir.name)

        for i, d in enumerate(decisions):
            if not isinstance(d, dict):
                continue
            j_id = f"{hash_dir.name}_d{i+1}"
            judgments[j_id] = {
                "topic_key": d.get("topic_key", ""),
                "stance": "unlabeled",  # 见模块 docstring：W4 激活
                "meeting_id": meeting_id,
                "judgment": d.get("decision", ""),
                "topic": d.get("topic_key", "").split("/")[-1] if d.get("topic_key") else "",
                "owner": d.get("owner", ""),
                "deadline": d.get("deadline", ""),
                "quote_orig": d.get("quote_orig", ""),
            }

    return {
        "judgments": judgments,
        "meta": {
            "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "n_samples": n_samples,
            "n_judgments": len(judgments),
            "stance_coverage": 0,  # unlabeled 占比 100%，待 W4 提示词增强后上升
        },
    }


def main() -> int:
    result = aggregate()
    OUT_JSON.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    m = result["meta"]
    print(f"[OK] judgments_master.json: {m['n_judgments']} judgments from {m['n_samples']} samples")
    print(f"     -> {OUT_JSON}")
    # 同 topic_key 分组预览（dispute 候选视图）
    by_topic = {}
    for j in result["judgments"].values():
        if j["topic_key"]:
            by_topic.setdefault(j["topic_key"], []).append(j)
    multi = {k: v for k, v in by_topic.items() if len(v) > 1}
    print(f"     同主题多判断分组（人工审阅候选）: {len(multi)} 组")
    for k, v in sorted(multi.items(), key=lambda x: -len(x[1]))[:5]:
        print(f"       {k}: {len(v)} 条判断")
    return 0


if __name__ == "__main__":
    sys.exit(main())
