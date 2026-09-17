"""s3 提示词契约护栏（2026-09-16 根因修复的回归锁）。

两个修好的缺陷：
  ① 抓取规则过严: 原「必须有具体数字(万/亿/千/%)」把「需要几百人→十几人」
     「花了一年左右」这类**非货币关键数字**排除在外 → 召回缺失。
  ② 输入截断过小: 原 `content[:6000]`，而 43 个源稿**中位长 25664 字**
     → 长会议中后段信息系统性丢失。

实测证据: 样本 8b563d5e6e9f 现行页有 4 条关键数字, 当前 s3 只提 2 条;
漏掉的 2 条（"几百人"、"一年左右"）在源稿中确实存在, 且都落在 6000 字窗口内
→ 证明是**规则**而非窗口导致, 两处都需修。
"""
import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# 兼容两种布局：实例仓 <root>/code · 引擎仓 <root>/src/pj102_engine/code
if not (ROOT / "code").exists() and (ROOT / "src" / "pj102_engine" / "code").exists():
    ROOT = ROOT / "src" / "pj102_engine"
sys.path.insert(0, str(ROOT / "code"))

_spec = importlib.util.spec_from_file_location(
    "s3_summary_under_test", ROOT / "code" / "steps" / "s3_summary.py")
s3 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(s3)


class FakeLLM:
    """只捕获 prompt，不联网。"""

    def __init__(self):
        self.prompt = None

    def call(self, prompt, **kwargs):
        self.prompt = prompt
        return ('{"one_sentence":"x","background":"b","problem":"p","method":"m",'
                '"outcome":"o","insight":"i","quantitative_params":[]}')


# ---------------- ① 截断窗口 ----------------
def test_excerpt_limit_is_raised():
    """原 6000 只覆盖中位源稿的 23% → 必须显著提高。"""
    assert s3.EXCERPT_LIMIT >= 15000, "截断上限过小，长会议信息会丢失"


def test_long_content_window_and_truncation_notice():
    llm = FakeLLM()
    s3.s3_standard_summary("\u5b57" * 25000, llm)
    # 前 EXCERPT_LIMIT 字进入 prompt
    assert llm.prompt.count("\u5b57") >= s3.EXCERPT_LIMIT - 1000
    # 必须显式告知模型"末尾未提供"，否则会臆测全文
    assert "\u672a\u63d0\u4f9b" in llm.prompt


def test_short_content_no_truncation_notice():
    llm = FakeLLM()
    s3.s3_standard_summary("\u77ed\u6587\u672c", llm)
    assert "\u672a\u63d0\u4f9b" not in llm.prompt, "未截断却提示截断"


# ---------------- ② 非货币数字召回 ----------------
def test_prompt_requires_non_currency_numbers():
    llm = FakeLLM()
    s3.s3_standard_summary("\u5185\u5bb9", llm)
    p = llm.prompt
    assert "\u5176\u4ed6\u5173\u952e\u6570\u5b57" in p
    assert "\u4eba\u6570" in p and "\u65f6\u957f" in p, "未覆盖人数/时长类数字"
    assert "\u4e25\u7981\u56e0\u7f3a\u5c11\u8d27\u5e01\u5355\u4f4d\u800c\u6f0f\u6293" in p, \
        "缺少「不得因缺货币单位而漏抓」的硬规则"


def test_prompt_forbids_transcription_prefix_in_labels():
    """署名硬规则必须仍在（上一轮修复，防被后续编辑覆盖）。"""
    llm = FakeLLM()
    s3.s3_standard_summary("\u5185\u5bb9", llm)
    assert "\u53d1\u8a00\u4eba\u672c\u4eba" in llm.prompt
    assert "[判断:\u5f20\u4e09]" in llm.prompt
