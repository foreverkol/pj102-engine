#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fix_dup_h2_20260915.py — 存量重复同名 H2 一次性收口 (F-4, D-33/P0-2)

背景: 三个生成器曾把被并入页的 H1+全套骨架 H2 原样追加进规范主页 —
  1. code/polish_pages.py (v1.3 merge_mode, 已于 v1.4 修复, 不再复发)
  2. scripts/merge_concepts.py (一次性脚本, ## ➕ 补充出现（date）)
  3. scripts/merge_machine_concepts.py (一次性脚本, 同款 H2 标记)
实例实测 23 页出现重复同名 H2 (王老师 5 组×4-6 份骨架等)。

修复口径 (与 polish_pages v1.4 _merge_appended 同构):
  - 定位页面内全部追加块标记 (### X 补充出现 / ## ➕ 补充出现（X）)
  - 第一个标记前 = 原始区 (原样保留); 标记起至文件尾 = 追加区
  - 每个追加块: 剥离 H1 → 按 H2 切分 → 同名(归一化)小节并入原始区对应小节末尾
  - 无名可回并的残留 → 降级 H3, 挂在该块标记 (统一 H3) 之下
  - frontmatter / callout 一律不动; 幂等: 无标记页零操作

产出: system/state/fix_dup_h2_20260915.json (逐页处理台账)
用法: python scripts/fix_dup_h2_20260915.py [--dry-run] [--wiki PATH]
"""
import re
import sys
import json
import argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "code"))
from polish_pages import _split_h2, _join_h2, _h2_norm  # noqa: E402

W = ROOT / "wiki"

# 追加块标记: polish 的 H3 形态 + merge_concepts/machine 的 H2 形态
MARK_RE = re.compile(
    r"(?m)^(?:###\s+(.+?)\s+补充出现\s*$|##\s+➕\s+补充出现（(.+?)）\s*$)")


def _head_split(ct: str):
    """frontmatter/callout 头 与 正文尾 分离 (与 polish_pages.split_fm 同款口径)"""
    m = re.match(r"^((?:>.*\n|\n)*)---\r?\n.*?\r?\n---\r?\n", ct, re.S)
    return (ct[:m.end()], ct[m.end():]) if m else ("", ct)


def _fix_page(text: str):
    """返回 (new_text, stats) — stats=None 表示无追加块(零操作)"""
    marks = list(MARK_RE.finditer(text))
    if not marks:
        return text, None

    orig_zone = text[:marks[0].start()]
    append_zone = text[marks[0].start():]
    head, tail = _head_split(orig_zone)
    tpre, tsecs = _split_h2(tail)

    # 按标记切块 (块含标记行本身; 下标一律基于全文 text, 勿用 append_zone 切片)
    bounds = [(m.start(), m.end(), (m.group(1) or m.group(2)).strip())
              for m in marks]
    chunks = []
    for i, (s, e, label) in enumerate(bounds):
        nxt = bounds[i + 1][0] if i + 1 < len(bounds) else len(text)
        chunks.append((label, text[e:nxt]))

    stats = {"merged_secs": 0, "leftover_secs": 0, "h1_stripped": 0,
             "mark_lines": len(chunks)}
    leftovers = []   # [(label, [text...])]
    for label, body in chunks:
        if not body.strip():
            continue
        b2, n_h1 = re.subn(r"(?m)^# (?!#)[^\n]*$", "", body.rstrip())
        stats["h1_stripped"] += n_h1
        pre, secs = _split_h2(b2)
        kept = []
        if pre.strip():
            kept.append(pre.strip())
        for title, sbody in secs:
            if not title.strip() or not sbody.strip():
                continue
            tgt = next((i for i, (t, _) in enumerate(tsecs)
                        if _h2_norm(t) == _h2_norm(title)), None)
            if tgt is not None:
                t, tb = tsecs[tgt]
                tsecs[tgt] = (t, tb.rstrip() + "\n\n" + sbody.strip() + "\n")
                stats["merged_secs"] += 1
            else:
                kept.append(f"### {title.lstrip('#').strip()}\n\n{sbody.strip()}")
                stats["leftover_secs"] += 1
        if kept:
            leftovers.append((label, kept))

    # 残留块: 同 label 合并, 标记统一 H3 形态
    by_label = {}
    for label, kept in leftovers:
        by_label.setdefault(f"### {label} 补充出现", []).extend(kept)
    tail_out = _join_h2(tpre, tsecs)
    if by_label:
        block = "\n\n" + "\n\n".join(
            f"{mk}\n\n" + "\n\n".join(kept) for mk, kept in by_label.items()) + "\n"
        return head + tail_out.rstrip() + "\n" + block, stats
    return head + tail_out, stats


def _merge_dup_secs(text: str):
    """兜底第二遍: 无追加标记但存在重复同名 H2 的页面 (如 Scenarios 页
    ## 🔗 关联网络 ×2, 来源非三个追加生成器), 直接合并同名小节
    (归一化匹配, 第 2+ 份内容并入第 1 份末尾, 保序)。"""
    head, tail = _head_split(text)
    pre, secs = _split_h2(tail)
    out, idx, merged = [], {}, 0
    for t, b in secs:
        k = _h2_norm(t)
        if k in idx:
            ot, ob = out[idx[k]]
            out[idx[k]] = (ot, ob.rstrip() + "\n\n" + b.strip() + "\n")
            merged += 1
        else:
            idx[k] = len(out)
            out.append((t, b))
    if not merged:
        return text, None
    return head + _join_h2(pre, out), {"dup_merged": merged}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--wiki", default=str(W))
    args = ap.parse_args()
    wiki = Path(args.wiki)

    manifest, touched = [], 0
    for p in sorted(wiki.rglob("*.md")):
        if p.name in ("index.md", "log.md") or p.name.startswith("log.legacy"):
            continue
        try:
            text = p.read_text(encoding="utf-8")
        except Exception as e:
            print(f"[ERR] {p.name}: {e}")
            continue
        # 守护式范围门: 只处理存在重复同名 H2 的页面,
        # 有"补充出现"标记但无重复小节的页面不动 (避免无谓形式变更)。
        # ⚠ 2026-09-16 (D-42) 修: 范围门必须用 **_h2_norm 归一化** 判同名 ——
        #   原字面比对会漏掉 `## 📅 出现会议 (2)` × `## 📅 出现会议`
        #   这类"计数后缀差异"页 (实测 `梁老师.md`), 与 lint 维度 14 口径不一致。
        m = re.match(r"^((?:>.*\n|\n)*)---\r?\n.*?\r?\n---\r?\n", text, re.S)
        body = text[m.end():] if m else text
        h2s = [_h2_norm(ln.strip()) for ln in body.split("\n")
               if re.match(r"^## (?!#)", ln.strip())]
        if not any(c > 1 for c in __import__("collections").Counter(h2s).values()):
            continue
        new, stats = _fix_page(text)
        if stats is None:
            # 无"补充出现"标记的重复页 (Scenarios 等) → 同名小节直接合并
            new, stats = _merge_dup_secs(text)
            if stats is None or new == text:
                continue
            rel = p.relative_to(wiki).as_posix()
            manifest.append({"page": rel, "mode": "merge_dup", **stats})
            touched += 1
            print(f"[{'DRY' if args.dry_run else 'OK'}] {rel}: "
                  f"合并重复小节 {stats['dup_merged']}")
            if not args.dry_run:
                p.write_text(new, encoding="utf-8", newline="\n")
            continue
        if new == text:
            continue
        touched += 1
        rel = p.relative_to(wiki).as_posix()
        manifest.append({"page": rel, "mode": "remerge", **stats})
        tag = "DRY" if args.dry_run else "OK"
        print(f"[{tag}] {rel}: 回并 {stats['merged_secs']} 小节, "
              f"残留 H3 {stats['leftover_secs']}, 剥 H1 {stats['h1_stripped']}, "
              f"标记 {stats['mark_lines']}")
        if not args.dry_run:
            p.write_text(new, encoding="utf-8", newline="\n")

    print(f"\n触及页面: {touched}")
    if not args.dry_run and touched:
        out = ROOT / "system/state/fix_dup_h2_20260915.json"
        out.write_text(json.dumps(manifest, ensure_ascii=False, indent=2),
                       encoding="utf-8")
        print(f"台账: {out}")


if __name__ == "__main__":
    main()
