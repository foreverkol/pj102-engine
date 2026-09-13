"""
S14: 商业模式片段识别(LLM) - v3.0 新增 step(v7.0 FR-v7.0-008)

v7.0 §六 Scenario 11 字段必填:
  theme / customer / pain_point / offering / value_capture / channel
  / key_resources / key_constraints / hidden_assumptions
  / trigger_signals / failure_modes

输出 JSON:
  0 个 scenario(识别不到) → scenarios: []
  ≥ 3 字段清晰才输出 scenario(简化:全 11 字段都试图填,空数组兜底)
"""

import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from llm_client import LLMClient, safe_json_parse


SCENARIO_FIELDS = [
    "theme", "customer", "pain_point", "offering",
    "value_capture", "channel", "key_resources",
    "key_constraints", "hidden_assumptions",
    "trigger_signals", "failure_modes",
]


def s14_scenario(content: str, llm: LLMClient) -> list:
    """LLM 提取 0-N 个 scenario

    Returns:
        [{theme, customer, ..., failure_modes}, ...]
    """
    excerpt = content[:10000]

    prompt = f"""分析以下会议内容,识别是否存在"商业模式片段"(scenario)。

会议内容(前 10000 字):
{excerpt}

【11 字段定义 - 必须填全】

1. theme: 业务主题/模式名(中文简短,如"财税数据→供应链金融变现")
2. customer: 目标客户(谁会用这个模式)
3. pain_point: 客户痛点(具体可感知的问题)
4. offering: 提供的产品/服务(具体内容)
5. value_capture: 价值捕获方式(SaaS订阅/佣金/分润/广告等)
6. channel: 分销渠道(直销/分销/合作伙伴等)
7. key_resources: 关键资源(数组,如 ["税局系统级连接", "业财税软件"])
8. key_constraints: 关键约束(数组,如 ["税局接口稳定性", "数据安全合规"])
9. hidden_assumptions: 隐性假设(数组,如 ["企业愿将核心数据放在第三方"])
10. trigger_signals: 触发信号(数组,如 ["企业财务有降本增效压力"])
11. failure_modes: 失败模式(数组,如 ["政策变化阻断连接"])

【输出规则】

- 识别到至少 3 个清晰字段,返回完整 scenario
- 若识别不到,返回空数组
- 输出 JSON 数组

【示例输出】

场景 1(财税 SaaS):
{{
  "theme": "财税数据→供应链金融变现",
  "customer": "中大企业的财务部门",
  "pain_point": "财务部门是成本中心,无法从数据中产生额外收入",
  "offering": "以税局连接为基础,打通业财税票,形成数据底座",
  "value_capture": "SaaS订阅 + 金融服务佣金/分润",
  "channel": "直销(中大企业)+ 园区/财税公司分销(小企业)",
  "key_resources": ["税局系统级连接", "业财税一体化软件"],
  "key_constraints": ["税局接口稳定性", "数据安全合规"],
  "hidden_assumptions": ["企业愿将核心经营数据放在第三方平台"],
  "trigger_signals": ["企业财务有降本增效压力", "已有多个银行关系需统一出口"],
  "failure_modes": ["税局政策变化阻断连接", "中大企业自研或选 ERP 巨头"]
}}

场景 2(票据中介):
{{
  "theme": "票据中介升级为系统服务商",
  ...
}}

【约束】
1. 11 字段全填,空字符串 "" 或空数组 [] 都算填
2. 完全无业务模式讨论 → 输出 []
3. 只输出 JSON 数组
"""
    result = llm.call(prompt, max_tokens=524288)  # v3.0 S10.2: 按官方上限 524288
    parsed = safe_json_parse(result, [])

    if not isinstance(parsed, list):
        return []

    # 校验 + 过滤
    valid = []
    for item in parsed:
        if not isinstance(item, dict):
            continue
        if not item.get("theme"):
            continue
        # 至少 3 个非空字段
        non_empty = sum(
            1 for k in SCENARIO_FIELDS
            if item.get(k) and item[k] != "" and item[k] != []
        )
        if non_empty < 3:
            continue
        # 确保 11 字段都有(空字符串兜底)
        for k in SCENARIO_FIELDS:
            if k not in item:
                if k in ("key_resources", "key_constraints",
                        "hidden_assumptions", "trigger_signals",
                        "failure_modes"):
                    item[k] = []
                else:
                    item[k] = ""
        valid.append(item)
    return valid
