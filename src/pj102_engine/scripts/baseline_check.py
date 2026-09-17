# -*- coding: utf-8 -*-
"""baseline_check: lint 标尺对拍器 (B1, 2026-09-16)

为什么需要它: 旧基线 `system/state/p1_lint_baseline.json` (2026-09-09) 有两个致命缺陷 ——
  ① 它是**绝对路径清单**, 换机器即失效 (分发/三环境场景直接不可用);
  ② 全项目**没有任何代码引用它**, 所谓"零回归断言"实为人工比对 → 基线锚定 475 页,
     而现状 725 页, 断言功能事实上早已失效。

本工具把基线重建为 **"计数 + 相对路径指纹"** 式, 并提供真正可执行的回归判定:
  - 逐维比对当前 lint 输出与基线计数
  - current > baseline → REGRESSED (退出码 1)
  - current < baseline → IMPROVED (提示, 可重锚)
  - 指纹用于确认"数量未变但内容位移"的隐性回归

维度来源: lint_wiki (15 维, 产物层) + lint_cache (4 维, 缓存层) = **19 维**
  13_stale_backlinks 于 D-32 接线 (2026-09-16): 补齐 `2_dead_links` 的盲区 ——
  backlinks 裸路径形态不被任何 wikilink 维度覆盖 (实测累积 311 条僵尸)。
  14_dup_h2 / 15_multi_page_entity 于 D-42 接线 (2026-09-16): 补齐**合并类操作**的盲区 ——
  合并天然产生重复同名 H2, 而既有 13 维无一覆盖 (标尺"零回归"是假阴性);
  同 entity_id 多页则意味页面层与身份层脱钩 (`11_entity_fragments` 只在页名基名相同时才报)。

用法:
  python scripts/baseline_check.py                  # 对拍
  python scripts/baseline_check.py --write-baseline  # 重锚 (仅在确认当前为合格态时)
  python scripts/baseline_check.py --json out.json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "code"))

BASELINE_PATH = ROOT / "system" / "state" / "baseline_v1.0.1.json"
LEGACY_BASELINE = ROOT / "system" / "state" / "p1_lint_baseline.json"
REPORT_PATH = ROOT / "system" / "state" / "baseline_check_latest.json"
KNOWN_ORPHANS = ROOT / "system" / "state" / "known_orphans.json"

EXEMPT_DIM = "1_graph_orphans"  # 豁免台账仅此一维 (Synthesis 孤页)


def collect() -> dict:
    """跑全部 19 维, 返回 {维度: [相对路径/描述, ...]}"""
    from lint_wiki import lint_wiki
    from lint_cache import lint_cache

    rep: dict = {}
    for k, v in lint_wiki(ROOT / "wiki").items():
        rep[k] = [_rel(x) for x in v]
    rep.update(lint_cache(ROOT))
    return rep


def _rel(x: str) -> str:
    """绝对路径 → 项目相对路径 (跨机器可移植)"""
    s = str(x)
    try:
        p = Path(s)
        if p.is_absolute():
            return p.relative_to(ROOT).as_posix()
    except Exception:
        pass
    return s.replace("\\", "/")


def fingerprint(items) -> str:
    payload = "\n".join(sorted(str(i) for i in items))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def load_exempt_count() -> int:
    """从豁免台账读净孤页豁免数 (实例资产, 缺失则 0)"""
    if not KNOWN_ORPHANS.exists():
        return 0
    try:
        d = json.loads(KNOWN_ORPHANS.read_text(encoding="utf-8"))
    except Exception:
        return 0
    if isinstance(d, list):
        return len(d)
    # 实际结构: {"_meta": {...}, "known": [ {...}, ... ]}
    for key in ("known", "known_orphans", "orphans", "entries", "items"):
        v = d.get(key)
        if isinstance(v, list):
            return len(v)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write-baseline", action="store_true")
    ap.add_argument("--json", default="")
    args = ap.parse_args()

    cur = collect()
    counts = {k: len(v) for k, v in cur.items()}
    prints = {k: fingerprint(v) for k, v in cur.items()}
    pages = len([p for p in (ROOT / "wiki").rglob("*.md")
                 if p.name not in ("index.md", "log.md")])
    exempt = load_exempt_count()

    if args.write_baseline:
        bl = {
            "version": "v1.0.1",
            "created": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "supersedes": "p1_lint_baseline.json (2026-09-09, 绝对路径清单式, 无对拍器)",
            "wiki_pages": pages,
            "dimensions": counts,
            "fingerprints": prints,
            "exemptions": {
                EXEMPT_DIM: {
                    "count": exempt,
                    "reason": "Synthesis/ 汇总页无外部入链属结构必然",
                    "ref": "system/state/known_orphans.json",
                    "acceptance": "net_orphans = raw - exempted = 0",
                }
            },
            "total_dimensions": len(counts),
            "dimension_source": "lint_wiki(15) + lint_cache(4)",
            "note": ("锚定 2026-09-16 现状 (引擎 v2.2.4 发布后)。"
                     "其中 C1_cache_completeness / C2_cache_validity / C3_s3_sentinel "
                     "为**已知缓存债**(轨道 A 待清偿) —— 锚定当前值而非理想值, 使"
                     "「补跑是否真见效」可被对拍器直接证明; 清偿后应重锚为 v1.0.2。"),
        }
        BASELINE_PATH.write_text(
            json.dumps(bl, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"✅ 基线已重锚: {BASELINE_PATH}")
        print(f"   wiki 页数 = {pages} · 维度数 = {len(counts)}")
        for k, v in counts.items():
            print(f"   {k:28s} {v}")
        return 0

    if not BASELINE_PATH.exists():
        print(f"❌ 基线不存在: {BASELINE_PATH}（先跑 --write-baseline）")
        return 2

    bl = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
    base = bl.get("dimensions", {})
    bfp = bl.get("fingerprints", {})

    regressed, improved, same, moved = [], [], [], []
    all_dims = sorted(set(counts) | set(base))
    for d in all_dims:
        c, b = counts.get(d, -1), base.get(d, -1)
        if b == -1:
            improved.append((d, b, c, "新增维度"))
        elif c == -1:
            regressed.append((d, b, c, "维度消失"))
        elif c > b:
            regressed.append((d, b, c, "计数增加"))
        elif c < b:
            improved.append((d, b, c, "计数下降"))
        else:
            (moved if prints.get(d) not in (None, bfp.get(d)) else same) \
                .append((d, b, c, "内容位移" if prints.get(d) != bfp.get(d) else ""))

    print(f"基线: {bl.get('version')} ({bl.get('created')}) · wiki {bl.get('wiki_pages')} 页")
    print(f"当前: wiki {pages} 页 · {len(counts)} 维")
    print("-" * 78)
    print(f"{'维度':30s} {'基线':>6s} {'当前':>6s}  判定")
    for d in all_dims:
        b, c = base.get(d, "-"), counts.get(d, "-")
        tag = ""
        if any(r[0] == d for r in regressed):
            tag = "⛔ REGRESSED"
        elif any(r[0] == d for r in improved):
            tag = "✅ IMPROVED"
        elif any(r[0] == d for r in moved):
            tag = "⚠️ 内容位移"
        else:
            tag = "·"
        extra = ""
        if d == EXEMPT_DIM:
            extra = f"  (raw · 豁免 {exempt} → net {counts.get(d, 0) - exempt})"
        print(f"{d:30s} {str(b):>6s} {str(c):>6s}  {tag}{extra}")

    net = counts.get(EXEMPT_DIM, 0) - exempt
    print("-" * 78)
    print(f"净孤页 net_orphans = {net} "
          f"({'✅ 达标' if net == 0 else '⛔ 未达标'})")
    print(f"回归: {len(regressed)} · 改善: {len(improved)} · 持平: {len(same)} "
          f"· 内容位移: {len(moved)}")

    out = {
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "baseline_version": bl.get("version"),
        "wiki_pages": pages,
        "counts": counts,
        "regressed": [{"dim": d, "baseline": b, "current": c, "why": w}
                      for d, b, c, w in regressed],
        "improved": [{"dim": d, "baseline": b, "current": c, "why": w}
                     for d, b, c, w in improved],
        "content_moved": [d for d, _, _, _ in moved],
        "net_orphans": net,
        "verdict": "PASS" if not regressed and net == 0 else "FAIL",
    }
    target = Path(args.json) if args.json else REPORT_PATH
    target.write_text(json.dumps(out, ensure_ascii=False, indent=2),
                      encoding="utf-8")
    print(f"报告: {target}")

    if regressed:
        print("\n⛔ 出现回归:")
        for d, b, c, w in regressed:
            print(f"   {d}: {b} → {c} ({w})")
    return 1 if (regressed or net != 0) else 0


if __name__ == "__main__":
    sys.exit(main())
