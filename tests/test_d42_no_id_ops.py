# -*- coding: utf-8 -*-
"""D-42 装置测试：lint 两维新维度 · dry_run 守卫 · 折叠范围门归一化。

对应本轮三处**新增/修复能力**：
  ① `lint_wiki.14_dup_h2`          —— 同名 H2（归一化判据）
  ② `lint_wiki.15_multi_page_entity` —— 同 entity_id 多页（含豁免台账）
  ③ `ref_rewrite.rewrite_wikilinks(dry_run=True)` —— 演练不落盘
  ④ `fix_dup_h2` 范围门改用归一化比对（原字面比对漏判 `## X (2)`）
"""
from __future__ import annotations

import importlib
import sys
from pathlib import Path

# 路径解析须同时兼容两种布局（本测试要能原样跑在**实例仓**与**引擎仓**）：
#   实例仓: <root>/code,                <root>/scripts
#   引擎仓: <root>/src/pj102_engine/code, <root>/src/pj102_engine/scripts
_ROOT = Path(__file__).resolve().parents[1]
for _cand in (_ROOT / "code", _ROOT / "src" / "pj102_engine" / "code",
              _ROOT / "scripts", _ROOT / "src" / "pj102_engine" / "scripts"):
    if _cand.exists():
        sys.path.insert(0, str(_cand))

import lint_wiki as LW                    # noqa: E402
import ref_rewrite as RR                  # noqa: E402

fix_dup_h2 = importlib.import_module("fix_dup_h2_20260915")


def _mk_page(root: Path, rel: str, fm: dict, body: str) -> Path:
    p = root / "wiki" / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    lines = ["---"]
    for k, v in fm.items():
        lines.append("%s: %s" % (k, v))
    lines.append("---")
    p.write_text("\n".join(lines) + "\n" + body, encoding="utf-8", newline="\n")
    return p


# ------------------------------------------------------- ① 维度 14 dup_h2

def test_dup_h2_detects_literal_duplicate(tmp_path):
    _mk_page(tmp_path, "Entities/Persons/A.md",
             {"entity_id": "person_aaaa_0001", "canonical_name": "A"},
             "# A\n\n## 📅 出现会议\n\n- 1\n\n## 📅 出现会议\n\n- 2\n")
    out = LW.lint_wiki(tmp_path / "wiki")["14_dup_h2"]
    assert len(out) == 1
    assert "出现会议 ×2" in out[0]


def test_dup_h2_normalizes_count_suffix(tmp_path):
    """`## X (2)` 与 `## X` 必须判为同名 —— 这是原装置范围门漏判的形态。"""
    _mk_page(tmp_path, "Entities/Persons/B.md",
             {"entity_id": "person_bbbb_0001", "canonical_name": "B"},
             "# B\n\n## 📅 出现会议 (2)\n\n- 1\n\n## 📅 出现会议\n\n- 2\n")
    out = LW.lint_wiki(tmp_path / "wiki")["14_dup_h2"]
    assert len(out) == 1, out
    assert "出现会议 ×2" in out[0]


def test_dup_h2_supports_times_suffix(tmp_path):
    """`(N 次出现)` 亦须归一化。"""
    _mk_page(tmp_path, "Entities/Persons/C.md",
             {"entity_id": "person_cccc_0001", "canonical_name": "C"},
             "# C\n\n## 🎯 活动 (3 次出现)\n\n- 1\n\n## 🎯 活动\n\n- 2\n")
    out = LW.lint_wiki(tmp_path / "wiki")["14_dup_h2"]
    assert len(out) == 1


def test_dup_h2_clean_page_not_reported(tmp_path):
    _mk_page(tmp_path, "Entities/Persons/D.md",
             {"entity_id": "person_dddd_0001", "canonical_name": "D"},
             "# D\n\n## 📅 出现会议\n\n- 1\n\n## 📑 元信息\n\n- 2\n")
    assert LW.lint_wiki(tmp_path / "wiki")["14_dup_h2"] == []


def test_dup_h2_ignores_frontmatter_occurrence(tmp_path):
    """frontmatter 里的 `## ` 文本不得计入。"""
    _mk_page(tmp_path, "Entities/Persons/E.md",
             {"entity_id": "person_eeee_0001", "canonical_name": "E",
              "note": '"## 📅 出现会议"'},
             "# E\n\n## 📅 出现会议\n\n- 1\n")
    assert LW.lint_wiki(tmp_path / "wiki")["14_dup_h2"] == []


# --------------------------------------------- ② 维度 15 multi_page_entity

def test_multi_page_entity_detects_same_id_two_pages(tmp_path):
    _mk_page(tmp_path, "Entities/Organizations/千问(Qwen).md",
             {"entity_id": "org_x_0001", "canonical_name": "千问(Qwen)"},
             "# 千问\n")
    _mk_page(tmp_path, "Entities/Organizations/阿里千问办公.md",
             {"entity_id": "org_x_0001", "canonical_name": "阿里千问办公"},
             "# 阿里千问办公\n")
    out = LW.lint_wiki(tmp_path / "wiki")["15_multi_page_entity"]
    assert len(out) == 1
    assert "org_x_0001" in out[0] and "2 页" in out[0]


def test_multi_page_entity_distinct_ids_not_reported(tmp_path):
    _mk_page(tmp_path, "Entities/Persons/F.md",
             {"entity_id": "person_f1_0001", "canonical_name": "F"}, "# F\n")
    _mk_page(tmp_path, "Entities/Persons/G.md",
             {"entity_id": "person_g1_0001", "canonical_name": "G"}, "# G\n")
    assert LW.lint_wiki(tmp_path / "wiki")["15_multi_page_entity"] == []


def test_multi_page_entity_empty_id_not_reported(tmp_path):
    """空 id 页不参与（否则所有无 id 页会被算成同一实体）—— P1 已清零，此处防回归。"""
    _mk_page(tmp_path, "Entities/Persons/H.md",
             {"entity_id": "''", "canonical_name": "H"}, "# H\n")
    _mk_page(tmp_path, "Entities/Persons/I.md",
             {"entity_id": "''", "canonical_name": "I"}, "# I\n")
    assert LW.lint_wiki(tmp_path / "wiki")["15_multi_page_entity"] == []


def test_multi_page_entity_exempt_ledger(tmp_path):
    """豁免台账命中 → 不报（供 T2 时间分页等"刻意设计"入册）。"""
    _mk_page(tmp_path, "Entities/Persons/J（2023-09-07）.md",
             {"entity_id": "person_j1_0001", "canonical_name": "J"}, "# J1\n")
    _mk_page(tmp_path, "Entities/Persons/J（2025-05-29）.md",
             {"entity_id": "person_j1_0001", "canonical_name": "J"}, "# J2\n")
    st = tmp_path / "system" / "state"
    st.mkdir(parents=True, exist_ok=True)
    (st / "known_multi_page_entities.json").write_text(
        '["person_j1_0001"]', encoding="utf-8")
    assert LW.lint_wiki(tmp_path / "wiki")["15_multi_page_entity"] == []


def test_multi_page_entity_ledger_missing_is_safe(tmp_path):
    """台账缺失 → 空集，不抛异常（引擎发行版不带实例数据）。"""
    _mk_page(tmp_path, "Entities/Persons/K.md",
             {"entity_id": "person_k1_0001", "canonical_name": "K"}, "# K\n")
    _mk_page(tmp_path, "Entities/Persons/L.md",
             {"entity_id": "person_k1_0001", "canonical_name": "L"}, "# L\n")
    out = LW.lint_wiki(tmp_path / "wiki")["15_multi_page_entity"]
    assert len(out) == 1


# --------------------------------------------- ③ ref_rewrite dry_run 守卫

def test_rewrite_wikilinks_dry_run_does_not_write(tmp_path):
    """★ 装置纪律: dry-run 必须"只统计不落盘"（原实现无条件写盘）。"""
    wiki = tmp_path / "wiki"
    wiki.mkdir(parents=True)
    f = wiki / "a.md"
    original = "见 [[Entities/Persons/旧名|旧名]] 与 [[旧名]]。\n"
    f.write_text(original, encoding="utf-8", newline="\n")

    r = RR.rewrite_wikilinks(wiki, {"Entities/Persons/旧名": "Entities/Persons/新名"},
                             dry_run=True)
    assert r["dry_run"] is True
    assert r["files_changed"] == 1
    # ⚠ hits 是**规则命中次数**，不是引用数：一处 `[[路径/旧名|旧名]]` 会被
    #   形态①(全路径双链) 与形态③(显示名) **各命中一次** → 3 = 2 处引用 + 1 次重叠。
    #   替换本身幂等（形态③ 只会把残留的 `|旧名]]` 补上），结果仍正确。
    assert r["hits"] == 3
    assert f.read_text(encoding="utf-8") == original, "dry-run 不得修改文件"

    r2 = RR.rewrite_wikilinks(wiki, {"Entities/Persons/旧名": "Entities/Persons/新名"})
    assert r2["dry_run"] is False
    txt = f.read_text(encoding="utf-8")
    assert "旧名" not in txt
    assert txt == "见 [[Entities/Persons/新名|新名]] 与 [[新名]]。\n"


def test_compile_rules_path_key_covers_full_path_form(tmp_path):
    """带路径键 → 形态①(全路径双链) 必须生成，否则 `[[dir/旧名|X]]` 会漏改。"""
    rules = RR.compile_rules({"Entities/Persons/旧名": "Entities/Persons/新名"})
    assert len(rules) == 4, "带路径键应生成四种形态规则"
    txt = "[[Entities/Persons/旧名|显示]]"
    for pat, rep in rules:
        txt = pat.sub(rep, txt)
    assert txt == "[[Entities/Persons/新名|显示]]"


def test_compile_rules_bare_key_skips_full_path_form():
    rules = RR.compile_rules({"旧名": "新名"})
    assert len(rules) == 3, "裸键无路径 → 形态①不适用，只生成 ②③④"


# ------------------------------------- ④ fix_dup_h2 范围门 / 折叠归一化

def test_fix_dup_h2_norm_matches_count_suffix():
    assert fix_dup_h2._h2_norm("## 📅 出现会议 (11)") == "## 📅 出现会议"
    assert fix_dup_h2._h2_norm("## 🎯 活动 (3 次出现)") == "## 🎯 活动"
    assert fix_dup_h2._h2_norm("## 📑 元信息") == "## 📑 元信息"


def test_merge_dup_secs_collapses_and_preserves_content():
    """兜底折叠: 第 2+ 份内容并入第 1 份末尾，标题保留首次出现者（含计数后缀）。"""
    txt = ("---\ntype: person\n---\n\n# A\n\n"
           "## 📅 出现会议 (2)\n\n- 甲\n\n"
           "## 📅 出现会议\n\n- 乙\n")
    new, stats = fix_dup_h2._merge_dup_secs(txt)
    assert stats and stats["dup_merged"] == 1
    assert new.count("## 📅 出现会议") == 1
    assert "出现会议 (2)" in new, "应保留带计数后缀的首次标题"
    assert "- 甲" in new and "- 乙" in new, "内容不得丢失"


def test_merge_dup_secs_idempotent():
    txt = "---\n---\n\n# A\n\n## X\n\n- 1\n\n## X\n\n- 2\n"
    new1, _ = fix_dup_h2._merge_dup_secs(txt)
    new2, stats2 = fix_dup_h2._merge_dup_secs(new1)
    assert stats2 is None, "折叠后应无可折叠项（幂等）"
    assert new2 == new1


def test_merge_dup_secs_no_dup_returns_none():
    txt = "---\n---\n\n# A\n\n## X\n\n- 1\n\n## Y\n\n- 2\n"
    new, stats = fix_dup_h2._merge_dup_secs(txt)
    assert stats is None and new == txt
