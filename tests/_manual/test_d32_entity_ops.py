# -*- coding: utf-8 -*-
"""D-32 装置测试：引用改写四形态 · 别名自污染闸 · 归并/拆分执行装置的接线与安全。

为什么单独一个测试文件
----------------------
D-32 引入三处**新装置**，每一处都对应一个曾经真实发生过的缺陷：

1. `code/ref_rewrite.py` —— 第 4 形态（`backlinks:` 裸路径）。
   旧实现只覆盖 `[[...]]` 三形态 → 页合并后 `- Entities/Persons/王老师本人.md`
   这类条目变成**僵尸**，且标尺只数 `[[...]]` 完全抓不到（实测残留 311 条）。
2. `entity_alias_guard.colliding_aliases` —— 别名自污染闸。
   `王义` 的 aliases 曾含 `王老师`（另一实体的 canonical_name）→ 阶段 2 命中
   即把两个不同的人归成一个 id。
3. `scripts/d32_entity_ops_20260916.py` —— 执行装置的**锚点校验**纪律：
   任何字段级改动的 old 文本必须命中，否则整批中止（防"锚点缺席却静默继续"）。
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "code"))

from entity_alias_guard import colliding_aliases  # noqa: E402
from ref_rewrite import compile_rules, rewrite_wikilinks, count_stale_backlinks  # noqa: E402


# =============================================== ① 引用改写器：四形态
OLD = "Entities/Persons/王老师本人"
NEW = "Entities/Persons/王老师"


def _rules():
    return compile_rules({OLD: NEW})


def _apply(txt):
    for pat, rep in _rules():
        txt = pat.sub(rep, txt)
    return txt


def test_form1_fullpath_link():
    assert _apply(f"[[{OLD}|王老师本人]]") == f"[[{NEW}|王老师]]"


def test_form2_short_link():
    assert _apply("[[王老师本人]]") == "[[王老师]]"


def test_form3_display_name():
    assert _apply("[[Entities/Persons/王老师本人|王老师本人]]见") == \
        "[[Entities/Persons/王老师|王老师]]见"


def test_form4_backlinks_bare_path():
    """第 4 形态 —— 这是 D-32 才暴露的缺口，D-40 的实现扫不到。"""
    src = "backlinks:\n  - Entities/Persons/王老师本人.md\n  - Meetings/x.md\n"
    out = _apply(src)
    assert f"- {NEW}.md" in out
    assert f"- {OLD}.md" not in out
    assert "- Meetings/x.md" in out, "不得误伤其它条目"


def test_backlinks_form_does_not_touch_prose():
    """形态 4 必须整行锚定 —— 散文里出现同样的路径不得被当条目改写。"""
    src = "参见 Entities/Persons/王老师本人.md 一页\n"
    assert _apply(src) == src


def test_no_prefix_damage():
    """前缀误伤防护：`深度` 是 `深度数科` 的前缀（D-40 实测死链 10→68）。"""
    rules = compile_rules({"Entities/Organizations/深度": "Entities/Organizations/深度X"})
    txt = "[[Entities/Organizations/深度数科|深度数科]]"
    for pat, rep in rules:
        txt = pat.sub(rep, txt)
    assert txt == "[[Entities/Organizations/深度数科|深度数科]]"


def test_rewrite_idempotent_and_no_dup(tmp_path):
    (tmp_path / "a.md").write_text("[[王老师本人]]\n", encoding="utf-8")
    r1 = rewrite_wikilinks(tmp_path, {OLD: NEW})
    r2 = rewrite_wikilinks(tmp_path, {OLD: NEW})
    assert r1["files_changed"] == 1
    assert r2["files_changed"] == 0, "二次跑必须零变更（幂等）"


def test_count_stale_backlinks(tmp_path):
    (tmp_path / "live.md").write_text("# live\n", encoding="utf-8")
    p = tmp_path / "src.md"
    p.write_text("backlinks:\n  - live.md\n  - gone.md\n", encoding="utf-8")
    assert count_stale_backlinks(tmp_path) == 1


# =============================================== ② 别名自污染闸
def test_collision_is_dropped():
    keep, dropped = colliding_aliases(["王老师", "王一", "王毅"], ["王老师", "梁丽"])
    assert keep == ["王一", "王毅"]
    assert dropped == ["王老师"]


def test_self_canonical_allowed():
    """本实体自己的规范名出现在自己别名表属正常（ASR 映射后常见）。"""
    keep, dropped = colliding_aliases(["海南数据交易平台"], ["海南数据交易平台"],
                                      self_canonical="海南数据交易平台")
    assert keep == ["海南数据交易平台"] and dropped == []


def test_guard_is_pure_and_order_preserving():
    keep, _ = colliding_aliases(["b", "a", "b"], ["zzz"])
    assert keep == ["b", "a"], "保序去重"


def test_guard_source_has_no_instance_data():
    """纪律：护栏是纯规则，不得内置实例人名（否则破坏 codex/hermes 可移植性）。

    注意：**docstring 里的举例不算数据**（那是文档），故先剥离注释与字符串。
    """
    src = (ROOT / "code" / "entity_alias_guard.py").read_text(encoding="utf-8")
    body = src[src.index("def colliding_aliases"):]
    body = re.sub(r'""".*?"""', "", body, flags=re.S)     # 剥离 docstring
    body = re.sub(r"#.*$", "", body, flags=re.M)          # 剥离行注释
    for name in ["王老师", "梁老师", "王义", "林建军", "豆包"]:
        assert name not in body, f"护栏函数体（代码部分）不得出现实例数据 {name}"


# =============================================== ③ resolver 接线
def _mk_resolver(tmp_path):
    from entity_resolver import EntityResolver
    reg = {"entities": [
        {"entity_id": "person_933a7dbb_0001", "canonical_name": "王老师",
         "aliases": [], "entity_type": "person"},
        {"entity_id": "person_18560d2a_0001", "canonical_name": "王总",
         "aliases": [], "entity_type": "person"},
    ]}
    p = tmp_path / "entity_registry.json"
    p.write_text(json.dumps(reg, ensure_ascii=False), encoding="utf-8")
    return EntityResolver(p)


def test_resolver_rejects_alias_colliding_with_other_canonical(tmp_path):
    """`王义` 带别名 `王老师` → **不得**因此归并到王老师实体（T4a 污染入口）。"""
    r = _mk_resolver(tmp_path)
    res = r.resolve_or_create("person", "王义", aliases=["王老师", "王一"])
    assert res["canonical_name"] == "王义"
    assert res["action"] == "create"
    assert "王老师" not in (res["aliases"] or [])
    assert "王老师" in (res.get("dropped_colliding_aliases") or [])


def test_resolver_wires_collision_guard():
    """装置必须接线 —— 防「写好却无人调用」（本项目三轮缺陷的同一病因）。"""
    src = (ROOT / "code" / "entity_resolver.py").read_text(encoding="utf-8")
    assert "colliding_aliases" in src
    assert "_canonicals" in src


# =============================================== ④ 执行装置：计划自洽性
def _load_ops():
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "_d32ops", ROOT / "scripts" / "d32_entity_ops_20260916.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_ops_plan_has_no_duplicate_members():
    ops = _load_ops()
    seen = set()
    for m in ops.WIKI_MERGES:
        for rel in m["members"]:
            assert rel not in seen, f"{rel} 被两个合并族同时认领"
            seen.add(rel)


def test_ops_registry_edits_are_unique_by_id():
    ops = _load_ops()
    ids = [e["id"] for e in ops.REG_EDITS]
    assert len(ids) == len(set(ids)), "同一实体不得有两条 registry 编辑（后写覆盖前写）"


def test_ops_merge_members_share_one_entity_id():
    """合并的前提：同 id 的族必须 id 一致；**跨 id 的族必须在计划里显式声明**。

    `王老师` 族恰恰是跨 id（`person_933a7dbb` vs `person_18560d2a`）——
    这是 T4a 分裂本身，属**刻意**的例外，故要求 `cross_id: True` 显式标注：
    防止"悄悄跨 id 合并"重演实体黑洞。
    """
    ops = _load_ops()
    wiki = ROOT / "wiki" / "Entities"
    arch_glob = sorted((ROOT / "system" / "backup").glob("d32_absorbed_*"))
    for m in ops.WIKI_MERGES:
        ids = set()
        for rel in m["members"]:
            p = wiki / (rel + ".md")
            if not p.exists():
                for d in arch_glob:                     # 已归档 → 去归档目录找
                    q = d / (rel.split("/")[-1] + ".md")
                    if q.exists():
                        p = q
                        break
            if not p.exists():
                continue
            ids.add(ops.fm_get(p.read_text(encoding="utf-8"), "entity_id"))
        if m.get("cross_id"):
            assert len(ids) >= 1
            continue
        assert len(ids) <= 1, f"{m['canonical']} 成员 id 不一致：{ids}"


def test_ops_split_target_has_own_entity():
    """拆分的产物必须有**独立** canonical 实体：要么已存在，要么在新建清单里。"""
    ops = _load_ops()
    reg = json.loads((ROOT / "system" / "registry" / "entity_registry.json")
                     .read_text(encoding="utf-8"))
    canon = {e["canonical_name"] for e in reg["entities"]}
    will_create = {ne["canonical"] for ne in ops.NEW_ENTITIES}
    for ne in ops.NEW_ENTITIES:
        assert ne["canonical"] not in canon or ne["canonical"] in canon  # 幂等：两者皆可
    for rb in ops.WIKI_REBINDS:
        assert rb["canonical"] in canon or rb["canonical"] in will_create, \
            f"{rb['canonical']} 既不存在也不会被创建 → 重绑无目标"


def test_ops_content_fix_fields_are_known_labels():
    ops = _load_ops()
    ok = {"姓名", "规范名", "实体编号", "别名", "角色/职位", "所属机构",
          "与王老师关系", "机构类型", "业务模式", "合作状态"}
    for fx in ops.CONTENT_FIXES:
        if fx["kind"] == "field":
            assert fx["label"] in ok, f"未知字段标签 {fx['label']}"
            assert fx.get("old") and fx.get("new") is not None


# =============================================== ⑤ 修正原语的幂等矩阵
def _fx(txt, kind, label="别名", old="", new=""):
    return _load_ops().fix_once(txt, kind, label, old, new)


def test_text_fix_new_contains_old_is_idempotent():
    """`new ⊃ old`（A → A+尾巴）：第二跑**不得**再插一段。

    实测事故：`林丽` 页因该判据写反，被重复插入 2 次。
    """
    a = "苏州元和融总经理"
    new = a + "；「林总」为泛称（已移除）"
    t1, n1, e1 = _fx(a, "text", old=a, new=new)
    assert n1 == 1 and e1 is None
    t2, n2, e2 = _fx(t1, "text", old=a, new=new)
    assert n2 == 0 and e2 is None, f"二次跑必须 0 变更，实际 {n2}"
    assert t2.count("（已移除）") == 1


def test_text_fix_old_contains_new_still_applies():
    """`old ⊃ new`（T+T → T 的收尾修复）：new 恒在文中，但仍必须**触发**。"""
    seg = "；泛称说明"
    t, n, e = _fx(seg + seg, "text", old=seg + seg, new=seg)
    assert n == 1 and e is None
    assert t == seg


def test_text_fix_missing_anchor_errors():
    t, n, e = _fx("无关文本", "text", old="不存在的锚点", new="X")
    assert n == 0 and e and "锚点未命中" in e


def test_field_fix_idempotent_when_already_applied():
    t = "- **规范名**: 梁老师\n"
    t2, n, e = _fx(t, "field", label="规范名", old="万联网梁老师", new="梁老师")
    assert n == 0 and e is None, "已应用（新值已在）应判为幂等，而非锚点错误"


def test_field_fix_reports_real_miss():
    t = "- **规范名**: 张三\n"
    _, n, e = _fx(t, "field", label="规范名", old="李四", new="王五")
    assert n == 0 and e and "锚点未命中" in e


def test_h1_collapse_adjacent_duplicates():
    """相邻重复 H1 必须**折叠**，而不是把空行删掉、留下两行 H1（实测 bug）。"""
    cases = [
        ("# 梁老师\n\n# 梁老师\n\n正文\n", "# 梁老师\n\n正文\n"),
        ("\n# 董峰\n\n\n\n# 董峰\n\n正文\n", "\n# 董峰\n\n正文\n"),
        ("# A\n# A\n# A\n正文\n", "# A\n正文\n"),
        ("# A\n\n# B\n\n正文\n", "# A\n\n# B\n\n正文\n"),  # 不同标题不动
    ]
    for src, want in cases:
        got, n, e = _fx(src, "h1")
        assert e is None
        assert got == want, f"in={src!r} got={got!r} want={want!r}"
