# -*- coding: utf-8 -*-
"""引擎侧同步勘察器 —— 通则③「每处热修都问：引擎侧是否同步」的自动化装置

用途
    逐次比对「引擎仓 pj102-engine」与「实例仓 梁超杰合伙项目」，把差异**按成因分型**，
    使「引擎侧同步清单」从"靠人回忆改了哪几个文件"升级为"可复核的机器清单"。

为什么要分型（血泪教训，2026-09-17）
    直接用 `diff -u a.py b.py | wc -l` 量差异会**严重高估**工作量：
      · unified diff 的行数含**上下文行**，不是变更行数；
      · 行尾（CRLF↔LF）不一致会让 diff 把**整个文件**报成一个 hunk。
    实测 `judgments_aggregator.py` 因此被判为「1 个 hunk / 205 行差异」，实情是
    **1 行**（D-73）—— 引擎侧 CRLF、实例侧 LF 所致。据此得出的"~717 行、不可机械
    cherry-pick"结论是**噪声产物**。本装置先归一化再比对，输出真实边界。

行的语法角色（ast + tokenize 判定）——用于区分「预期中性化」与「真差异」
    DOC     模块/类/函数的 docstring 内     → 示例名差异属预期中性化
    COMMENT 注释行                          → 同上
    PROMPT  非 docstring 的字符串字面量内   → 提示词/规则变更，**改变 LLM 行为**，须审阅
    CODE    其余可执行代码                  → 语义变更，须审阅

区块类别
    NEUTRAL_NAME 主理人↔王老师 互换后逐行一致 ⇒ 中性化差异，**不上游**
    PROSE        变更行全 ∈ DOC∪COMMENT       ⇒ 预期差异，**不上游**
    PROMPT       至少一行 ∈ PROMPT            ⇒ 需审阅（提示词）
    LOGIC        其余                          ⇒ 需审阅（代码语义）
    ※ LOGIC/PROMPT 仍需人工二次定性为：
        ① 环境适配（PROJECT_ROOT / .env 路径）—— 引擎与实例**各自保留，禁止互移**
        ② 行尾契约（写入侧 `newline="\\n"`）—— **应上游**
        ③ 功能补丁                              —— **应上游**
        ④ 实例数据/品牌文案                     —— **不上游**

用法
    python scripts/engine_sync_probe_20260917.py                 # 全量分型表
    python scripts/engine_sync_probe_20260917.py --detail        # 追加逐区块明细
    python scripts/engine_sync_probe_20260917.py --file code/llm_client.py
    python scripts/engine_sync_probe_20260917.py --out F:/Temp/probe.txt

退出码：0 = 勘察完成（不代表"无差异"）；2 = 引擎仓路径不存在。
"""
from __future__ import annotations

import argparse
import ast
import difflib
import io
import os
import sys
import tokenize
from pathlib import Path

# 两仓根目录随环境而异，一律由环境变量指定：
#   PJ102_ENGINE_ROOT   引擎仓根（默认 ./pj102-engine）
#   PJ102_INSTANCE_ROOT 部署仓根（默认 .）
ENGINE_ROOT = Path(os.environ.get("PJ102_ENGINE_ROOT") or "pj102-engine")
INSTANCE_ROOT = Path(os.environ.get("PJ102_INSTANCE_ROOT") or ".")
ENGINE_PKG = ENGINE_ROOT / "src" / "pj102_engine"

NAME_MAP = [("主理人", "王老师"), ("王老师", "主理人")]
CATS = ["NEUTRAL_NAME", "PROSE", "PROMPT", "LOGIC", "BLANK"]


# ---------------------------------------------------------------- 读取与行角色
def read_src(p: Path) -> str:
    b = p.read_bytes()
    if b.startswith(b"\xef\xbb\xbf"):      # 去 BOM
        b = b[3:]
    return b.decode("utf-8", errors="replace")


def docstring_lines(src: str) -> set[int]:
    """处于模块/类/函数 docstring 内的行号（1-based）"""
    out: set[int] = set()
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return out
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = getattr(node, "body", None)
            if body and isinstance(body[0], ast.Expr) \
                    and isinstance(body[0].value, ast.Constant) \
                    and isinstance(body[0].value.value, str):
                out.update(range(body[0].value.lineno, body[0].value.end_lineno + 1))
    return out


def line_roles(src: str) -> dict[int, set[str]]:
    roles: dict[int, set[str]] = {}
    dl = docstring_lines(src)
    code_types = {tokenize.NAME, tokenize.NUMBER, tokenize.OP}
    fstr = getattr(tokenize, "FSTRING_START", None)
    if fstr is not None:
        code_types.add(fstr)
    try:
        toks = list(tokenize.generate_tokens(io.StringIO(src).readline))
    except Exception:
        return roles
    for t in toks:
        if t.type == tokenize.COMMENT:
            for ln in range(t.start[0], t.end[0] + 1):
                roles.setdefault(ln, set()).add("COMMENT")
        elif t.type == tokenize.STRING:
            for ln in range(t.start[0], t.end[0] + 1):
                roles.setdefault(ln, set()).add("DOC" if ln in dl else "PROMPT")
        elif t.type in code_types:
            roles.setdefault(t.start[0], set()).add("CODE")
    return roles


def role_of(roles: dict[int, set[str]], ln: int) -> str:
    r = roles.get(ln)
    if not r:
        return "BLANK"
    for k in ("CODE", "PROMPT", "COMMENT", "DOC"):   # CODE 优先
        if k in r:
            return k
    return "DOC"


# ---------------------------------------------------------------- 比对
def classify(rel: str) -> list[tuple] | None:
    """返回 [(kind, tag, e1, e2, j1, j2, eb, ib), ...]；文件缺失返回 None"""
    pe, pi = ENGINE_PKG / rel, INSTANCE_ROOT / rel
    if not pe.exists() or not pi.exists():
        return None
    se, si = read_src(pe), read_src(pi)
    e = [x.rstrip() for x in se.splitlines()]     # 归一化：CRLF→LF 已由 splitlines 处理
    i = [x.rstrip() for x in si.splitlines()]     #            + 去行尾空白
    re_, ri = line_roles(se), line_roles(si)
    out = []
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, e, i, autojunk=False).get_opcodes():
        if tag == "equal":
            continue
        eb, ib = e[i1:i2], i[j1:j2]
        kind = "LOGIC"
        for a, b in NAME_MAP:
            if [x.replace(a, b) for x in eb] == [x.replace(a, b) for x in ib]:
                kind = "NEUTRAL_NAME"
                break
        if kind == "LOGIC":
            rl = {role_of(re_, i1 + 1 + k) for k in range(len(eb))} | \
                 {role_of(ri, j1 + 1 + k) for k in range(len(ib))}
            rl.discard("BLANK")
            if not rl:
                kind = "BLANK"
            elif rl <= {"DOC", "COMMENT"}:
                kind = "PROSE"
            elif "PROMPT" in rl:
                kind = "PROMPT"
        out.append((kind, tag, i1 + 1, i2, j1 + 1, j2, eb, ib))
    return out


def py_files(sub: str) -> list[str]:
    d = ENGINE_PKG / sub
    if not d.exists():
        return []
    return sorted(str(p.relative_to(ENGINE_PKG)).replace("\\", "/")
                  for p in d.rglob("*.py") if "__pycache__" not in str(p))


def main() -> int:
    ap = argparse.ArgumentParser(description="引擎侧同步勘察器（只读）")
    ap.add_argument("--detail", action="store_true", help="追加逐区块明细")
    ap.add_argument("--file", help="只勘察单个相对路径，如 code/llm_client.py")
    ap.add_argument("--out", help="同时写入文件")
    a = ap.parse_args()

    if not ENGINE_PKG.exists():
        print(f"[ERR] 引擎仓不存在: {ENGINE_PKG}", file=sys.stderr)
        return 2

    targets = [a.file] if a.file else (py_files("code") + py_files("scripts"))

    L: list[str] = []
    w = L.append
    w("=" * 104)
    w("引擎侧同步勘察 —— NEUTRAL_NAME/PROSE = 预期差异（不上游）；PROMPT/LOGIC = 需审阅")
    w("归一化：去 BOM / CRLF→LF / 去行尾空白 ｜ 引擎 %s" % ENGINE_ROOT.name)
    w("=" * 104)
    w("")
    w("%-44s %-5s %-7s %-8s %-7s %-6s" % ("文件", "区块", "中性化", "文档注释", "提示词", "代码"))
    w("-" * 104)

    need, rows = [], []
    for rel in targets:
        blocks = classify(rel)
        if blocks is None:
            w("%-44s %s" % (rel, "（一侧缺失，跳过）"))
            continue
        c = {k: 0 for k in CATS}
        for b in blocks:
            c[b[0]] += 1
        rows.append((rel, len(blocks), c))
        if c["LOGIC"] or c["PROMPT"]:
            need.append(rel)
        w("%-44s %-5d %-7d %-8d %-7d %-6d%s"
          % (rel, len(blocks), c["NEUTRAL_NAME"], c["PROSE"], c["PROMPT"], c["LOGIC"],
             " ★" if (c["LOGIC"] or c["PROMPT"]) else ""))

    tot = {k: sum(r[2][k] for r in rows) for k in CATS}
    w("-" * 104)
    w("%-44s %-5d %-7d %-8d %-7d %-6d"
      % ("合计（%d 文件）" % len(rows), sum(r[1] for r in rows),
         tot["NEUTRAL_NAME"], tot["PROSE"], tot["PROMPT"], tot["LOGIC"]))
    w("")
    w("★ 需人工二次定性（环境适配 / 行尾契约 / 功能补丁 / 实例数据）的文件 %d 个：" % len(need))
    w("   " + "、".join(need))

    if a.detail:
        w("")
        w("=" * 104)
        w("逐区块明细（仅 PROMPT / LOGIC）")
        w("=" * 104)
        for rel in need:
            blocks = [b for b in classify(rel) if b[0] in ("LOGIC", "PROMPT")]
            w("")
            w("### %s   （需审阅 %d 区块）" % (rel, len(blocks)))
            for kind, tag, e1, e2, j1, j2, eb, ib in blocks:
                w("  ● %-7s %-8s 引擎 L%d→%d ｜ 实例 L%d→%d" % (kind, tag, e1, e2, j1, j2))
                for x in eb[:10]:
                    w("      - | %s" % x[:160])
                if len(eb) > 10:
                    w("      - | ...(共 %d 行)" % len(eb))
                for x in ib[:12]:
                    w("      + | %s" % x[:160])
                if len(ib) > 12:
                    w("      + | ...(共 %d 行)" % len(ib))

    text = "\n".join(L) + "\n"
    print(text)
    if a.out:
        Path(a.out).write_text(text, encoding="utf-8", newline="\n")
        print("[OK] -> %s" % a.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
