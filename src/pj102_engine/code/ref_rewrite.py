# -*- coding: utf-8 -*-
r"""全库引用改写器（引擎级，四形态全覆盖）。

为什么需要单独成模块
--------------------
D-40 的执行脚本在 `scripts/` 里自带一份 `rewrite_refs`，只覆盖 **3 种形态**。
D-32 勘查时发现第 **4 种形态**：`backlinks:` 里的**裸路径**条目

    backlinks:
      - Entities/Persons/王老师本人.md     ← 既不是 [[双链]]，也不带 | 显示名

它不会被任何 wikilink 规则扫到 → 页合并/改名后变成**指向已不存在页面的僵尸条目**
（标尺 `2_dead_links` 也抓不到，因为它只数 `[[...]]`）。
故把改写能力上收到引擎层，四种形态一次覆盖，并让 scripts/ 复用同一实现
（"一处实现"是纪律：两份实现必然分叉）。

四种形态
--------
| # | 形态 | 例 |
|---|---|---|
| 1 | 全路径双链 | `[[Entities/Persons/王老师本人\|…]]` |
| 2 | 短名双链 | `[[王老师本人]]` |
| 3 | 显示名 | `\|王老师本人]]` |
| 4 | backlinks 裸路径 | `- Entities/Persons/王老师本人.md` |

⚠ 铁律：**必须用完整目标边界** `(?=[\]|#])`，禁裸 `replace`。
D-40 实测：`replace("[[旧","[[新")` 因「深度」是「深度数科」的前缀 →
生成 `深度数科数科`，死链 10 → 68。

纪律：纯逻辑、零实例数据 → 可移植 codex / hermes。
"""
from __future__ import annotations

import re
from pathlib import Path


def compile_rules(renames: dict) -> list:
    """`{old_rel_or_stem: new_rel_or_stem}` → 编译后的 (pattern, repl) 列表。

    键可带路径（`Entities/Persons/王老师本人`）或不带（`王老师本人`）；
    值需为**新的相对路径**（不含 `.md`）。
    """
    rules = []
    for old, new in (renames or {}).items():
        old = str(old).strip().rstrip("/")
        new = str(new).strip().rstrip("/")
        if not old or not new or old == new:
            continue
        od, nd = old.split("/")[-1], new.split("/")[-1]
        # ① 全路径双链（带别名/锚点分隔符边界）
        rules.append((re.compile(r"\[\[" + re.escape(old) + r"(?=[\]|#])"), "[[" + new))
        # ② 短名双链
        if od != old:
            rules.append((re.compile(r"\[\[" + re.escape(od) + r"(?=[\]|#])"), "[[" + nd))
        # ③ 显示名
        rules.append((re.compile(r"\|" + re.escape(od) + r"\]\]"), "|" + nd + "]]"))
        # ④ backlinks 裸路径（YAML 列表条目，整行锚定，避免误伤正文散文）
        if "/" in old:
            rules.append((
                re.compile(r"^(\s*-\s*)" + re.escape(old) + r"\.md(\s*)$", re.M),
                r"\g<1>" + new + ".md" + r"\g<2>",
            ))
        else:
            rules.append((
                re.compile(r"^(\s*-\s*)" + re.escape(od) + r"\.md(\s*)$", re.M),
                r"\g<1>" + nd + ".md" + r"\g<2>",
            ))
    return rules


def rewrite_wikilinks(wiki_root: Path, renames: dict, only_ext: str = ".md",
                      dry_run: bool = False) -> dict:
    """在 `wiki_root` 下就地改写引用。返回统计。

    dry_run=True 时**只统计不落盘**（D-42 修：调用方做 dry-run 演练时，
    本函数原先无条件写盘 → 演练即污染，是最危险的一类装置缺陷）。
    """
    rules = compile_rules(renames)
    if not rules:
        return {"files_changed": 0, "hits": 0, "rules": 0, "dry_run": dry_run}
    files_changed = hits = 0
    for p in sorted(Path(wiki_root).rglob("*" + only_ext)):
        if ".obsidian" in p.parts:
            continue
        txt = p.read_text(encoding="utf-8")
        orig = txt
        n = 0
        for pat, rep in rules:
            txt, k = pat.subn(rep, txt)
            n += k
        if txt != orig:
            if not dry_run:
                p.write_text(txt, encoding="utf-8", newline="")
            files_changed += 1
            hits += n
    return {"files_changed": files_changed, "hits": hits,
            "rules": len(rules), "dry_run": dry_run}


def stale_backlinks(wiki_root: Path) -> list:
    """`backlinks:` 裸路径中指向**不存在页面**的条目清单（第 4 形态的独立验收口径）。

    为什么必须是独立维度
    --------------------
    标尺 `2_dead_links` 只数 `[[...]]` 双链，**完全覆盖不到** backlinks 裸路径。
    实测（2026-09-16）：D-38/D-40 历轮合并累积了 **311 条**僵尸条目而无人察觉
    —— 页面早已归档/改名，backlinks 仍指着旧路径。故上收为 lint 维度 13。
    """
    root = Path(wiki_root)
    stems = set()
    for p in root.rglob("*.md"):
        rel = p.relative_to(root).as_posix()
        stems.add(rel[:-3])
        stems.add(p.stem)
    out = []
    for p in sorted(root.rglob("*.md")):
        txt = p.read_text(encoding="utf-8")
        m = re.search(r"^backlinks:\s*$", txt, re.M)
        if not m:
            continue
        for line in txt[m.end():].splitlines():
            mm = re.match(r"^\s+-\s+(\S+)\.md\s*$", line)
            if not mm:
                if line.strip() and not line.startswith(" "):
                    break
                continue
            if mm.group(1) not in stems:
                out.append(f"{p.relative_to(root).as_posix()} → {mm.group(1)}.md")
    return out


def count_stale_backlinks(wiki_root: Path) -> int:
    return len(stale_backlinks(wiki_root))
