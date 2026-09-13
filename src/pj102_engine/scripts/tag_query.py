#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
tag_query.py — W4 三轴组合筛选查询工具 + P5 T-P5.2 第四维 (时间窗/来源会议)

用法:
  python scripts/tag_query.py                          # 全库四轴分布统计
  python scripts/tag_query.py --topic finance          # 按 topic 筛
  python scripts/tag_query.py --meta prediction        # 按 meta 筛
  python scripts/tag_query.py --stance caution         # 按 stance 筛
  python scripts/tag_query.py --topic finance --meta prediction   # 组合筛
  # T-P5.2 第四维:
  python scripts/tag_query.py --date-range 2026-08-01:2026-09-30   # 时间窗 (闭区间, 冒号两侧可留空=开放)
  python scripts/tag_query.py --date-range 2026-09-01:              # 2026-09-01 之后 (含)
  python scripts/tag_query.py --source-meeting 深圳培训             # 按来源会议关键词筛
  # 四维组合:
  python scripts/tag_query.py --topic finance --date-range 2026-01-01: --source-meeting 千问

有效日期口径 (T-P5.1 定稿, 按页型分字段):
  Meetings/Judgments/Scenarios/Synthesis/Entities -> date
  Summaries -> source_date / Queries -> query_date
  merged Concepts -> source_dates 列表取 max (最近关联)
  无任何日期字段 -> 不参与时间窗 (被筛除)
"""
import re
import argparse
from pathlib import Path
from collections import Counter

ROOT = Path(__file__).resolve().parent.parent
WIKI = ROOT / "wiki"
EXCLUDE = ("index.md", "log.md")


def fm_of(txt: str) -> str:
    m = re.match(r"^((?:>[^\n]*\n)+(?:\s*\n)*)---\r?\n(.*?)\r?\n---", txt, re.S)
    if m:
        return m.group(2)
    m = re.match(r"^---\r?\n(.*?)\r?\n---", txt, re.S)
    return m.group(1) if m else ""


def get_field(fm: str, key: str):
    m = re.search(rf"^{key}:\s*(.*)$", fm, re.M)
    return m.group(1).strip() if m else None


def get_topics(fm: str) -> list:
    """topics 兼容内联式 [a, b] 与块式（backlink_builder YAML 往返产物）"""
    raw = get_field(fm, "topics")
    if raw is None:
        return []
    raw = raw.strip()
    if raw.startswith("["):
        inner = raw.strip("[]").replace("'", "").replace('"', "")
        return [t.strip() for t in inner.split(",") if t.strip()]
    if raw == "":
        m = re.search(r"^topics:\s*\n((?:\s+-\s.*\n?)+)", fm, re.M)
        if m:
            return [ln.strip().lstrip("-").strip().strip("'\"")
                    for ln in m.group(1).splitlines() if ln.strip()]
    return []


_ISO = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def eff_date(fm: str, body: str):
    """T-P5.2 有效日期: 按页型分字段解析, 无日期返回 None。

    merged concept 的 source_dates 块式列表取 max (最近关联);
    文件名日期不参与 (frontmatter 语义优先, 避免双源冲突)。
    """
    for key in ("date", "source_date", "query_date"):
        v = get_field(fm, key)
        if v and _ISO.match(v.strip().strip("'\"")):
            return v.strip().strip("'\"")
    # merged concepts: source_dates 块式列表
    m = re.search(r"^source_dates:\s*\n((?:\s+-\s.*\n?)+)", fm, re.M)
    if m:
        dates = [ln.strip().lstrip("-").strip().strip("'\"")
                 for ln in m.group(1).splitlines() if ln.strip()]
        dates = [d for d in dates if _ISO.match(d)]
        if dates:
            return max(dates)
    return None


def parse_date_range(spec: str):
    """'2026-08-01:2026-09-30' -> (lo, hi); 一侧留空为开放。None 表示不过滤。"""
    if not spec:
        return None, None
    lo, _, hi = spec.partition(":")
    lo = lo.strip() or None
    hi = hi.strip() or None
    for x in (lo, hi):
        if x and not _ISO.match(x):
            raise SystemExit(f"日期格式错误 (需 YYYY-MM-DD): {x}")
    return lo, hi


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--topic", help="topic 轴筛选值")
    ap.add_argument("--meta", help="meta 轴筛选值")
    ap.add_argument("--stance", help="stance 轴筛选值")
    ap.add_argument("--date-range", dest="date_range", default="",
                    help="时间窗 (T-P5.2): 2026-08-01:2026-09-30 / 2026-09-01: / :2026-09-30")
    ap.add_argument("--source-meeting", dest="source_meeting", default="",
                    help="来源会议关键词 (T-P5.2): 页面 [[Meetings/…]] 链接或 source 含关键词")
    ap.add_argument("--limit", type=int, default=20)
    args = ap.parse_args()

    try:
        lo, hi = parse_date_range(args.date_range)
    except SystemExit:
        raise
    has_dr = bool(args.date_range)
    has_sm = bool(args.source_meeting)

    topic_c, meta_c, stance_c = Counter(), Counter(), Counter()
    hits = []
    for p in sorted(WIKI.rglob("*.md")):
        if p.name in EXCLUDE or p.name.startswith("log.legacy") or ".obsidian" in p.parts:
            continue
        txt = p.read_text(encoding="utf-8", errors="ignore")
        fm = fm_of(txt)
        if not fm:
            continue
        topics = get_topics(fm)
        meta_type = get_field(fm, "meta_type")
        stance = get_field(fm, "stance")
        for t in topics:
            topic_c[t] += 1
        meta_c[meta_type or "?"] += 1
        if stance:
            stance_c[stance] += 1

        ok = True
        if args.topic and args.topic not in topics:
            ok = False
        if args.meta and meta_type != args.meta:
            ok = False
        if args.stance and stance != args.stance:
            ok = False
        if ok and has_dr:
            d = eff_date(fm, txt)
            if d is None or (lo and d < lo) or (hi and d > hi):
                ok = False
        if ok and has_sm:
            kw = args.source_meeting
            if f"[[Meetings/{kw}" not in txt and kw not in (get_field(fm, "source") or "") \
                    and kw not in (get_field(fm, "source_file") or ""):
                ok = False
        if ok and (args.topic or args.meta or args.stance or has_dr or has_sm):
            d = eff_date(fm, txt) or "-"
            hits.append((p.relative_to(WIKI).as_posix(), d, topics, meta_type, stance))

    if not (args.topic or args.meta or args.stance or has_dr or has_sm):
        print("=== 四轴分布总览 ===")
        print("topic:", dict(topic_c.most_common()))
        print("meta_type:", dict(meta_c.most_common()))
        print("stance(判断页):", dict(stance_c.most_common()))
        print("(第四维用法: --date-range 2026-08-01:2026-09-30 / --source-meeting 关键词)")
        return

    print(f"筛选命中: {len(hits)} 页")
    for rel, d, topics, meta_type, stance in hits[: args.limit]:
        st = f" stance={stance}" if stance else ""
        print(f"  {rel[:56]:58s} date={d} topics={topics} meta={meta_type}{st}")


if __name__ == "__main__":
    main()
