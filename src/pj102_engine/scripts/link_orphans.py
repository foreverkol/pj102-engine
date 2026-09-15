#!/usr/bin/env python3
"""link_orphans.py — 真孤儿回链 (v2, 2026-09-14 接入批次后处理链; v2.2.4 上游引擎)

孤儿知识页 (concept/judgment/scenario 等, 无任何入链) 从其来源会议页获得回链。
确定性, 零 LLM, 幂等 (已存在链接不重复添加)。

豁免口径:
  - Synthesis 综合页设计为只出链, 不属孤儿修复范围 → 计入 report["exempt_synthesis"]
    (修复 D-b: 旧实现在孤儿判定前抢先 continue, 导致该列表恒为空)
  - Queries / Summaries 同样豁免 → 计入 report["exempt_other_dirs"]

来源字段口径 (修复 D-c):
  同一份 L0 文件名, 三类页面用了不同的 key —
    Meetings/*        → source:
    Knowledge/*(多数) → source_meeting:
    Knowledge/Scenarios → source_ref:   ← lint_wiki 的 scenario schema 就是这么定义的
  旧实现只认 source_meeting, 导致全部 Scenarios 落入 unresolved。
  现改为 _source_of() 依次尝试 source_meeting → source_ref。

用法:
  python -m pj102_engine.scripts.link_orphans [--dry-run]
  (需在项目根目录运行, 或设置 PJ102_PROJECT_ROOT 环境变量)
  亦可 in-process 调用 (run_full.py 后处理链):
  from pj102_engine.scripts.link_orphans import link_orphans
  report = link_orphans(wiki_root, dry_run=False)
"""
import re
import json
import argparse
import os
from pathlib import Path

PROJECT_ROOT = Path(os.environ.get("PJ102_PROJECT_ROOT") or Path.cwd())
WIKI = PROJECT_ROOT / "wiki"
EXEMPT_DIRS = {"Synthesis", "Queries", "Summaries"}
SEC = "## 🔗 相关知识页"

# 来源字段尝试顺序: 见文件头 D-c 说明
SOURCE_KEYS = ("source_meeting", "source_ref")


def split_fm(text):
    m = re.match(r"^---\r?\n(.*?)\r?\n---\r?\n?", text, re.S)
    return (m.group(1), text[m.end():]) if m else ("", text)


def _fm_value(fm, key):
    m = re.search(rf"^{key}:\s*['\"]?([^'\"\n]+?)['\"]?\s*$", fm, re.M)
    return m.group(1).strip() if m else None


def _source_of(fm):
    """D-c: source_meeting 优先, 回退 source_ref (Scenarios 用后者)"""
    for key in SOURCE_KEYS:
        v = _fm_value(fm, key)
        if v:
            return v
    return None


def link_orphans(wiki_root=None, dry_run=False, write_state=True, verbose=True):
    """给孤儿知识页补回链。返回 report dict (幂等, 确定性, 零 LLM)。"""
    wiki = Path(wiki_root) if wiki_root else WIKI
    root = wiki.parent  # wiki 的上级即项目根 (writable state 落点)
    say = print if verbose else (lambda *a, **k: None)

    # 1) 全库入链统计
    inlinks = {}
    all_pages = {}
    for p in wiki.rglob("*.md"):
        if p.name in ("index.md", "log.md") or p.name.startswith("log.legacy"):
            continue
        rel = p.relative_to(wiki).as_posix()[:-3]
        t = p.read_text(encoding="utf-8", errors="ignore")
        all_pages[rel] = (p, t)
        for m in re.finditer(r"\[\[([^\]|#]+)", t):
            tgt = m.group(1).strip().rsplit("/", 1)[-1]   # basename
            if tgt.endswith(".md"):
                tgt = tgt[:-3]                            # 去 .md 后缀
            inlinks.setdefault(tgt, set()).add(rel)

    # 2) 会议页索引: fm source (L0 文件名) -> 会议 rel
    meet_by_src = {}
    for rel, (p, t) in all_pages.items():
        if not rel.startswith("Meetings/"):
            continue
        fm, _ = split_fm(t)
        src = _fm_value(fm, "source")
        if src:
            meet_by_src[src] = rel

    # 3) 孤儿判定 → 按来源会议归组
    orphan_groups = {}   # meeting rel -> [(orphan rel, stem)]
    unresolved, exempt, exempt_other = [], [], 0
    for rel, (p, t) in all_pages.items():
        top = rel.split("/")[0]
        if rel.startswith("Meetings/"):
            continue                     # 会议页仅作回链宿主, 不作被挂对象
        stem = rel.rsplit("/", 1)[-1]
        fm, _ = split_fm(t)

        # D-b: 豁免判定必须在孤儿判定之后登记, 否则报告恒为空
        if top == "Synthesis" or "type: synthesis" in fm:
            if not inlinks.get(stem):
                exempt.append(rel)
            continue
        if top in EXEMPT_DIRS:          # Queries / Summaries 静默豁免
            exempt_other += 1
            continue
        if inlinks.get(stem):
            continue                     # 有入链, 非孤儿

        src = _source_of(fm)
        meet = meet_by_src.get(src) if src else None
        if not meet:
            unresolved.append({"page": rel, "source": src})
            continue
        orphan_groups.setdefault(meet, []).append((rel, stem))

    # 4) 会议页补回链小节 (幂等)
    #    修复 (D-a): 原实现无条件追加 "## 🔗 相关知识页" 标题, 对已有该小节的
    #    页面会造出重复标题。现改为: 小节已存在 → 在该小节末尾就地插入新链接;
    #    不存在 → 才新建小节。
    report = {"meetings_touched": 0, "links_added": 0,
              "unresolved": unresolved, "exempt_synthesis": exempt,
              "exempt_other_dirs": exempt_other}
    for meet, items in sorted(orphan_groups.items()):
        p, t = all_pages[meet]
        new_links = []
        for orel, stem in items:
            short = orel.split("/", 1)[1] if "/" in orel else orel
            if f"[[{orel}" in t or f"[[{stem}" in t or f"[[{short}" in t:
                continue
            new_links.append(f"- [[{orel}|{stem}]]")
        n = len(new_links)
        if not n:
            continue
        if SEC in t:
            lines = t.rstrip().split("\n")
            start = next(i for i, ln in enumerate(lines) if ln.strip() == SEC)
            j = start + 1
            while j < len(lines) and not lines[j].startswith("## "):
                j += 1
            lines[j:j] = new_links
            new_text = "\n".join(lines) + "\n"
        else:
            new_text = (t.rstrip() + "\n\n" + SEC + "\n"
                        + f"> [!info] P2 回链 ({n} 页知识产出首次挂链)\n"
                        + "".join(x + "\n" for x in new_links))
        report["meetings_touched"] += 1
        report["links_added"] += n
        if not dry_run:
            p.write_text(new_text, encoding="utf-8")
        say(f"[{'DRY' if dry_run else 'OK'}] {meet}: +{n} 回链")

    say(f"\n触及会议页: {report['meetings_touched']} | 新增回链: {report['links_added']}")
    say(f"豁免 (synthesis 只出链): {len(exempt)}"
        + (" → " + ", ".join(exempt) if exempt else ""))
    say(f"豁免 (Queries/Summaries): {exempt_other}")
    say(f"无来源可回链 (unresolved): {len(unresolved)}")
    for u in unresolved:
        say(f"    · {u['page']}  (source={u['source']})")

    if not dry_run and write_state:
        (root / "system/state/p2_orphan_backlink.json").parent.mkdir(
            parents=True, exist_ok=True)
        (root / "system/state/p2_orphan_backlink.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    link_orphans(dry_run=args.dry_run)


if __name__ == "__main__":
    main()
