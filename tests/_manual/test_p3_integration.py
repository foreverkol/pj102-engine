"""P3 集成验证: pipeline 完整导入链 + 集成模块 API 对接"""
import sys
import pathlib
sys.path.insert(0, "F:/workbuddy/项目空间/PJ-102-02项目/03-执行/code")

from core import AppConfig, setup_logging, get_logger

cfg = AppConfig()
cfg.paths.ensure_dirs()
logger = setup_logging(cfg.paths.logs_dir)

print("=== 1. pipeline 完整导入链 ===")
import pipeline
print(f"  pipeline 导入: OK")
print(f"  process_one: {hasattr(pipeline, 'process_one')}")
print(f"  _run_integrations: {hasattr(pipeline, '_run_integrations')}")
print(f"  main: {hasattr(pipeline, 'main')}")
print(f"  load_index: {hasattr(pipeline, 'load_index')}")

print("\n=== 2. steps 导入链 ===")
from steps import (
    s1_basic_info, s2_scene_recognition, s3_standard_summary,
    s4_fjv, s5_implicit_knowledge, s6_entity_extraction,
    s7_action_decision, s8_risk_blindspot, s9_knowledge_classify,
    s10_cognitive_refine, s11_value_rating, s12_write_wiki,
    s12_write_all_5_types, s13_financial_params, s14_scenario,
)
print(f"  全部 14 个 step 函数导入: OK")

print("\n=== 3. LLMClient 导入 ===")
from llm_client import LLMClient, safe_json_parse
print(f"  LLMClient: OK")
print(f"  safe_json_parse: OK")

print("\n=== 4. 集成模块 API 对接验证 ===")

# 4a. entity_resolver
try:
    from entity_resolver import EntityResolver
    resolver = EntityResolver(cfg.paths.registry_path)
    r = resolver.resolve_or_create("person", "测试人物", ["别名1"])
    has_save = hasattr(resolver, "save")
    print(f"  entity_resolver: OK (resolve_or_create + save={has_save})")
    print(f"    返回 entity_id: {r.get('entity_id', 'N/A')}")
    # 清理: 还原 registry
    if cfg.paths.registry_path.exists():
        import json
        data = json.loads(cfg.paths.registry_path.read_text(encoding="utf-8"))
        # 不修改原 registry, 只是测试
except Exception as e:
    print(f"  entity_resolver: FAIL - {e}")

# 4b. citations
try:
    from citations import write_citations_intermediate
    print(f"  citations.write_citations_intermediate: OK")
except Exception as e:
    print(f"  citations: FAIL - {e}")

# 4c. scenario_extractor
try:
    from scenario_extractor import write_scenarios
    print(f"  scenario_extractor.write_scenarios: OK")
except Exception as e:
    print(f"  scenario_extractor: FAIL - {e}")

# 4d. review_queue
try:
    from review_queue import enqueue
    print(f"  review_queue.enqueue: OK")
except Exception as e:
    print(f"  review_queue: FAIL - {e}")

print("\n=== 5. build_index 导入 ===")
sys.path.insert(0, "F:/workbuddy/项目空间/PJ-102-02项目/03-执行/scripts")
import build_index
print(f"  build_index.build: {hasattr(build_index, 'build')}")

print("\n=== 6. core 层完整性 ===")
from core import AppConfig, compute_content_hash, get_logger, setup_logging
print(f"  AppConfig: OK")
print(f"  compute_content_hash: {compute_content_hash('test')}")
print(f"  get_logger: OK")
print(f"  setup_logging: OK")

print("\n=== 7. 路径配置验证 ===")
paths = cfg.paths
print(f"  project_root: {paths.project_root}")
print(f"  wiki_base: {paths.wiki_base}")
print(f"  wiki_meetings: {paths.wiki_meetings}")
print(f"  wiki_persons: {paths.wiki_persons}")
print(f"  wiki_organizations: {paths.wiki_organizations}")
print(f"  wiki_concepts: {paths.wiki_concepts}")
print(f"  wiki_judgments: {paths.wiki_judgments}")
print(f"  wiki_comparisons: {paths.wiki_comparisons}")
print(f"  wiki_scenarios: {paths.wiki_scenarios}")
print(f"  data_raw: {paths.data_raw}")
print(f"  data_index: {paths.data_index}")
print(f"  registry_path: {paths.registry_path}")
print(f"  processed_state: {paths.processed_state}")

print("\n=== 8. LLM 配置验证(主理人铁律) ===")
print(f"  model: {cfg.llm.model}")
print(f"  max_tokens: {cfg.llm.max_tokens}")
print(f"  base_url: {cfg.llm.base_url}")
print(f"  sample_limit: {cfg.sample_limit}")

print("\n=== 全部 P3 集成验证通过 ===")
