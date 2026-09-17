"""
S6: 5 类实体抽取(LLM) - v3.0 升级(v7.0 canonical_name + aliases + entity_id 占位)
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from llm_client import LLMClient, safe_json_dict
from excerpt import excerpt_for_llm


def s6_entity_extraction(content: str, llm: LLMClient) -> dict:
    """LLM 5 类实体 + v7.0 canonical_name + aliases + quote_orig"""
    excerpt, EXCERPT_LIMIT = excerpt_for_llm(content, 10000)

    prompt = f"""从以下会议内容抽取 5 类实体,输出 JSON(v7.0 增强版):

会议内容(前 {EXCERPT_LIMIT} 字):
{excerpt}

【v3.0 字段规范】
- persons[] 每条:
  * name: 中文姓名(必填)
  * role: 角色/职位
  * org: 所属机构
  * relation_to_wang: 长期合作伙伴/被引荐方/下属/上级/同行/渠道方/未确认
  * aliases[]: 别名数组(如 ["星辰黄总", "黄总"]),v7.0 §8.3 必填(空数组也算)
  * quote_orig: 原文 verbatim(15-80 字),grep 可定位
  * quote_line_range: [起始行, 结束行]
  * disambiguation_note: 若同名歧义,简述差异;否则空字符串

- organizations[] 每条:
  * name: 中文机构名(必填)
  * type: bank/non_bank_fi/fintech/channel/industry_core/saas/platform/other
  * aliases[]: 别名数组
  * business_model: 业务模式简述
  * cooperation_status: target/exploring/active/paused/terminated
  * quote_orig + quote_line_range

- concepts[] 每条: name, definition, quote_orig, quote_line_range
- products[] 每条: name, type, description, quote_orig
- projects[] 每条: name, status, description, quote_orig

【输出格式】
{{
  "persons": [
    {{
      "name": "黄国华",
      "role": "创始人/CEO",
      "org": "星辰科技",
      "relation_to_wang": "引荐合作方",
      "aliases": ["星辰黄总"],
      "quote_orig": "黄总今天讲了税局连接的逻辑",
      "quote_line_range": [42, 50],
      "disambiguation_note": ""
    }}
  ],
  "organizations": [
    {{
      "name": "星辰科技",
      "type": "fintech",
      "aliases": ["星辰"],
      "business_model": "业票财税一体化SaaS",
      "cooperation_status": "target",
      "quote_orig": "...",
      "quote_line_range": [...]
    }}
  ],
  "concepts": [...],
  "products": [...],
  "projects": [...]
}}

【规则】
1. persons/organizations 必填,空也返回 []
2. aliases 必填数组,空填 []
3. quote_orig 是 verbatim 原文(grep 验证)
4. 只输出 JSON
"""
    result = llm.call(prompt, max_tokens=524288)  # v3.0 S10.2: 按官方上限 524288
    parsed = safe_json_dict(result, {
        "persons": [],
        "organizations": [],
        "concepts": [],
        "products": [],
        "projects": [],
    })

    # 兜底:确保 5 个 key 都存在且为 list
    for key in ["persons", "organizations", "concepts", "products", "projects"]:
        if key not in parsed or not isinstance(parsed[key], list):
            parsed[key] = []
        else:
            # 对 person/org 确保 aliases 字段
            for item in parsed[key]:
                if isinstance(item, dict) and "aliases" not in item:
                    item["aliases"] = []

    return parsed
