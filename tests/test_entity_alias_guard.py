"""实体 alias 护栏 + EntityResolver 两阶段归并 回归测试。

背景（2026-09-16 实测）：registry 中出现"实体黑洞"——
`person_71add69e_0001`(canonical=万联网梁老师) 的 aliases 吞并了
梁超杰 / 蒋总 / 杨总 / 梁总 / 小总 / 发言人2 / 电话号码，
把至少 5 个不同的人合并进同一 entity_id。

本测试锁定两条不变量：
  I1  弱标识不得作为归并依据
  I2  canonical 精确匹配优先于 alias 命中（消除遍历顺序敏感性）
"""

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "code"))

from entity_alias_guard import (  # noqa: E402
    alias_quality,
    is_junk_entity_name,
    is_weak_alias,
    split_aliases,
)
from entity_resolver import EntityResolver  # noqa: E402


# ---------------- I1: 弱标识判定 ----------------

@pytest.mark.parametrize("alias,reason", [
    ("梁总", "generic_role"),
    ("杨总", "generic_role"),
    ("蒋总", "generic_role"),
    ("王老师", "generic_role"),
    ("黄老板", "generic_role"),
    ("张博士", "generic_role"),
    ("发言人2", "transcript_label"),
    ("发言人梁老师", "transcript_label"),
    ("说话人A", "transcript_label"),
    ("梁超杰@136 0260 1921", "numeric_or_id"),
    ("梁超杰@", "numeric_or_id"),
    ("梁", "single_char"),
    ("王", "single_char"),
    ("梁总(未在文中明示)", "annotated"),
    ("王老师（存疑）", "annotated"),
    ("未提取", "junk"),
    ("孙老师本人", "self_ref"),
    ("王老师本人", "self_ref"),
    ("梁某人", "anonym"),
    ("张某", "anonym"),
    ("", "empty"),
])
def test_weak_alias_detected(alias, reason):
    is_weak, why = is_weak_alias(alias)
    assert is_weak, f"{alias!r} 应判为弱标识"
    assert why == reason, f"{alias!r} 期望 {reason}，实得 {why}"


@pytest.mark.parametrize("alias", [
    "梁超杰", "万联网梁老师", "超杰", "李劲松", "万联网专家顾问梁老师",
    "梁超杰老师",   # 3 字以上人名 + 后缀 → 不是泛化称呼
])
def test_strong_alias_kept(alias):
    is_weak, why = is_weak_alias(alias)
    assert not is_weak, f"{alias!r} 应判为强标识（实得 {why}）"


def test_split_aliases_partitions_without_loss():
    raw = ["梁超杰", "梁总", "发言人2", "超杰", "", "梁"]
    strong, weak = split_aliases(raw)
    assert set(strong) == {"梁超杰", "超杰"}
    assert set(weak) == {"梁总", "发言人2", "梁"}
    # 无信息丢失（空串除外）
    assert len(strong) + len(weak) == 5


def test_alias_quality_shape():
    q = alias_quality(["梁超杰", "梁总", "发言人2"])
    assert q["total"] == 3 and q["strong"] == 1 and q["weak"] == 2
    assert "generic_role" in q["weak_detail"]
    assert "transcript_label" in q["weak_detail"]


# ---------------- I2: 两阶段归并 ----------------

def _mk_registry(tmp_path, entities):
    p = tmp_path / "reg.json"
    p.write_text(json.dumps({"version": "1.0", "schema": "v7.0",
                             "last_updated": "", "entities": entities},
                            ensure_ascii=False), encoding="utf-8")
    return p


def test_canonical_exact_wins_over_alias_hit(tmp_path):
    """★ 复现原 bug：`梁超杰` 既是 A 的 canonical，又在 B 的 aliases 里。

    原实现遍历时先撞上谁就归谁 → 结果不确定。
    新实现必须**恒返回 canonical 精确匹配的那个**。
    """
    ents = [
        # 顺序刻意把"黑洞"放在前面（原实现会误归）
        {"entity_id": "person_B_0001", "canonical_name": "万联网梁老师",
         "aliases": ["梁超杰", "梁老师", "发言人2"], "entity_type": "person"},
        {"entity_id": "person_A_0001", "canonical_name": "梁超杰",
         "aliases": ["超杰"], "entity_type": "person"},
    ]
    r = EntityResolver(_mk_registry(tmp_path, ents))
    got = r._find("梁超杰", [])
    assert got["entity_id"] == "person_A_0001", "canonical 精确匹配必须优先"


def test_weak_only_alias_does_not_merge(tmp_path):
    """★ `蒋总` 的 aliases 全是弱标识（梁总/杨总/发言人2）→ 不得归并到梁老师。"""
    ents = [
        {"entity_id": "person_B_0001", "canonical_name": "万联网梁老师",
         "aliases": ["梁老师", "梁总", "杨总"], "entity_type": "person"},
    ]
    r = EntityResolver(_mk_registry(tmp_path, ents))
    assert r._find("蒋总", ["梁总", "杨总", "发言人2"]) is None


def test_strong_alias_still_merges(tmp_path):
    """强 alias（`超杰`）仍应正常归并 —— 护栏不能矫枉过正。"""
    ents = [
        {"entity_id": "person_A_0001", "canonical_name": "梁超杰",
         "aliases": ["超杰"], "entity_type": "person"},
    ]
    r = EntityResolver(_mk_registry(tmp_path, ents))
    got = r._find("某人", ["超杰"])
    assert got is not None and got["entity_id"] == "person_A_0001"


def test_resolve_creates_independent_entity_for_generic_name(tmp_path):
    """`蒋总` 走完整 resolve → 应**新建独立实体**，而非并入梁老师。"""
    ents = [
        {"entity_id": "person_B_0001", "canonical_name": "万联网梁老师",
         "aliases": ["梁老师", "梁总"], "entity_type": "person"},
    ]
    r = EntityResolver(_mk_registry(tmp_path, ents))
    res = r.resolve_or_create("person", "蒋总", aliases=["梁总", "杨总", "发言人2"])
    assert res["action"] == "create", "不应被归并到既有实体"
    assert res["canonical_name"] == "蒋总"
    # 弱标识不得进入参与归并的 aliases
    assert res["aliases"] == []


def test_update_partitions_weak_aliases(tmp_path):
    """update 时弱标识进 weak_aliases，不进 aliases（否则下次误归并）。"""
    ents = [
        {"entity_id": "person_A_0001", "canonical_name": "梁超杰",
         "aliases": ["超杰"], "entity_type": "person"},
    ]
    r = EntityResolver(_mk_registry(tmp_path, ents))
    r.resolve_or_create("person", "梁超杰", aliases=["梁总", "梁超杰@136", "阿杰"])
    e = r.get_entity("person_A_0001")
    assert "超杰" in e["aliases"] and "阿杰" in e["aliases"]
    assert "梁总" not in e["aliases"]
    assert "梁总" in e.get("weak_aliases", [])
    assert "梁超杰@136" in e.get("weak_aliases", [])


# ---------------- 机器标签拦截（垃圾实体源头阻断） ----------------

@pytest.mark.parametrize("name,reason", [
    ("发言人2", "transcript_label"),
    ("发言人6(深圳科技公司方)", "transcript_label"),
    ("说话人A", "transcript_label"),
    ("未提取", "placeholder"),
    ("未知", "placeholder"),
    ("123", "numeric_only"),
    ("", "empty"),
])
def test_junk_entity_name_detected(name, reason):
    is_junk, why = is_junk_entity_name(name)
    assert is_junk, f"{name!r} 应判为机器标签"
    assert why == reason, f"{name!r} 期望 {reason}，实得 {why}"


@pytest.mark.parametrize("name", ["梁超杰", "万联网梁老师", "蒋总", "梁", "王老师"])
def test_real_name_not_junk(name):
    """★ 单字姓（`梁`）与泛称（`蒋总`）**不得**被当垃圾拦截 ——
    它们可能确有其人，只是源稿未给全名。「弱 alias」≠「垃圾实体」。"""
    is_junk, why = is_junk_entity_name(name)
    assert not is_junk, f"{name!r} 被误判为垃圾（{why}）"


def test_resolve_skips_transcript_label(tmp_path):
    """★ 端到端：`发言人2` 必须返回 skip，且**不写入 registry**。"""
    r = EntityResolver(_mk_registry(tmp_path, []))
    res = r.resolve_or_create("person", "发言人2", aliases=[])
    assert res["action"] == "skip"
    assert res["junk_reason"] == "transcript_label"
    assert r.registry["entities"] == [], "垃圾实体不应写入 registry"
