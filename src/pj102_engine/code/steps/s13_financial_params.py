"""
S13: 定量金融参数提取(LLM) - v3.0 新增(v6.1 P-2)

9 类参数:额度 / 授信金额 / 利率 / 费率 / 期限 / 账期 / 保证金比例
        / 营业收入 / 净利润 / 目标市场规模 / 客单价 / 其他关键数字
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from llm_client import LLMClient, safe_json_parse
from excerpt import excerpt_for_llm


# 9 类 enum
FINANCIAL_PARAM_TYPES = [
    "额度", "授信金额",
    "利率", "费率",
    "期限", "账期",
    "保证金比例",
    "营业收入",
    "净利润",
    "目标市场规模",
    "客单价",
    "其他关键数字",
]


def s13_financial_params(content: str, llm: LLMClient) -> list:
    """LLM 提取金融参数,返回 list[dict]"""
    excerpt, EXCERPT_LIMIT = excerpt_for_llm(content, 8000)

    prompt = f"""从会议内容中抓取所有定量金融参数,输出 JSON 数组:

会议内容(前 {EXCERPT_LIMIT} 字):
{excerpt}

【9 类参数类型 - 必须选 1】
1. 额度 / 授信金额
2. 利率 / 费率
3. 期限 / 账期
4. 保证金比例
5. 营业收入
6. 净利润
7. 目标市场规模
8. 客单价
9. 其他关键数字

【每条记录 5 字段】
- type: 9 类枚举任一
- value: 数值字符串(如 "3000万", "4.35%", "6个月")
- quote: 原文 verbatim 引用(15-80 字,grep 可定位)
- speaker: 发言人姓名(必填,无则填 "未确认")
- confidence: high / medium / low

【抓取规则】
1. 必须有具体数字(万/亿/千/%/元)
2. quote 必须 verbatim 复制原文(15-80 字)
3. speaker 必填,识别不到的填 "未确认"
4. 同一参数多人说 → 取更具体的;quote 标注合并
5. 无金融参数 → []

【输出 JSON 数组格式】
[
  {{"type": "额度", "value": "3000万元", "quote": "额度可以给到3000万", "speaker": "刘总", "confidence": "high"}},
  {{"type": "利率", "value": "4.35%", "quote": "利率大概在4.35%左右", "speaker": "本人", "confidence": "high"}}
]

只输出 JSON,不要其他内容。
"""
    result = llm.call(prompt, max_tokens=524288)  # v3.0 S10.2: 按官方上限 524288
    parsed = safe_json_parse(result, {"items": []})

    # safe_json_parse 返回 dict 时(默认),提取 items;返回 list 时直接用
    if isinstance(parsed, dict):
        parsed = parsed.get("items", [])
    if not isinstance(parsed, list):
        return []

    # 校验 + 过滤:quote 空 / speaker 空的丢弃
    valid = []
    for item in parsed:
        if not isinstance(item, dict):
            continue
        if not item.get("type"):
            continue
        if not item.get("value"):
            continue
        if item.get("type") not in FINANCIAL_PARAM_TYPES:
            continue
        if not item.get("quote", "").strip():
            item["confidence"] = "low"   # quote 缺失 → 标低置信
        if not item.get("speaker", "").strip():
            continue   # speaker 完全空 → 丢弃
        # 规范化
        item["quote"] = item["quote"].strip()
        item["speaker"] = item["speaker"].strip()
        item["confidence"] = item.get("confidence", "medium")
        valid.append(item)

    return valid
