"""
S3: 标准摘要(LLM) - v3.0 升级(v6.1 [判断:发言人] + quantitative_params 9 类)
"""
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from llm_client import LLMClient, safe_json_dict
from excerpt import excerpt_limit

# s3 输入截断上限(字)。2026-09-16 由 6000 提到 20000:
# 43 个源稿中位长 25664 字 → 原值只覆盖约 23%, 长会议的中后段关键数字与
# 判断被系统性丢弃(实测: "需要几百人→十几人"/"花了一年左右" 均落在窗口内却漏抓,
# 原因有二 —— ① 抓取规则排斥非货币数字 ② 窗口过小)。
EXCERPT_LIMIT = excerpt_limit(20000)


def s3_standard_summary(content: str, llm: LLMClient) -> dict:
    """LLM 输出五要素摘要 + [判断:发言人] + quantitative_params 9 类

    ⚠ 截断上限: 原为 6000 字, 但 43 个源稿**中位长 25664 字** → 原设置只覆盖
    约 23% 的文本, 长会议中后段的关键数字与判断系统性丢失 (2026-09-16 实测)。
    提到 20000 字覆盖约 78%; 成本影响可忽略 (s3 输入 +约 1.9万 tokens/样本,
    按 0.4 元/M 计 <0.01 元/样本)。
    """
    truncated = len(content) > EXCERPT_LIMIT
    excerpt = content[:EXCERPT_LIMIT]
    _tail = (f"\n\n⚠ 注意: 原文共 {len(content)} 字, 此处仅含前 {EXCERPT_LIMIT} 字,"
             f"末尾 {len(content) - EXCERPT_LIMIT} 字**未提供** —— "
             f"不要臆测未提供部分的内容。" if truncated else "")

    prompt = f"""请输出以下会议的标准摘要,每条内容需加 [判断:发言人] 标注。

会议内容(前 {EXCERPT_LIMIT} 字):
{excerpt}{_tail}

【v6.1 输出格式(judgment label)】

- **背景**:[事实/判断陈述] [判断:张三](如属纯事实表述,可不加)
- **问题**:[事实/判断陈述] [判断:张三]
- **方法**:[方案描述] (一般事实,少标判断)
- **结果**:[达成的共识/成果] [判断:李四]
- **启示**:[对未来指导意义] [判断:李四] (一般属于判断推断)

【署名硬规则 —— 必须遵守】
1. 方括号内**只写人名本身**,例如 [判断:张三]、[判断:李四]。
2. **严禁**写入下列字样:「发言人」「发言人本人」「发言人1」「说话人」「本人」「关键发言人」等
   转写口条词。它们只是录音转写工具的标记,不是人名。
   ✗ 错误:[判断:发言人本人张三]   ✓ 正确:[判断:张三]
3. 同一句如由多人共同判断,用顿号连接:[判断:张三、李四]。
4. 若确实无法判断是谁说的,宁可不加 [判断:...],也不要写占位词。

【判断句判定标准】
- 含「觉得/认为/相信/估计/可能/应该/看来/估计是」→ 判断
- 含具体数字/日期/名称 → 事实
- 行动计划(「要/将/会/计划」)→ 事实/愿景,不标判断
- 「已签约」→ 事实(有具体行为)
- 「资源整合是关键」→ 判断(主观评估)→ 标 [判断:张三]

【v6.1 字段 quantitative_params - 9 类金融参数】
- type 必填,枚举:
  * 额度 / 授信金额
  * 利率 / 费率
  * 期限 / 账期
  * 保证金比例
  * 营业收入
  * 净利润
  * 目标市场规模
  * 客单价
  * 其他关键数字

- value: 数值字符串(如 "3000万", "4.35%", "6个月")
- quote: 原文 verbatim(15-50 字)
- speaker: 发言人
- confidence: high/medium/low

抓取规则:
- 必须有**具体数字**。数字分两类, **都必须抓**:
  ① 金额/比率类: 万 / 亿 / 千万 / % / 元 (如 "3000万"、"4.35%")
  ② 规模/时长类: 人数(几百人 / 十几人 / 一个人)、时长(8-9个月 / 一年左右 / 三年)、
     倍数(翻倍 / 三倍)、月份(6个月)、面积 / 产量 / 团队规模等
- **「其他关键数字」专项覆盖**: 团队规模变化、投入时长与金额、业务周期 —— 这类
  即使**不含 "万/亿" 等货币单位**, 同样是关键数字,
  ✗ 严禁因缺少货币单位而漏抓 (2026-09-16 实测: 原规则漏掉 "需要几百人→十几人"、
    "花了一年左右", 二者在源稿中确实存在)。
- quote 必须 verbatim 复制原文; speaker 必填。
若无金融参数 → quantitative_params: []。

【输出 JSON 格式】
{{
  "one_sentence": "一句话总结(≤30 字)",
  "background": "...",
  "problem": "...",
  "method": "...",
  "outcome": "...",
  "insight": "...",
  "quantitative_params": [
    {{"type": "额度", "value": "3000万", "quote": "...", "speaker": "刘总", "confidence": "high"}}
  ]
}}

只输出 JSON。
"""
    result = llm.call(prompt, max_tokens=524288)  # v3.0 S10: 升 8000
    parsed = safe_json_dict(result, {
        "one_sentence": "未提取",
        "background": "未提取",
        "problem": "未提取",
        "method": "未提取",
        "outcome": "未提取",
        "insight": "未提取",
        "quantitative_params": [],
    })

    # 确保 quantitative_params 是数组
    if "quantitative_params" not in parsed:
        parsed["quantitative_params"] = []
    if not isinstance(parsed["quantitative_params"], list):
        parsed["quantitative_params"] = []

    # ---- 出口兜底清洗（幂等，仅 T1/T2）----------------------------------
    # 即便提示词已加硬规则，模型仍可能带入转写口条噪声（源稿口条形如
    # 「发言人本人张三」，2026-09-16 实测 9 个样本 32 处）→ 出口再兜一层。
    # 注意：白名单归约(T3)依赖 config/speaker_alias.json（**部署侧数据**），
    # 刻意不在此启用，以保持引擎在其它环境/朋友机上可移植。
    try:
        from speaker_norm import clean_text
        _ENGINE_SAFE_CFG = {"canonical_names": [], "alias_map": {}}
        for _k, _v in list(parsed.items()):
            if isinstance(_v, str):
                parsed[_k], _ = clean_text(_v, _ENGINE_SAFE_CFG, enable_t3=False)
        for _q in parsed.get("quantitative_params", []):
            if isinstance(_q, dict) and isinstance(_q.get("speaker"), str):
                _q["speaker"], _ = clean_text(_q["speaker"], _ENGINE_SAFE_CFG, enable_t3=False)
    except Exception as _e:  # 清洗失败不得阻断管线
        print(f"[WARN] s3 署名兜底清洗跳过: {type(_e).__name__}: {_e}")

    return parsed
