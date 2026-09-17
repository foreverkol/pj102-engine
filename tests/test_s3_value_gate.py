# -*- coding: utf-8 -*-
"""s3 值级忠实度门（``scripts/s3_fidelity_gate_20260916.py``）归一化单测。

**为什么单独一个文件**：本仓有两道同名「忠实度门」，职责不同，勿混：

* ``code/fidelity_gate.py``      —— **页面级**（新旧页面对拍：关键数字行数、
  双链数、泛指实体），夹具驱动，见 ``tests/test_fidelity_gate.py``。
* ``scripts/s3_fidelity_gate_*.py`` —— **值级·回源稿**（把 s3 抽出的每个数字
  回**原始转写稿**做值级比对，符合通则⑨「不采信 wiki 派生文本」）。

本文件只测后者。核心是**双向**验证：
  1. 正控 —— 录音口语形态必须被容忍（通则⑫）；
  2. **负控** —— 真编造必须仍被抓住（防止"宽容"演化成"放水"）。

⚠ 历史教训（2026-09-17）：门只展开了**升序**口读链（``1万5000亿`` / ``1亿5``），
漏掉中文**最常用**的**降序**链 ``1亿1511万`` ⇒ 源稿写 `1亿1511万`、LLM 规范化成
`1.1511亿` 时被判 **假 MISS**。修复后必须证明灵敏度未下降 —— 即本文件的负控用例。
"""
import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
# 兼容两种布局：实例仓 <root>/code · 引擎仓 <root>/src/pj102_engine/code
if not (ROOT / "code").exists() and (ROOT / "src" / "pj102_engine" / "code").exists():
    ROOT = ROOT / "src" / "pj102_engine"
_GATE = ROOT / "scripts" / "s3_fidelity_gate_20260916.py"


def _load():
    spec = importlib.util.spec_from_file_location("s3_value_gate", _GATE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


pytestmark = pytest.mark.skipif(not _GATE.exists(), reason="值级门脚本不在本环境")
gate = _load()

# 取自 E1 样本 03fd3ed81b6a（20230529 内部例会）的真实源稿片段
SRC = ("刚刚周丽也说了，截止今天为止，我们其实是已经完成了1亿1511万。"
       "名单外的是三家，一家是60，一家是5万的，然后有51万的。")


# ---------------- 正控：口语形态必须被容忍 ----------------
def test_descending_chain_is_expanded():
    """降序链 `1亿1511万` ⇒ 115,110,000（本次修复的核心）。"""
    assert 115_110_000.0 in gate.values("完成了1亿1511万")


def test_descending_chain_reverse_written_as_decimal_yi():
    """源稿 `1亿1511万` vs 摘要 `1.1511亿` ⇒ 同值，不得判 MISS。"""
    st, miss = gate.classify('{"type":"授信金额","value":"1.1511亿"}', SRC)
    assert st == "OK", f"降序链反写被误判为编造: {miss}"


def test_ascending_chain_still_works():
    """回归保护：升序链能力不得被本次修改破坏。"""
    # 1万5000亿 / 1亿5 —— 前者见原实现注释，后者为省略读法
    assert len(gate.values("1万5000亿")) >= 1
    assert 150_000_000.0 in gate.values("1亿5")


def test_unit_swap_same_value():
    """`11511万` == `1.1511亿`（换单位不改值）⇒ 应命中。"""
    st, _ = gate.classify('{"type":"金额","value":"11511万"}', SRC)
    assert st == "OK"


# ---------------- 负控：真编造必须被抓 ----------------
def test_fabricated_number_still_detected():
    """★ 关键负控：灵敏度不得因放宽而归零。"""
    st, miss = gate.classify('{"type":"授信金额","value":"9.99亿"}', SRC)
    assert st == "MISS", "编造数字未被抓住 → 值级门已放水"
    assert 999_000_000.0 in miss


def test_magnitude_confusion_detected():
    """量级错乱（把 1亿1511万 写成 11.511亿）必须判 MISS。"""
    st, _ = gate.classify('{"type":"授信金额","value":"11.511亿"}', SRC)
    assert st == "MISS"


# ---------------- 误连防护 ----------------
def test_desc_chain_does_not_cross_words():
    """`3亿 5万人` 含空白/量词 ⇒ 不得被误合成 3亿0500万（避免放水）。"""
    assert 300_050_000.0 not in gate.values("公司有3亿 5万人")


def test_desc_chain_ignores_counter_words():
    """`1亿1511万个` 后接量词 ⇒ 不合成（负向前瞻）。"""
    assert 115_110_000.0 not in gate.values("大约1亿1511万个")
