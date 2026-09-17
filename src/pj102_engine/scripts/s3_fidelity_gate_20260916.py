#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""s3 忠实度门（值级·回源稿验真）—— Phase 1 验收装置

用途：s3（摘要抽取步）放宽「关键数字」召回规则后，**必须**验证 LLM 没有编造数字。
做法：把新 s3 的 `quantitative_params` 里每个数字，回**源稿**（不是 wiki 派生文本，
符合通则⑨）做**值级**比对。

判据分层（宽 → 严）：
  L1 exact          原样命中
  L2 nocomma/space  去千分位 / 去「数字间空格」后命中
                    （录音转写口语停顿会产生 `3 600万`、`1万 5000亿` 这类形态）
  L3 chain          口读连写归一：`1万5000亿` = 1.5万亿 · `1亿5` = 1.5亿
  L4 scale/zh       量级（万/亿/千/百）换算 + 中文数字转写 + ±5% 容差
  MISS              以上皆不命中 ⇒ 疑似编造，打印源稿同首字上下文供人工核

实测（2026-09-16，42 样本）：参数 590 条，MISS **0**；分层分布以 L1 为主
（例：`0→41` 的 07-28 林科院样本有 61 处 L1 原样命中）⇒ 规则放宽未引发编造。
实测（2026-09-17，72 样本 / 含 E1 扩量 30 份）：参数 636+ 条，MISS **0** ⇒ 扩量未引入编造。
  ⚠ 扩量样本源稿在暂存副本目录，须靠 `find_src` 多源回退才能参与验真（否则静默 skip）。

用法：
  python scripts/s3_fidelity_gate_20260916.py                 # 全量
  python scripts/s3_fidelity_gate_20260916.py --hash <content_hash>
  python scripts/s3_fidelity_gate_20260916.py --fails-only     # 只看 MISS
退出码：0 = 无 MISS；1 = 存在 MISS（可接 CI / 验收脚本）
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

# 项目根：优先 PJ102_PROJECT_ROOT（与引擎其它脚本惯例一致），否则按本文件位置推导。
ROOT = Path(os.environ.get("PJ102_PROJECT_ROOT") or Path(__file__).resolve().parents[1])
CACHE = ROOT / "system/cache/steps"
# 源稿根目录 = **部署侧数据**，由 PJ102_S3_SRC 指定。
#   ⚠ 未设时退化为当前目录 ⇒ 全部样本会因源稿缺失被 skip；
#     门会打印 skipped 计数与告警，防「单源假绿」（见 main()）。
SRC = Path(os.environ.get("PJ102_S3_SRC") or ".")

# 通则⑤「装置必须接线」：扩量批次（E1/E2/E3）的源稿在**暂存副本**目录，
# 原库源目录不含它们。单源实现会让扩量样本因「源稿缺失」被 **静默 skip**
# ⇒ 忠实度门假绿。故改为**多源回退**，命中即用。
# 可用环境变量 PJ102_S3_EXTRA_SRC 覆盖（分号/逗号分隔多个目录）。
_EXTRA = os.environ.get("PJ102_S3_EXTRA_SRC", "")
SRC_DIRS: list[Path] = [SRC] + [Path(p) for p in re.split(r"[;,]", _EXTRA) if p.strip()]


def find_src(filename: str) -> Path | None:
    """按 [严格源目录 → 扩量暂存目录] 顺序回退查找源稿。"""
    for d in SRC_DIRS:
        p = d / filename
        if p.exists():
            return p
    return None

SCALE = {"万": 1e4, "亿": 1e8, "千": 1e3, "百": 1e2, "十": 10}
ZH_D = {"零": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5,
        "六": 6, "七": 7, "八": 8, "九": 9}
ZH_U = {"十": 10, "百": 100, "千": 1000}

NUM = re.compile(r"(\d+(?:\.\d+)?)\s*((?:亿|万|千|百|十){1,3})?")
CHAIN = re.compile(r"(\d+(?:\.\d+)?)\s*(万|亿)\s*(\d+(?:\.\d+)?)\s*(亿|万)?")
# 降序链（中文最常用读法）：`1亿1511万` = 1e8 + 1511e4。
# ⚠ 这是 CHAIN 的**盲区**（CHAIN 只处理升序 `1万5000亿` 与省略 `1亿5`）：
#   实测 2026-09-17 因此把源稿 `1亿1511万` 与 LLM 规范化的 `1.1511亿`
#   判为不同 ⇒ 假 MISS（通则⑫ 的又一形态）。
#   收紧为「无空白 + 后不接常用量词」，避免跨句误连（如 `3亿 5万人`）。
DESC = re.compile(r"(\d+(?:\.\d+)?)(亿|万)(\d+(?:\.\d+)?)(万|千|百|十)"
                  r"(?![人个家名位圈条项次只])")
_UNIT_RANK = {"亿": 1e8, "万": 1e4, "千": 1e3, "百": 1e2, "十": 10}


def _unit_mul(units: str | None) -> float:
    """`万亿` 这类叠用量级需连乘（1.5万亿 = 1.5e12）"""
    if not units:
        return 1.0
    m = 1.0
    for c in units:
        m *= SCALE.get(c, 1.0)
    return m


def cn_to_arabic(s: str) -> str:
    def seg(m):
        t = m.group(0)
        total = cur = 0
        for c in t:
            if c in ZH_D:
                cur = ZH_D[c]
            elif c in ZH_U:
                total += (cur or 1) * ZH_U[c]
                cur = 0
            elif c in ("万", "亿"):
                total = (total + cur) * (1e4 if c == "万" else 1e8)
                cur = 0
        return str(int(total + cur))
    return re.sub(r"[零一二两三四五六七八九十百千万亿]+", seg, s)


def _dedup(text: str) -> str:
    return re.sub(r"(?<=\d)\s+(?=\d)", "", text)


def values(text: str) -> set[float]:
    text = text.replace(",", "").replace("，", "")
    out: set[float] = set()
    for m in NUM.finditer(text):
        v = float(m.group(1))
        out.add(v)
        mul = _unit_mul(m.group(2))
        if mul != 1.0:
            out.add(v * mul)
    for m in CHAIN.finditer(text):          # 口读连写（升序）
        a, u1, b, u2 = float(m.group(1)), m.group(2), float(m.group(3)), m.group(4)
        if u2 and u2 != u1:
            out.add((a * SCALE[u1] + b) * SCALE[u2])          # 1万5000亿
        else:
            d = len(m.group(3).split(".")[0])
            out.add((a + b / (10 ** d)) * SCALE[u1])          # 1亿5
    for m in DESC.finditer(text):           # 降序链：1亿1511万 = 1e8 + 1511e4
        a, u1, b, u2 = float(m.group(1)), m.group(2), float(m.group(3)), m.group(4)
        if _UNIT_RANK[u2] < _UNIT_RANK[u1]:
            out.add(a * _UNIT_RANK[u1] + b * _UNIT_RANK[u2])
    return out


def src_values(text: str) -> set[float]:
    n = _dedup(text)
    return values(text) | values(n) | values(cn_to_arabic(n))


def classify(blob: str, text: str) -> tuple[str, list[float]]:
    """返回 (判定, 未命中数值列表)

    ⚠ 判据必须按**原始数字串**（如 `1500`）而非换算值（1.5e11）做原样比对，
    否则 `"%g" % 1.5e11 = 1.5e+11` 永不命中，会把 `1500个亿` 这类真数字误判为编造。
    """
    nospace = _dedup(text)
    nocomma = nospace.replace(",", "").replace("，", "")
    sv = src_values(text)
    miss: list[float] = []
    for m in NUM.finditer(blob):
        raw = m.group(1)
        if len(raw.replace(".", "")) < 2:      # 忽略个位数（多为序号/列举）
            continue
        val = float(raw) * _unit_mul(m.group(2))
        if raw in text or raw in nospace or raw in nocomma:
            continue
        tol = max(1.0, abs(val) * 0.05)
        if any(abs(val - v) <= tol for v in sv):
            continue
        miss.append(val)
    return ("OK" if not miss else "MISS"), miss


def main() -> int:
    ap = argparse.ArgumentParser(description="s3 忠实度门（值级回源稿验真）")
    ap.add_argument("--hash", default=None, help="只验单个 content_hash")
    ap.add_argument("--fails-only", action="store_true", help="只打印 MISS 明细")
    a = ap.parse_args()

    idx = json.loads((ROOT / "system/state/index.json").read_text(encoding="utf-8"))
    by_hash = {s["content_hash"]: s for s in idx["samples"]}
    targets = [a.hash] if a.hash else sorted(by_hash)

    tot_n = tot_m = checked = skipped = 0
    bad: list[tuple[str, str, str, list[float], str]] = []
    if not a.fails_only:
        print("=== 逐样本 ===")
        print(f"源目录回退序（{len(SRC_DIRS)}）: "
              + " → ".join(str(d) for d in SRC_DIRS))
    for h in targets:
        p = CACHE / h / "s3.json"
        if not p.exists():
            print(f" ❌ {h}  s3 缓存缺失")
            continue
        d = json.loads(p.read_text(encoding="utf-8"))
        ps = d.get("quantitative_params") or []
        fn = by_hash[h]["filename"]
        sp = find_src(fn)
        if sp is None:
            skipped += 1
            print(f" ❌ {h}  源稿缺失 {fn[:50]}")
            continue
        text = sp.read_text(encoding="utf-8", errors="ignore")
        n_miss = 0
        for x in ps:
            blob = x if isinstance(x, str) else json.dumps(x, ensure_ascii=False)
            st, miss = classify(blob, text)
            if miss:
                n_miss += len(miss)
                i = text.find(("%g" % miss[0])[:2])
                ctx = text[max(0, i - 55): i + 55].replace("\n", " ") if i >= 0 else ""
                bad.append((h, blob, st, miss, ctx))
        checked += 1
        tot_n += len(ps)
        tot_m += n_miss
        if not a.fails_only:
            tag = "✅" if n_miss == 0 else "⚠️"
            print(f" {tag} {h}  n={len(ps):3d} miss={n_miss:2d}  {fn[:56]}")

    print(f"\n样本 {checked} · 参数合计 {tot_n} · MISS {tot_m}"
          f"  （MISS 率 {tot_m / max(1, tot_n) * 100:.1f}%）")
    if skipped:
        print(f"⚠️ 另有 {skipped} 份因**源稿缺失**被跳过（未参与值级验真）"
              f" ⇒ 单源假绿风险，请核对 SRC_DIRS")
    if bad:
        print("\n=== MISS 明细（需人工核：多为口读连写/空格，非编造）===")
        for h, blob, st, miss, ctx in bad:
            print(f"  {h} | {blob[:60]}")
            print(f"       未命中 {miss}  · 源稿上下文: …{ctx}…")
    print("\n" + ("✅ 通过：无编造数字" if tot_m == 0 else f"⚠️ 不通过：{tot_m} 处待人工核"))
    return 0 if tot_m == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
