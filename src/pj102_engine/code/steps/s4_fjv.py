"""
S4: FJV 三分法（LLM）
- F (Fact): 客观事实，含具体数字、时间、地点、机构
- J (Judgment): 主理人的判断、观点、看法
- V (Value): 价值、机会、长期意义
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from llm_client import LLMClient, safe_json_parse


def s4_fjv(content: str, llm: LLMClient) -> dict:
    """LLM 提取 FJV 三分法"""
    excerpt = content[:8000]

    prompt = f"""请从以下会议中提取 FJV 三分法判断，输出 JSON 格式：

会议内容（前 8000 字）：
{excerpt}

FJV 说明：
- F (Fact): 客观事实，含具体数字、时间、地点、机构
- J (Judgment): 主理人（说话者本人）的判断、观点、看法
- V (Value): 价值、机会、长期意义

请输出：
{{
  "facts": ["事实1（带原文引述）", "事实2", ...],
  "judgments": ["判断1（必须是主理人本人的观点）", "判断2", ...],
  "values": ["价值1", "价值2", ...]
}}

每项最多 5 条，只输出 JSON。
"""
    result = llm.call(prompt, max_tokens=524288)  # v3.0 S10.2: 按官方上限 524288
    return safe_json_parse(result, {
        "facts": [], "judgments": [], "values": [],
    })