"""内容忠实度门 —— 补齐既有择优判准的盲区：**结构指标改善、内容却退化**。

【背景 · 2026-09-16 实证】
A1 补跑后 s15 重写的摘要页，结构指标全面"改善"：
    双链 18 → 20   [判断:] 3 → 17   字节 5181 → 5381
但内容侧同时劣化：
    关键数字表 **4 行 → 2 行**（丢失 2 条量化信息）
    署名 `梁超杰、王老师` → `发言人梁超杰` / `发言人本人王老师`（带入转写标签噪声）
    实体表混入泛指词（几位教授）
既有择优判准是「双链 > [判断:] > 结构 > 字节」→ 会把新版判为"赢"。
**盲区 = 内容忠实度**：判准只看"有没有更多结构"，不看"原文信息还在不在"。

【5 条判据 · 全部为"新版不得劣于旧版"】
    F1 financial_rows     关键数字表数据行数不减少          [hard]
    F2 signature_noise    [判断:] 与关键数字表发言人列噪声不增加  [hard]
    F3 wikilinks          双链总数不减少                    [hard]
    F4 bytes_shrink       字节不缩水 > 15%                  [warn]
    F5 generic_entities   泛指词/非实体入实体表不增加        [hard]

verdict: FAIL（任一 hard 不过）/ WARN（仅 warn 不过）/ PASS。
FAIL 时**禁止用候选页替换现行页** —— 宁可保留旧版，不可静默丢信息。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from speaker_norm import count_noise  # noqa: E402

# 泛指词 / 非实体：不得作为实体入表
_GENERIC_ENTITY_RE = re.compile(
    r"几位|各位|多人|某人|一些|若干|相关方|团队|未知|待补|不详|用户\(|集体|大家|双方|各方"
)

_BYTE_SHRINK_LIMIT = 0.15


# --------------------------------------------------------------------------
# Markdown 结构解析
# --------------------------------------------------------------------------
def section(md: str, heading: str) -> str:
    """取 ``## <heading>`` 下的正文（到下一个 ``## `` 为止）。"""
    m = re.search(rf"^##\s*{re.escape(heading)}\s*$", md, re.M)
    if not m:
        return ""
    rest = md[m.end():]
    nxt = re.search(r"^##\s+", rest, re.M)
    return rest[: nxt.start()] if nxt else rest


def _table_rows(sec: str) -> list[list[str]]:
    rows: list[list[str]] = []
    for line in sec.splitlines():
        s = line.strip()
        if not s.startswith("|"):
            continue
        if re.fullmatch(r"\|[\s|:\-]+\|", s):          # |---|---| 分隔行
            continue
        cells = [c.strip() for c in s.strip("|").split("|")]
        if not any(cells):
            continue
        rows.append(cells)
    return rows


def financial_rows(md: str) -> list[list[str]]:
    """关键数字表的数据行（去掉表头）。"""
    rows = _table_rows(section(md, "关键数字"))
    if rows and ("类型" in "".join(rows[0]) or "数值" in "".join(rows[0])):
        rows = rows[1:]
    return rows


def speaker_cell_noise(md: str) -> list[str]:
    """关键数字表「发言人」列里的转写标签噪声（如 发言人梁超杰）。"""
    rows = financial_rows(md)
    hits: list[str] = []
    for r in rows:
        for cell in r:
            if re.match(r"^\s*(发言人|说话人|本人|speaker)", cell):
                hits.append(cell)
    return hits


def wikilink_count(md: str) -> int:
    return len(re.findall(r"\[\[[^\]]+\]\]", md))


def entity_names(md: str) -> list[str]:
    """实体名：frontmatter entities + 「涉及实体」清单。"""
    names: list[str] = []
    fm = re.search(r"^---\s*$(.*?)^---\s*$", md, re.M | re.S)
    if fm:
        m = re.search(r"^entities:\s*(\[.*?\])\s*$", fm.group(1), re.M)
        if m:
            try:
                names += [str(x).strip() for x in json.loads(m.group(1).replace("'", '"'))]
            except Exception:
                names += re.findall(r"\[\[([^\]|]+)", m.group(1))
    sec = section(md, "涉及实体")
    names += re.findall(r"-\s*\[\[([^\]|]+)", sec)
    # 统一剥掉 [[ ]] 包装
    out = []
    for n in names:
        n = re.sub(r"^\[\[|\]\]$", "", n.strip())
        n = n.split("|")[0].strip()
        if n:
            out.append(n)
    return list(dict.fromkeys(out))


def generic_entities(md: str) -> list[str]:
    return [n for n in entity_names(md) if _GENERIC_ENTITY_RE.search(n)]


# --------------------------------------------------------------------------
# 门
# --------------------------------------------------------------------------
def gate(old_md: str, new_md: str, old_label: str = "old", new_label: str = "new") -> dict:
    """对拍新旧两版，返回判定报告。"""
    checks: list[dict] = []

    def _add(key: str, level: str, ok: bool, old_v, new_v, detail: str = ""):
        checks.append({
            "key": key, "level": level, "ok": bool(ok),
            "old": old_v, "new": new_v, "detail": detail,
        })

    # F1 关键数字表行数
    o_rows, n_rows = len(financial_rows(old_md)), len(financial_rows(new_md))
    _add("F1_financial_rows", "hard", n_rows >= o_rows, o_rows, n_rows,
         "关键数字表数据行数不得减少")

    # F2 署名噪声（[判断:] + 关键数字表发言人列）
    o_n = count_noise(old_md) + len(speaker_cell_noise(old_md))
    n_n = count_noise(new_md) + len(speaker_cell_noise(new_md))
    _add("F2_signature_noise", "hard", n_n <= o_n, o_n, n_n,
         "转写标签噪声（发言人/本人…）不得增加")

    # F3 双链
    o_l, n_l = wikilink_count(old_md), wikilink_count(new_md)
    _add("F3_wikilinks", "hard", n_l >= o_l, o_l, n_l, "知识图谱连通性不得回退")

    # F4 字节缩水（warn 级）
    o_b, n_b = len(old_md.encode("utf-8")), len(new_md.encode("utf-8"))
    shrink = (o_b - n_b) / o_b if o_b else 0.0
    _add("F4_bytes_shrink", "warn", shrink <= _BYTE_SHRINK_LIMIT, o_b, n_b,
         f"字节缩水不得超过 {_BYTE_SHRINK_LIMIT:.0%}（当前 {shrink:+.1%}）")

    # F5 泛指词入实体表
    o_g, n_g = len(generic_entities(old_md)), len(generic_entities(new_md))
    _add("F5_generic_entities", "hard", n_g <= o_g, o_g, n_g,
         "泛指词/非实体不得入实体表")

    hard_fail = [c for c in checks if c["level"] == "hard" and not c["ok"]]
    warn_fail = [c for c in checks if c["level"] == "warn" and not c["ok"]]
    verdict = "FAIL" if hard_fail else ("WARN" if warn_fail else "PASS")

    return {
        "old": old_label, "new": new_label, "verdict": verdict,
        "checks": checks,
        "hard_fails": [c["key"] for c in hard_fail],
        "warn_fails": [c["key"] for c in warn_fail],
    }


def render(report: dict) -> str:
    lines = [f"忠实度门 {report['verdict']}  [{report['old']}] vs [{report['new']}]"]
    for c in report["checks"]:
        mark = "OK " if c["ok"] else ("FAIL" if c["level"] == "hard" else "WARN")
        lines.append(f"  [{mark}] {c['key']:<22} {c['old']} → {c['new']}   {c['detail']}")
    if report["verdict"] == "FAIL":
        lines.append(f"  ⛔ 命中 {', '.join(report['hard_fails'])} → 禁止以候选页替换现行页")
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="内容忠实度门（pytest 之外的第二道闸）")
    ap.add_argument("--old", required=True, help="现行版（基准）")
    ap.add_argument("--new", required=True, help="候选版")
    ap.add_argument("--json", dest="json_out", default=None, help="报告落盘路径")
    args = ap.parse_args(argv)

    # 以「行尾保真」方式读取: F4 的字节口径必须基于真实字节,
    # 否则 CRLF 被折成 LF 会导致计数失真（Windows 文本模式陷阱）。
    with open(args.old, "r", encoding="utf-8", newline="") as f:
        old_md = f.read()
    with open(args.new, "r", encoding="utf-8", newline="") as f:
        new_md = f.read()
    rep = gate(old_md, new_md, Path(args.old).name, Path(args.new).name)
    print(render(rep))
    if args.json_out:
        Path(args.json_out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json_out).write_text(json.dumps(rep, ensure_ascii=False, indent=1),
                                       encoding="utf-8")
    return 1 if rep["verdict"] == "FAIL" else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
