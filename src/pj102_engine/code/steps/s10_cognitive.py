"""
S10: 认知提炼 + v7.0 ldamc 5 维自检(LLM) - v3.0 升级
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from llm_client import LLMClient, safe_json_parse


def s10_cognitive_refine(content: str, llm: LLMClient) -> dict:
    """LLM 认知提炼 + 数字人素材 + v7.0 ldamc 5 维"""
    excerpt = content[:10000]

    prompt = f"""从以下会议内容提炼认知模式 + 数字人素材 + 【v7.0 创新】ldamc 5 维自检:

会议内容(前 10000 字):
{excerpt}

【v7.0 ldamc 5 维自检 - 必填】
- lost: 本会议漏了什么重要信息/盲点(如 "税局连接是企业数字化的刚性入口")
- different: 与既往认知的差异(与之前观点有何不同)
- added: 新增信息(本会议补充了什么)
- more: 待补充信息(还需要进一步研究什么)
- connected[]: 关联概念/主题数组(如 ["供应链金融变现路径", "企业数字化底座"])

【输出 JSON】
{{
  "cognitive_refinement": ["递进式问题拆解: 降本→促发展→能经营", ...],
  "digital_human_material": {{
    "speaking_style": "理性分析型",
    "frequently_used_words": ["资源整合", "可控", "长期"],
    "thinking_framework": "用数据和逻辑推导"
  }},
  "ldamc": {{
    "lost": "税局连接是企业数字化的刚性入口",
    "different": "SaaS 从工具升级为底座+变现双层模型",
    "added": "供应链金融新增税务数据入口",
    "more": "客户规模/金融变现案例/竞品验证",
    "connected": ["供应链金融变现路径", "企业数字化底座"]
  }}
}}

【规则】
1. ldamc 5 个字段全必填,空字符串也算"诚实空白"
2. connected 是数组,可空数组
3. cognitive_refinement 是数组,3-5 条认知模式
4. digital_human_material 4 字段全必填
5. 只输出 JSON
"""
    result = llm.call(prompt, max_tokens=524288)  # v3.0 S10.2: 按官方上限 524288
    parsed = safe_json_parse(result, {
        "cognitive_refinement": [],
        "digital_human_material": {},
        "ldamc": {
            "lost": "",
            "different": "",
            "added": "",
            "more": "",
            "connected": [],
        },
    })

    # 兜底
    if "cognitive_refinement" not in parsed or not isinstance(parsed["cognitive_refinement"], list):
        parsed["cognitive_refinement"] = []
    if "digital_human_material" not in parsed or not isinstance(parsed["digital_human_material"], dict):
        parsed["digital_human_material"] = {}
    # ldamc 兜底
    if "ldamc" not in parsed or not isinstance(parsed["ldamc"], dict):
        parsed["ldamc"] = {"lost": "", "different": "", "added": "",
                           "more": "", "connected": []}
    else:
        for k in ["lost", "different", "added", "more"]:
            if k not in parsed["ldamc"]:
                parsed["ldamc"][k] = ""
        if "connected" not in parsed["ldamc"] or not isinstance(parsed["ldamc"]["connected"], list):
            parsed["ldamc"]["connected"] = []

    return parsed
