"""
S7: 决策与行动项(LLM) - v3.0 升级(v7.0 topic_key + evolution 链 + quote_orig)
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from llm_client import LLMClient, safe_json_parse


def s7_action_decision(content: str, llm: LLMClient) -> dict:
    """LLM 决策 + 行动项 + v7.0 topic_key + evolution + quote_orig"""
    excerpt = content[:8000]

    prompt = f"""从以下会议内容抽取决策 + 行动项,输出 JSON:

会议内容(前 8000 字):
{excerpt}

【v3.0 输出格式(v7.0 增强版)】

- decisions[] 每条:
  * decision: 决策内容(必填)
  * owner: 决策人
  * reason: 决策理由
  * deadline: 截止日期(无则空字符串)
  * 【v7.0】topic_key: "业务域/具体子主题"(必填,如 "bank_cooperation/weizhong" / "loan_to_note/wh可行性" / "partner_coordination/方明")
  * 【v7.0】evolved_from: 字符串,前置判断 ID(v7.0 §七,无填 "")
  * 【v7.0】evolved_to: 数组,后续判断 ID(无填 [])
  * 【W4 stance 立场】决策/判断的立场态度,必填,取值严格四选一:
      support  - 明确支持/推进/确定要做
      caution  - 谨慎/有保留/需再验证
      oppose   - 明确反对/否定/不做
      mixed    - 混合态度(部分支持部分保留)
  * quote_orig: 原文 verbatim(15-80 字)
  * quote_line_range: [起始行, 结束行]

- action_items[] 每条:
  * action: 行动内容(必填)
  * owner: 负责人
  * deadline: 截止日期(无则空字符串)
  * subtype: follow_up/decision/research
  * status: pending/done

【topic_key 命名规则】
- 必须两层(domain/subject),如 "bank_cooperation/weizhong"
- domain 候选: bank_cooperation / partner_coordination / investor_communication / internal_review / industry_exchange / personal_thinking / product_strategy / business_model
- subject 中文转英文 slug(全小写 + 下划线)

【evolution 说明 v7.0】
- evolved_from: 若本判断是某已有判断的演化,填那个判断的 ID(如 "J-20230108-001");否则填 ""
- evolved_to: 若本判断被未来判断演化,填那些 ID;无填 []
- evolution 实现后续由 dispute_detector 补全,本次抽取可默认空

【输出 JSON】
{{
  "decisions": [
    {{
      "decision": "...",
      "owner": "...",
      "reason": "...",
      "deadline": "...",
      "topic_key": "bank_cooperation/weizhong",
      "evolved_from": "",
      "evolved_to": [],
      "stance": "support",
      "quote_orig": "...",
      "quote_line_range": [10, 20]
    }}
  ],
  "action_items": [
    {{
      "action": "...",
      "owner": "...",
      "deadline": "...",
      "subtype": "follow_up",
      "status": "pending"
    }}
  ]
}}

【规则】
1. decisions 必填数组,空填 []
2. topic_key 必填(v7.0 §8.1 必填字段规则)
3. stance 必填,严格四选一: support/caution/oppose/mixed,禁止其他值
4. quote_orig verbatim
5. 只输出 JSON
"""
    result = llm.call(prompt, max_tokens=524288)  # v3.0 S10.2: 按官方上限 524288
    parsed = safe_json_parse(result, {
        "decisions": [],
        "action_items": [],
    })

    for key in ["decisions", "action_items"]:
        if key not in parsed or not isinstance(parsed[key], list):
            parsed[key] = []
        else:
            # 确保 decisions 每条都有 topic_key + evolution
            if key == "decisions":
                for item in parsed[key]:
                    if isinstance(item, dict):
                        if "topic_key" not in item:
                            item["topic_key"] = "general/unknown"
                        if "evolved_from" not in item:
                            item["evolved_from"] = ""
                        if "evolved_to" not in item:
                            item["evolved_to"] = []

    return parsed
