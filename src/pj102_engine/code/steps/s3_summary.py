"""
S3: 标准摘要(LLM) - v3.0 升级(v6.1 [判断:发言人] + quantitative_params 9 类)
"""
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from llm_client import LLMClient, safe_json_parse


def s3_standard_summary(content: str, llm: LLMClient) -> dict:
    """LLM 输出五要素摘要 + [判断:发言人] + quantitative_params 9 类"""
    excerpt = content[:6000]

    prompt = f"""请输出以下会议的标准摘要,每条内容需加 [判断:发言人] 标注。

会议内容(前 6000 字):
{excerpt}

【v6.1 输出格式(judgment label)】

- **背景**:[事实/判断陈述] [判断:发言人姓名](如无 [判断:发言人] 因事实表述,可不加)
- **问题**:[事实/判断陈述] [判断:发言人姓名]
- **方法**:[方案描述] (一般事实较少判断)
- **结果**:[达成的共识/成果] [判断:关键发言人]
- **启示**:[对未来指导意义] [判断:发言人] (一般属于判断推断)

【判断句判定标准】
- 含「觉得/认为/相信/估计/可能/应该/看来/估计是」→ 判断
- 含具体数字/日期/名称 → 事实
- 行动计划(「要/将/会/计划」)→ 事实/愿景,不标判断
- 「已签约」→ 事实(有具体行为)
- 「资源整合是关键」→ 判断(主观评估)→ 标 [判断:发言人]

【v6.1 字段 quantitative_params - 9 类金融参数】
- type 必填,枚举:
  * 额度 / 授信金额
  * 利率 / 费率
  * 期限 / 账期
  * 保证金比例
  * 营业收入
  * 净利润
  * 目标市场规模
  * 客单价
  * 其他关键数字

- value: 数值字符串(如 "3000万", "4.35%", "6个月")
- quote: 原文 verbatim(15-50 字)
- speaker: 发言人
- confidence: high/medium/low

抓取规则:必须有具体数字(万/亿/千/%);quote 必须 verbatim 复制原文;speaker 必填。
若无金融参数 → quantitative_params: []。

【输出 JSON 格式】
{{
  "one_sentence": "一句话总结(≤30 字)",
  "background": "...",
  "problem": "...",
  "method": "...",
  "outcome": "...",
  "insight": "...",
  "quantitative_params": [
    {{"type": "额度", "value": "3000万", "quote": "...", "speaker": "刘总", "confidence": "high"}}
  ]
}}

只输出 JSON。
"""
    result = llm.call(prompt, max_tokens=524288)  # v3.0 S10: 升 8000
    parsed = safe_json_parse(result, {
        "one_sentence": "未提取",
        "background": "未提取",
        "problem": "未提取",
        "method": "未提取",
        "outcome": "未提取",
        "insight": "未提取",
        "quantitative_params": [],
    })

    # 确保 quantitative_params 是数组
    if "quantitative_params" not in parsed:
        parsed["quantitative_params"] = []
    if not isinstance(parsed["quantitative_params"], list):
        parsed["quantitative_params"] = []

    return parsed
