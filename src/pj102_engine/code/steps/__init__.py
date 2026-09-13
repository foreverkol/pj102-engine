"""
steps package - 注册所有 s1-s13 步骤
"""
from .s1_basic import s1_basic_info
from .s2_scene import s2_scene_recognition
from .s3_summary import s3_standard_summary
from .s4_fjv import s4_fjv
from .s5_implicit import s5_implicit_knowledge
from .s6_entity import s6_entity_extraction
from .s7_decision import s7_action_decision
from .s8_risk import s8_risk_blindspot
from .s9_classify import s9_knowledge_classify
from .s10_cognitive import s10_cognitive_refine
from .s11_value import s11_value_rating
from .s12_wiki import s12_write_wiki, s12_write_all_5_types
from .s13_financial_params import s13_financial_params
from .s14_scenario import s14_scenario  # v3.0 v7.0 新增

__all__ = [
    "s1_basic_info",
    "s2_scene_recognition",
    "s3_standard_summary",
    "s4_fjv",
    "s5_implicit_knowledge",
    "s6_entity_extraction",
    "s7_action_decision",
    "s8_risk_blindspot",
    "s9_knowledge_classify",
    "s10_cognitive_refine",
    "s11_value_rating",
    "s12_write_wiki",
    "s12_write_all_5_types",
    "s13_financial_params",
    "s14_scenario",  # v3.0 v7.0 新增
]
