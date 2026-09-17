"""registry 别名治理：审计"实体黑洞"与弱标识污染（只读优先）。

背景
----
2026-09-16 实测发现 `system/registry/entity_registry.json` 中出现**实体黑洞**：
`person_71add69e_0001`(canonical=万联网梁老师) 的 aliases 吞并了
梁超杰 / 蒋总 / 杨总 / 梁总 / 小总 / 发言人2 / 电话号码 —— 至少 5 个不同的人
被合并进同一 entity_id（信息污染），且 `梁超杰` 另有独立实体（一人两认领）。

本脚本
------
1. **审计**（默认只读）
   - 弱标识污染：泛化称呼 / 源稿口条 / 含数字 / 单字姓 / 带注解
   - **跨实体 alias 冲突** —— 同一 alias 被 ≥2 个实体认领 = 误合并的直接征兆
   - 垃圾 canonical（如 `发言人2` 被直接建成实体页）
   - "吞噬规模"排行（alias 数最多的实体）
2. **修复**（`--apply`，先自动快照 registry）
   - 弱 alias 移入 `weak_aliases`（保留展示，**不再参与任何归并**）
   - 跨实体冲突 alias：从**非 canonical 持有者**移除
   - 垃圾 canonical 实体标记 `status_stage = "obsolete"`（不删除，留证）
   - 输出修复台账 + 前后对比

纪律
----
- **不自动合并/拆分实体**（语义判断需人工裁决）
- apply 前自动快照到 `system/backup/registry_pre_alias_audit_<ts>.json`
- 幂等：二次运行应报 0 变更
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "code"))

from entity_alias_guard import is_weak_alias, split_aliases  # noqa: E402

# 垃圾 canonical：直接由源稿口条/占位符生成的实体页
JUNK_CANONICAL_HINT = ("发言人", "说话人", "说话者", "演讲人", "未提取", "未知", "不详")


def load_registry(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def audit(reg: dict) -> dict:
    ents = reg.get("entities", [])
    weak_by_entity, detail = {}, Counter()
    conflict = {}
    junk_canonical = []
    alias_owners = {}

    for e in ents:
        eid = e.get("entity_id", "?")
        cn = e.get("canonical_name", "")
        als = e.get("aliases") or []
        strong, weak = split_aliases(als)
        if weak:
            weak_by_entity[eid] = {"canonical": cn, "weak": weak}
            for w in weak:
                detail[is_weak_alias(w)[1]] += 1
        for a in strong:
            alias_owners.setdefault(a, []).append({"entity_id": eid, "canonical": cn})
        if any(h in str(cn) for h in JUNK_CANONICAL_HINT):
            junk_canonical.append({"entity_id": eid, "canonical_name": cn,
                                   "aliases": als,
                                   "obsolete": e.get("status_stage") == "obsolete"})

    # (a) 同一 alias 被 ≥2 个实体认领
    for a, owners in alias_owners.items():
        if len(owners) > 1:
            conflict[a] = list(owners)

    # (b) ★ 更隐蔽的一类：某实体的 alias **恰好是另一个实体的 canonical**（冒充）
    #     例：person_71add69e(万联网梁老师).aliases 含 `梁超杰`，
    #         而 `梁超杰` 是 person_3bdbca59 的 canonical → 必须让出。
    #     漏检会导致"同一人被两处认领"永久残留。
    canon_owner = {e.get("canonical_name"): e.get("entity_id")
                   for e in ents if e.get("canonical_name")}
    for a, owners in alias_owners.items():
        real = canon_owner.get(a)
        outsiders = [o for o in owners if o["entity_id"] != real] if real else []
        # 无外部持有者 → 不是冲突（实体把自己的名字列进 aliases 属正常）
        if not real and len(owners) <= 1:
            continue
        if not outsiders:
            continue
        bucket = conflict.setdefault(a, [])
        if real and not any(x["entity_id"] == real for x in bucket):
            bucket.append({"entity_id": real, "canonical": a, "role": "canonical"})
        for o in outsiders:
            if not any(x["entity_id"] == o["entity_id"] for x in bucket):
                bucket.append(o)

    junk_active = [j for j in junk_canonical if not j["obsolete"]]

    # 吞噬规模排行
    swallow = sorted(
        ({"entity_id": e.get("entity_id"), "canonical": e.get("canonical_name"),
          "alias_count": len(e.get("aliases") or []),
          "aliases": e.get("aliases") or []} for e in ents),
        key=lambda x: -x["alias_count"],
    )[:10]

    return {
        "entity_total": len(ents),
        "entities_with_weak_aliases": len(weak_by_entity),
        "weak_alias_total": sum(detail.values()),
        "weak_detail": dict(detail),
        "weak_by_entity": weak_by_entity,
        "cross_entity_conflicts": conflict,
        "junk_canonical": junk_canonical,
        "junk_canonical_active": junk_active,
        "top_swallow": swallow,
    }


def repair(reg: dict, rep: dict) -> tuple[dict, list]:
    """执行实际修复。返回 (stat, actions)。"""
    ents = reg.get("entities", [])
    actions = []
    stat = Counter()

    conflict_keys = set(rep["cross_entity_conflicts"].keys())

    for e in ents:
        eid = e.get("entity_id", "?")
        cn = e.get("canonical_name", "")
        als = list(e.get("aliases") or [])
        strong, weak = split_aliases(als)

        kept, dropped = [], []
        for a in strong:
            owners = rep["cross_entity_conflicts"].get(a)
            if a in conflict_keys:
                # 冲突 alias：仅由 canonical 精确匹配者保留，其余让出
                if cn == a:
                    kept.append(a)
                else:
                    dropped.append(a)
                    stat["conflict_yielded"] += 1
            else:
                kept.append(a)

        old_weak = e.get("weak_aliases") or []
        merged_weak = list(dict.fromkeys(old_weak + weak + dropped))
        changed = (kept != als) or (merged_weak != old_weak)
        e["aliases"] = kept
        if merged_weak:
            e["weak_aliases"] = merged_weak
        if changed:
            stat["weak_moved"] += len(weak) + len(dropped)
            actions.append({"entity_id": eid, "canonical": cn,
                            "moved_to_weak": weak,
                            "yielded_conflict_aliases": dropped})

        # 垃圾 canonical → 标记 obsolete
        if any(h in str(cn) for h in JUNK_CANONICAL_HINT):
            if e.get("status_stage") != "obsolete":
                e["status_stage"] = "obsolete"
                e["_obsolete_reason"] = ("canonical_name 为源稿口条/占位符，"
                                         "非真实实体 (2026-09-16 registry 治理)")
                stat["marked_obsolete"] += 1
                actions.append({"entity_id": eid, "canonical": cn,
                                "action": "marked_obsolete"})

    return stat, actions


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="registry 别名治理（实体黑洞审计）")
    ap.add_argument("--registry", default=None)
    ap.add_argument("--apply", action="store_true", help="执行修复（默认只读）")
    ap.add_argument("--out", default="docs/PJ102_REGISTRY_ALIAS_AUDIT_20260916.md")
    ap.add_argument("--json", default="system/state/registry_alias_audit_20260916.json")
    args = ap.parse_args(argv)

    reg_path = Path(args.registry) if args.registry else ROOT / "system" / "registry" / "entity_registry.json"
    reg = load_registry(reg_path)
    rep = audit(reg)

    print(f"实体总数: {rep['entity_total']}")
    print(f"含弱标识的实体: {rep['entities_with_weak_aliases']}  |  弱标识条目: {rep['weak_alias_total']}")
    print(f"弱标识明细: {rep['weak_detail']}")
    print(f"★ 跨实体 alias 冲突: {len(rep['cross_entity_conflicts'])} 例")
    for a, owners in list(rep["cross_entity_conflicts"].items())[:12]:
        print(f"    {a!r} ← {[o['entity_id'] + '(' + str(o['canonical']) + ')' for o in owners]}")
    print(f"★ 垃圾 canonical 实体: {len(rep['junk_canonical'])} 个"
          f"（其中未标记 obsolete 的 {len(rep['junk_canonical_active'])} 个）")
    for j in rep["junk_canonical_active"][:8]:
        print(f"    {j['entity_id']}  canonical={j['canonical_name']!r}  obsolete={j['obsolete']}")
    print("★ 吞噬规模 Top5:")
    for s in rep["top_swallow"][:5]:
        print(f"    {s['entity_id']} ({s['canonical']}) alias={s['alias_count']}")

    stat, actions = Counter(), []
    if args.apply:
        ts = time.strftime("%Y%m%d_%H%M%S")
        snap = ROOT / "system" / "backup" / f"registry_pre_alias_audit_{ts}.json"
        snap.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(reg_path, snap)
        print(f"\n[快照] {snap}")

        stat, actions = repair(reg, rep)
        reg["last_updated"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        reg_path.write_text(json.dumps(reg, ensure_ascii=False, indent=2),
                            encoding="utf-8", newline="\n")
        print(f"[修复] {dict(stat)}")

        # 修后复验
        rep2 = audit(load_registry(reg_path))
        print(f"[复验] 含弱标识实体: {rep2['entities_with_weak_aliases']}"
              f"  |  跨实体冲突: {len(rep2['cross_entity_conflicts'])}"
              f"  |  未标记垃圾 canonical: {len(rep2['junk_canonical_active'])}")

    # 报告
    L = ["# registry 别名治理审计（实体黑洞）", "",
         f"- 生成时间: {time.strftime('%Y-%m-%d %H:%M:%S')}",
         f"- registry: `{reg_path.relative_to(ROOT)}`",
         f"- 模式: **{'已执行修复' if args.apply else '只读审计'}**", "",
         "## 一、总量", "",
         f"| 指标 | 值 |", "|---|---|",
         f"| 实体总数 | {rep['entity_total']} |",
         f"| 含弱标识的实体 | {rep['entities_with_weak_aliases']} |",
         f"| 弱标识条目 | {rep['weak_alias_total']} |",
         f"| **跨实体 alias 冲突** | **{len(rep['cross_entity_conflicts'])}** |",
         f"| 垃圾 canonical 实体 | {len(rep['junk_canonical'])} |", "",
         "## 二、弱标识分布（按类型）", ""]
    for k, v in sorted(rep["weak_detail"].items(), key=lambda kv: -kv[1]):
        L.append(f"- `{k}`: {v}")
    L += ["", "## 三、🔴 跨实体 alias 冲突（误合并征兆）", ""]
    if rep["cross_entity_conflicts"]:
        for a, owners in rep["cross_entity_conflicts"].items():
            L.append(f"- **`{a}`** 被 {len(owners)} 个实体认领:")
            for o in owners:
                L.append(f"    - `{o['entity_id']}` ({o['canonical']})")
    else:
        L.append("- （无）")
    L += ["", "## 四、垃圾 canonical 实体（源稿口条被建成实体页）", "",
          f"共 {len(rep['junk_canonical'])} 个，其中**未标记** {len(rep['junk_canonical_active'])} 个。", ""]
    if rep["junk_canonical"]:
        for j in rep["junk_canonical"]:
            L.append(f"- `{j['entity_id']}` canonical=`{j['canonical_name']}`"
                     f" aliases={j['aliases']} obsolete={j['obsolete']}")
    else:
        L.append("- （无）")
    L += ["", "## 五、吞噬规模 Top10", "",
          "| entity_id | canonical | alias 数 |", "|---|---|---|"]
    for s in rep["top_swallow"]:
        L.append(f"| `{s['entity_id']}` | {s['canonical']} | {s['alias_count']} |")
    if args.apply:
        L += ["", "## 六、修复动作", "",
              f"- 弱标识移入 `weak_aliases`: {stat.get('weak_moved', 0)}",
              f"- 冲突 alias 让出: {stat.get('conflict_yielded', 0)}",
              f"- 标记 obsolete: {stat.get('marked_obsolete', 0)}", ""]
        for a in actions:
            L.append(f"- `{a['entity_id']}` ({a.get('canonical')}): "
                     f"{json.dumps({k: v for k, v in a.items() if k not in ('entity_id', 'canonical')}, ensure_ascii=False)}")
    L += ["", "---", "",
          "## 处置原则", "",
          "1. **弱标识只降级不外弃** —— 移入 `weak_aliases` 保留信息，但不再参与归并",
          "2. **不自动合并/拆分** —— 语义判断需人工裁决（本脚本只做机械净化）",
          "3. **垃圾实体只标记不删除** —— `status_stage=obsolete` 留证，便于回溯",
          "4. **引擎侧已同步加固** —— `entity_alias_guard.py` + 两阶段 `_find()`", ""]

    outp = ROOT / args.out
    outp.parent.mkdir(parents=True, exist_ok=True)
    outp.write_text("\n".join(L), encoding="utf-8", newline="\n")
    jsonp = ROOT / args.json
    jsonp.parent.mkdir(parents=True, exist_ok=True)
    jsonp.write_text(json.dumps(rep, ensure_ascii=False, indent=1),
                     encoding="utf-8", newline="\n")
    print(f"\n报告: {outp}")
    print(f"JSON: {jsonp}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
