"""
S11: 价值评级（LLM）
- relevance: 与主理人核心业务的相关度
- actionability: 行动可落地性
- innovation: 新颖性
- value_score: 综合价值
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from llm_client import LLMClient, safe_json_parse
from excerpt import excerpt_for_llm


def s11_value_rating(content: str, llm: LLMClient) -> dict:
    """LLM 价值评级"""
    excerpt, EXCERPT_LIMIT = excerpt_for_llm(content, 4000)

    prompt = f"""为会议做价值评级，输出 JSON：

会议内容：{excerpt}

请输出：
{{
  "relevance": 0.0-1.0,        # 与主理人核心业务的相关度
  "actionability": 0.0-1.0,     # 行动可落地性
  "innovation": 0.0-1.0,        # 新颖性
  "value_score": 0.0-1.0,       # 综合价值（=0.4*relevance+0.3*actionability+0.3*innovation）
  "value_reason": "评分理由"
}}

只输出 JSON。
"""
    result = llm.call(prompt, max_tokens=524288)  # v3.0 S10.2: 按官方上限 524288(实测)
    return safe_json_parse(result, {
        "relevance": 0.5, "actionability": 0.5, "innovation": 0.5,
        "value_score": 0.5, "value_reason": "LLM 失败",
    })