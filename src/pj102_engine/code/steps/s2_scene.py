"""
S2: 场景识别(LLM) - v3.0 升级(v6.1 meeting_type 6 类 + subtype + v7.0 external_ref)
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from llm_client import LLMClient, safe_json_parse
from excerpt import excerpt_for_llm


def s2_scene_recognition(content: str, llm: LLMClient) -> dict:
    """LLM 识别会议场景(含 v6.1 meeting_type 6 类 + subtype + v7.0 external_ref 标识)"""
    excerpt, EXCERPT_LIMIT = excerpt_for_llm(content, 4000)

    prompt = f"""请分析以下会议转写,输出 JSON 格式的会议场景信息:

会议内容(前 {EXCERPT_LIMIT} 字):
{excerpt}

【v3.0 字段定义】
- scene_type: 6 类枚举
  * client_visit     - 客户拜访/需求交流(首次拜访、需求挖掘、方案讨论)
  * bank_communication - 银行交流(银行拜访、授信谈判、风控沟通)
  * investor_沟通   - 投资沟通(VC/PE 路演、投资人尽调、条款谈判)
  * partner_coordination - 合作方协调(渠道方对接、资源方洽谈)
  * internal_review  - 内部复盘(团队会议、项目复盘、战略讨论)
  * industry_exchange - 行业交流(论坛参会、行业协会、同业交流)
  * personal_thinking - 个人思考(录音自言自语、分析判断)

- meeting_subtype: 6 类枚举(可选)
  * first_meet       - 首次接触
  * follow_up        - 后续跟进
  * negotiation      - 商务谈判
  * contract_sign    - 签约
  * project_kickoff  - 项目启动
  * regular_review   - 定期回顾
  * n/a              - 不适用

- perspective: speaker/expert/sales_market/ceo/partner
- scene_reason: 简要说明为什么是这种场景
- confidence: high/medium/low
- is_external_knowledge: bool,是否外部参考(如新闻/论文/白皮书)
  (true → external_ref_target 必填;false → null)
- external_ref_target: 当 is_external_knowledge=true 时填入
  reference 的目标路径,如 "Knowledge/External/微众银行白皮书.md";否则 null

【输出 JSON 格式】
{{
  "scene_type": "client_visit",
  "meeting_subtype": "first_meet",
  "perspective": "sales_market",
  "scene_reason": "...",
  "confidence": "high",
  "is_external_knowledge": false,
  "external_ref_target": null
}}

【规则】
1. scene_type 必填,6 类枚举
2. meeting_subtype 必填,无合适填 n/a
3. 涉及外部资料(论文/白皮书/新闻)→ is_external_knowledge=true
4. 只输出 JSON,不要其他内容
"""
    result = llm.call(prompt, max_tokens=524288)  # v3.0 S10.2: 按官方上限 524288
    return safe_json_parse(result, {
        "scene_type": "other",
        "meeting_subtype": "n/a",
        "perspective": "other",
        "scene_reason": "LLM 未返回",
        "confidence": "low",
        "is_external_knowledge": False,
        "external_ref_target": None,
    })
