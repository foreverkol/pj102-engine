"""
S5: 隐性知识（LLM × 3 次子调用）
- experiential: 体验性隐性知识（亲身经历、案例、踩过的坑）
- judgmental: 判断性隐性知识（思维模型、决策框架）
- relational: 关系性隐性知识（人脉网络、信任关系）
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from llm_client import LLMClient, safe_json_parse


def s5_implicit_knowledge(content: str, llm: LLMClient) -> dict:
    """3 次子调用：体验性/判断性/关系性"""
    excerpt = content[:6000]

    # 5.1 体验性
    p1 = f"""从会议中提取主理人的"体验性隐性知识"（亲身经历、案例、踩过的坑）：
会议内容：{excerpt}

输出 JSON：{{"experiential": ["体验1", "体验2", "体验3"]}}（最多 3 条）"""
    exp_data = safe_json_parse(llm.call(p1, max_tokens=524288), {"experiential": []})  # v3.0 S10: 8000

    # 5.2 判断性
    p2 = f"""从会议中提取主理人的"判断性隐性知识"（思维模型、决策框架、判断标准）：
会议内容：{excerpt}

输出 JSON：{{"judgmental": ["判断1", "判断2", "判断3"]}}（最多 3 条）"""
    jud_data = safe_json_parse(llm.call(p2, max_tokens=524288), {"judgmental": []})  # v3.0 S10: 8000

    # 5.3 关系性
    p3 = f"""从会议中提取"关系性隐性知识"（人脉网络、信任关系、合作模式）：
会议内容：{excerpt}

输出 JSON：{{"relational": ["关系1", "关系2", "关系3"]}}（最多 3 条）"""
    rel_data = safe_json_parse(llm.call(p3, max_tokens=524288), {"relational": []})  # v3.0 S10: 8000

    return {
        "experiential": exp_data.get("experiential", []),
        "judgmental": jud_data.get("judgmental", []),
        "relational": rel_data.get("relational", []),
    }