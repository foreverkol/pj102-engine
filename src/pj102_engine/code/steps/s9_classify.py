"""
S9: 知识归类(LLM) - v3.0 升级(v6.1 可转化资产 tag 5 类)
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from llm_client import LLMClient, safe_json_dict
from excerpt import excerpt_for_llm


def s9_knowledge_classify(content: str, llm: LLMClient) -> dict:
    """LLM 知识归类 + 复用场景 + v6.1 可转化资产 tag 5 类"""
    excerpt, EXCERPT_LIMIT = excerpt_for_llm(content, 8000)

    prompt = f"""根据会议内容,做知识归类,输出 JSON:

会议内容(前 {EXCERPT_LIMIT} 字):
{excerpt}

【v3.0 输出格式】

- knowledge_type: methodology/dataset/network/relationship/contact/event/project/business_model/case_study/rule/insight/...
- tags 数组,必须包含:
  1. 分类标签(可选): #供应链金融 #票据 #金融科技 #产业互联网 #银行合作 #创业 #融资
  2. 【v6.1 强制】可转化资产标签(5 类),至少 1 个:
     * #可转化资产/#BP素材     - 背景描述、市场痛点、商业模式、市场规模数据
     * #可转化资产/#官网文案   - 公司介绍、产品说明、核心优势、服务案例
     * #可转化资产/#销售话术   - 客户常见问题解答、产品卖点话术、竞品对比话术
     * #可转化资产/#演讲素材   - 行业趋势判断、方法论、案例故事
     * #可转化资产/#客户案例   - 成功合作经历、客户背景、解决方案、成果数据

- reuse_scenarios 数组: 列出可复用场景
  * investor_pitch - 投资人沟通
  * client_persuasion - 客户说服
  * banker_communication - 银行沟通
  * channel_negotiation - 渠道谈判
  * internal_training - 内部培训
  * digital_human_training - 数字人语料

- 【W4 三轴受控标签】
  * topics 数组: 主题域,只能从以下词表选(最多 3 个,按内容相关度):
      ai / finance / industry / science / technology / product / methodology
  * meta_type 字符串: 页面性质,只能从以下词表选一个:
      comparison(对比) / timeline(时间线) / controversy(争议) / prediction(预测主张) / tutorial(教程) / reference(参考)
    会议内容归 reference; 含明确趋势判断/预测归 prediction; 含方案对比归 comparison

【示例输出】
{{
  "knowledge_type": "methodology",
  "tags": [
    "#供应链金融", "#票据",
    "#可转化资产/#BP素材",
    "#可转化资产/#演讲素材"
  ],
  "reuse_scenarios": ["investor_pitch", "banker_communication"],
  "topics": ["finance", "product"],
  "meta_type": "reference"
}}

【规则】
1. tags 数组必须 ≥ 2 个,含至少 1 个 #可转化资产/
2. 分类标签按内容匹配,可空
3. topics 只能从词表选,最多 3 个,无相关则空数组
4. meta_type 只能从词表选一个,默认 reference
5. 只输出 JSON
"""
    result = llm.call(prompt, max_tokens=524288)  # v3.0 S10.2: 按官方上限 524288
    parsed = safe_json_dict(result, {
        "knowledge_type": "general",
        "tags": [],
        "reuse_scenarios": [],
    })

    # 确保列表类型
    if "tags" not in parsed or not isinstance(parsed["tags"], list):
        parsed["tags"] = []
    if "reuse_scenarios" not in parsed or not isinstance(parsed["reuse_scenarios"], list):
        parsed["reuse_scenarios"] = []

    return parsed
