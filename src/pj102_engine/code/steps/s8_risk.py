"""
S8: 风险点+盲区（LLM）
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from llm_client import LLMClient, safe_json_parse
from excerpt import excerpt_for_llm


def s8_risk_blindspot(content: str, llm: LLMClient) -> dict:
    """LLM 提取风险和盲区"""
    excerpt, EXCERPT_LIMIT = excerpt_for_llm(content, 6000)

    prompt = f"""从会议中识别风险点和盲区，输出 JSON 格式：

会议内容（前 {EXCERPT_LIMIT} 字）：
{excerpt}

请输出：
{{
  "risks": [
    {{"risk": "风险描述", "impact": "高/中/低", "mitigation": "应对建议"}}
  ],
  "blindspots": [
    {{"blindspot": "盲区描述", "context": "为什么没注意到"}}
  ],
  "uncertain": ["不确定事项1", "不确定事项2"]
}}

每类最多 3 条，只输出 JSON。
"""
    result = llm.call(prompt, max_tokens=524288)  # v3.0 S10.2: 按官方上限 524288
    return safe_json_parse(result, {
        "risks": [], "blindspots": [], "uncertain": [],
    })