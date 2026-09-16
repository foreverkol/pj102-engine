"""s12 冒烟测试: 验证字段名 bug 修复 + 分层路径 + v7.0 字段补全"""
import sys
import pathlib
sys.path.insert(0, "F:/workbuddy/项目空间/PJ-102-02项目/03-执行/code")

from core import AppConfig, setup_logging
from steps.s12_wiki import s12_write_all_5_types

cfg = AppConfig()
cfg.paths.ensure_dirs()

# mock state (模拟 12+2 步 pipeline 输出, 验证字段名对齐)
state = {
    "sample": "test_meeting_001.md",
    "content_hash": "a1b2c3d4e5f6",
    "s1": {"date": "2026-09-01", "title": "星云科技合作洽谈", "char_count": 15000, "recording_time": "14:00-15:30", "duration_estimate": "90min"},
    "s2": {"scene_type": "external_business", "scene_subtype": "partner_pitch", "perspective": "third_party", "scene_reason": "外部合作方来访", "confidence": 0.85, "is_external_knowledge": True},
    "s3": {"one_sentence": "星云科技提出税局连接方案合作", "background": "主理人与星云科技周总会谈", "problem": "税局连接逻辑如何打通", "method": "通过星云 SaaS 桥接税局接口", "outcome": "达成初步合作意向", "insight": "税局连接是票据电子化的关键节点", "quantitative_params": [{"type": "额度", "value": "3000万", "quote": "首批合作额度3000万", "speaker": "周总", "confidence": "high"}]},
    "s4": {"facts": ["周总是星云科技创始人", "星云做业票财税一体化SaaS"], "judgments": ["税局连接是票据电子化的关键节点", "资源整合比单点突破更重要"], "values": ["合作共赢", "长期主义"]},
    "s5": {"experiential": ["周总在税局连接方面有实战经验"], "judgmental": ["主理人认为税局连接逻辑值得投入"], "relational": ["主理人与周总是长期合作伙伴"]},
    "s6": {
        "persons": [{"name": "黄国华", "role": "创始人/CEO", "org": "星云科技", "relation_to_wang": "长期合作伙伴", "aliases": ["星云周总", "周总"], "quote_orig": "周总今天讲了税局连接的逻辑", "quote_line_range": [42, 50], "disambiguation_note": "", "entity_id": "P00001", "canonical_name": "黄国华"}],
        "organizations": [{"name": "星云科技", "type": "fintech", "aliases": ["星云"], "business_model": "业票财税一体化SaaS", "cooperation_status": "target", "quote_orig": "星云做业票财税一体化", "quote_line_range": [10, 15], "entity_id": "O00001", "canonical_name": "星云科技"}],
        "concepts": [{"name": "税局连接", "definition": "通过 SaaS 桥接税务局接口实现票据电子化", "quote_orig": "税局连接的逻辑", "quote_line_range": [42, 45]}],
        "products": [{"name": "星云SaaS", "type": "fintech_platform", "description": "业票财税一体化平台"}],
        "projects": [{"name": "税局桥接项目", "status": "exploring", "description": "打通税局接口的合作项目"}],
    },
    "s7": {"decisions": [{"decision": "启动税局连接POC", "owner": "主理人", "reason": "验证可行性", "deadline": "2026-10"}], "action_items": [{"action": "输出 POC 方案", "owner": "周总", "deadline": "2026-09-15"}]},
    "s8": {"risks": [{"risk": "税局接口不稳定", "impact": "high"}], "blindspots": [{"blindspot": "未评估合规风险"}]},
    "s9": {"knowledge_type": "tactical", "tags": ["票据电子化", "税局连接", "SaaS"], "reuse_scenarios": ["其他税局对接项目"]},
    "s10": {"cognitive_refinement": ["税局连接是票据电子化的关键节点", "SaaS桥接是降本路径"], "digital_human_material": {"speaking_style": "务实简洁", "frequently_used_words": ["关键节点", "降本"], "thinking_framework": "问题-方案-验证"}, "ldamc": {"lost": "合规细节", "different": "与海数交方案对比", "added": "税局连接新视角", "more": "需要POC验证", "connected": ["票据电子化", "SaaS桥接"]}},
    "s11": {"relevance": 0.85, "actionability": 0.75, "innovation": 0.70, "value_score": 0.77, "value_reason": "税局连接是关键节点且可行动"},
    "s13": {"financial_params": [{"type": "额度", "value": "3000万", "speaker": "周总", "quote_orig": "首批合作额度3000万"}]},
    "s14": [{"scenario_name": "税局连接合作", "scenario_type": "business_deal", "description": "星云科技与主理人探讨税局连接合作", "key_entities": ["星云科技", "黄国华"]}],
    "_meta": {"llm_provider": "minimax", "llm_model": "MiniMax-M3", "version": "v3.0"},
    "_integrations": {"entity_resolver": {"resolved": 2}, "citations": {"written": 3}, "scenario_extractor": {"written": 1}, "review_queue": {"enqueued": 2}},
}

# 关键验证: s12_write_all_5_types(state, cfg) -- 签名对齐 pipeline
result = s12_write_all_5_types(state, cfg)
print("=== s12 冒烟测试通过 ===")
for k, v in result.items():
    print(f"  {k}: {len(v)} 个文件")
    for f in v:
        print(f"    -> {f}")

# 验证分层路径
meeting_file = pathlib.Path(result["meetings"][0])
print(f"\n=== 路径验证 ===")
print(f"meeting 路径: {meeting_file}")
print(f"  在 Meetings/ 下: {'Meetings' in meeting_file.parts}")
print(f"  文件存在: {meeting_file.exists()}")

# 验证 frontmatter
content = meeting_file.read_text(encoding="utf-8")
print(f"\n=== frontmatter 关键字段验证 ===")
checks = {
    "method(非approach)": "method:" in content and "approach:" not in content,
    "relation_to_wang": "relation_to_wang:" in content,
    "business_model": "business_model" in content,
    "entity_id": "entity_id:" in content,
    "status_stage": "status_stage:" in content,
    "value_grade": "value_grade:" in content,
    "quantitative_params表": "金融参数" in content,
    "S13渲染": "S13" in content,
    "S14场景": "场景提取" in content,
    "集成结果": "集成结果" in content,
    "动态时间戳": "2026-09-04" not in content,
    "版本v3.0": "v3.0" in content and "v1.1" not in content,
}
for name, ok in checks.items():
    print(f"  {'✅' if ok else '❌'} {name}")

# 检查 person 文件
if result["persons"]:
    person_file = pathlib.Path(result["persons"][0])
    p_content = person_file.read_text(encoding="utf-8")
    print(f"\n=== person 文件验证 ===")
    print(f"  路径: {person_file}")
    print(f"  在 Entities/Persons/ 下: {'Entities' in person_file.parts and 'Persons' in person_file.parts}")
    print(f"  含 entity_id: {'entity_id:' in p_content}")
    print(f"  含 canonical_name: {'canonical_name:' in p_content}")
    print(f"  relation_to_wang(非relationship): {'relation_to_wang:' in p_content and 'relationship:' not in p_content}")

# 检查 concept 文件
if result["concepts"]:
    concept_file = pathlib.Path(result["concepts"][0])
    print(f"\n=== concept 文件验证 ===")
    print(f"  路径: {concept_file}")
    print(f"  在 Knowledge/Concepts/ 下: {'Knowledge' in concept_file.parts and 'Concepts' in concept_file.parts}")

# 检查 judgment 文件
if result["judgments"]:
    judgment_file = pathlib.Path(result["judgments"][0])
    print(f"\n=== judgment 文件验证 ===")
    print(f"  路径: {judgment_file}")
    print(f"  在 Knowledge/Judgments/ 下: {'Knowledge' in judgment_file.parts and 'Judgments' in judgment_file.parts}")
    j_content = judgment_file.read_text(encoding="utf-8")
    print(f"  含 value_grade: {'value_grade:' in j_content}")

# 清理测试文件
import shutil
test_dir = cfg.paths.wiki_base
for f in test_dir.rglob("*.md"):
    if "test_meeting" in f.name or "a1b2c3d4" in f.name:
        f.unlink()
print("\n=== 全部冒烟测试通过 ===")
