"""内容忠实度门单测。核心是**反向测试**：用 2026-09-16 归档的真实退化样本，
证明这道门真的会 FAIL —— 而不是只会印 PASS。"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "code"))

from fidelity_gate import (  # noqa: E402
    entity_names,
    financial_rows,
    gate,
    generic_entities,
    speaker_cell_noise,
    wikilink_count,
)

OLD_MD = """---
entities: ["[[梁超杰]]", "[[王老师]]"]
---
> [!abstract] 一句话总结
> 完整总结

## 五要素
- **背景**：真实内容 [判断:梁超杰、王老师]

## 关键数字

| 类型 | 数值 | 原文引述 | 发言人 | 置信度 |
|---|---|---|---|---|
| 其他关键数字 | 数万 | 你花了几万 | 梁超杰 | medium |
| 营业收入 | 从几千万降至一两百万 | 从原来几千万 | 王老师 | high |

## 涉及实体
- [[梁超杰]]
- [[王老师]]
"""

NEW_MD = """---
entities: ["[[梁超杰]]", "[[王老师]]", "[[几位教授]]"]
---
> [!abstract] 一句话总结
> 总结

## 五要素
- **背景**：真实内容 [判断:发言人梁超杰]

## 关键数字

| 类型 | 数值 | 原文引述 | 发言人 | 置信度 |
|---|---|---|---|---|
| 其他关键数字 | 几万 | 你花了几万 | 发言人梁超杰 | medium |

## 涉及实体
- [[梁超杰]]
- [[王老师]]
- [[几位教授]]
"""


# ---------------- 解析器 ----------------
def test_financial_rows_parse():
    assert len(financial_rows(OLD_MD)) == 2
    assert len(financial_rows(NEW_MD)) == 1


def test_speaker_cell_noise():
    assert speaker_cell_noise(OLD_MD) == []
    assert speaker_cell_noise(NEW_MD) == ["发言人梁超杰"]


def test_wikilink_count_and_entities():
    assert wikilink_count(OLD_MD) > 0
    assert entity_names(OLD_MD) == ["梁超杰", "王老师"]
    assert generic_entities(OLD_MD) == []
    assert generic_entities(NEW_MD) == ["几位教授"]


# ---------------- 门判定 ----------------
def test_gate_fails_on_degradation():
    rep = gate(OLD_MD, NEW_MD)
    assert rep["verdict"] == "FAIL"
    assert "F1_financial_rows" in rep["hard_fails"]
    assert "F2_signature_noise" in rep["hard_fails"]
    assert "F5_generic_entities" in rep["hard_fails"]


def test_gate_pass_on_identical():
    rep = gate(OLD_MD, OLD_MD)
    assert rep["verdict"] == "PASS"
    assert rep["hard_fails"] == []


def test_gate_pass_when_content_grows():
    richer = OLD_MD.replace("| 王老师 | high |",
                            "| 王老师 | high |\n| 期限 | 6个月 | 六个月 | 王老师 | high |")
    rep = gate(OLD_MD, richer)
    assert rep["verdict"] == "PASS"


def test_link_loss_is_hard_fail():
    lossy = OLD_MD.replace("[[王老师]]", "王老师").replace("[判断:梁超杰、王老师]", "[判断:梁超杰]")
    rep = gate(OLD_MD, lossy)
    assert rep["verdict"] == "FAIL"
    assert "F3_wikilinks" in rep["hard_fails"]


def test_byte_shrink_is_warn_not_fail():
    """字节缩水只算 WARN，不得单独把版本判死（曾误伤过合法精简）。"""
    thin = "---\nentities: [\"[[梁超杰]]\", \"[[王老师]]\"]\n---\n" + "## 关键数字\n" + (
        "| 类型 | 数值 | 原文引述 | 发言人 | 置信度 |\n|---|---|---|---|---|\n"
        "| 其他关键数字 | 数万 | 你花了几万 | 梁超杰 | medium |\n"
        "| 营业收入 | 从几千万降至一两百万 | 从原来几千万 | 王老师 | high |\n"
    ) + "## 涉及实体\n- [[梁超杰]]\n- [[王老师]]\n"
    rep = gate(OLD_MD, thin)
    assert rep["warn_fails"] == ["F4_bytes_shrink"]
    assert rep["verdict"] == "WARN"


# ---------------- 反向测试（真实归档样本，已冻结为夹具） ----------------
# 为什么用 tests/fixtures/ 而非 system/backup/s15_candidates_*/:
#   那个目录是**运行时目录**，同一天再跑一次补跑就会被覆盖 —— 曾导致本测试失效。
#   夹具来源：2026-09-16 真实补跑产物（现行 wiki 页 vs s15 重写候选）。
FIXTURE_BASE = ROOT / "tests" / "fixtures" / "summary_20260908_baseline.md"
FIXTURE_DEGRADED = ROOT / "tests" / "fixtures" / "summary_20260908_degraded.md"


@pytest.mark.skipif(not (FIXTURE_BASE.exists() and FIXTURE_DEGRADED.exists()),
                    reason="对拍夹具不在本环境")
def test_reverse_test_real_archived_pair_must_fail():
    """★ 关键回归测试：真实退化样本必须被拦下 —— 证明这道门是活的。

    该样本的退化特征：关键数字表 4 行 → 2 行、实体表混入泛指词「几位教授」，
    而**双链与字节反而"改善"**（18→20、+…）→ 正是既有判准的盲区。
    """
    old_md = FIXTURE_BASE.read_text(encoding="utf-8-sig")
    new_md = FIXTURE_DEGRADED.read_text(encoding="utf-8-sig")
    rep = gate(old_md, new_md, FIXTURE_BASE.name, FIXTURE_DEGRADED.name)
    assert rep["verdict"] == "FAIL", "退化样本未被拦下 → 忠实度门失效"
    assert "F1_financial_rows" in rep["hard_fails"], "未检出关键数字行丢失"
    assert "F5_generic_entities" in rep["hard_fails"], "未检出泛指词入实体表"
    # 同时确认"结构/字节指标"并未回退 —— 即盲区真实存在
    f3 = next(c for c in rep["checks"] if c["key"] == "F3_wikilinks")
    f4 = next(c for c in rep["checks"] if c["key"] == "F4_bytes_shrink")
    assert f3["new"] >= f3["old"], "盲区前提不成立（双链应未回退）"
    assert f4["ok"], "盲区前提不成立（字节缩水应在阈值内）"
