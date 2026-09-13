"""PJ-102 core schema — 各步 IO 定义 + 统一 content_hash + WIKI 布局

修复的历史问题:
  - build_index.py 用 SHA1[:12] 前 64KB, daily_incremental.py 用 SHA256[:12] 全文
    两个 content_hash 算法不一致 -> 增量去重失效. 此处统一为 SHA256[:12] 全文.
  - s12_wiki 字段名 bug: 读 s3.approach(实际 method) / s6 person.relationship
    (实际 relation_to_wang) / s6 org.role(不存在). 此处 TypedDict 以 step 实际
    输出字段为准, 杜绝手写字段名错误.
"""
from __future__ import annotations

import hashlib
from typing import Any, Dict, List, Optional, TypedDict


def compute_content_hash(content: str) -> str:
    """统一 content_hash: SHA256[:12] 全文

    替代:
      - build_index.py 的 SHA1[:12] 前 64KB(算法不一致)
      - daily_incremental.py 自有的 compute_content_hash(此处为单一真相源)

    Returns:
        12 字符十六进制 hash, 作为文件唯一标识
    """
    return hashlib.sha256(content.encode("utf-8")).hexdigest()[:12]


# ============ 各 step IO TypedDict(以 step 实际输出字段为准) ============

class S1Basic(TypedDict, total=False):
    title: str
    date: str
    filename: str
    size_bytes: int
    char_count: int
    line_count: int
    recording_time: Optional[str]
    duration_estimate: str


class S2Scene(TypedDict, total=False):
    scene_type: str
    meeting_subtype: str
    perspective: str
    scene_reason: str
    confidence: str
    is_external_knowledge: bool
    external_ref_target: Optional[str]


class S3Summary(TypedDict, total=False):
    one_sentence: str
    background: str
    problem: str
    method: str          # 注: s12 旧代码误读 approach, 实际是 method
    outcome: str
    insight: str
    quantitative_params: List[Dict[str, Any]]


class S4FJV(TypedDict, total=False):
    facts: List[str]
    judgments: List[str]
    values: List[str]


class S5Implicit(TypedDict, total=False):
    experiential: List[str]
    judgmental: List[str]
    relational: List[Any]


class S6Person(TypedDict, total=False):
    name: str
    role: str
    org: str
    relation_to_wang: str   # 注: s12 旧代码误读 relationship, 实际是 relation_to_wang
    aliases: List[str]
    quote_orig: str
    quote_line_range: List[int]
    disambiguation_note: str


class S6Organization(TypedDict, total=False):
    name: str
    type: str
    aliases: List[str]
    business_model: str    # 注: s12 旧代码误读 role, 实际 org 无 role 字段
    cooperation_status: str
    quote_orig: str
    quote_line_range: List[int]


class S6Entity(TypedDict, total=False):
    persons: List[S6Person]
    organizations: List[S6Organization]
    concepts: List[Dict[str, Any]]
    products: List[Dict[str, Any]]
    projects: List[Dict[str, Any]]


class S7Decision(TypedDict, total=False):
    decisions: List[Dict[str, Any]]
    action_items: List[Dict[str, Any]]


class S8Risk(TypedDict, total=False):
    risks: List[Any]
    blindspots: List[Any]
    uncertain: List[Any]


class S9Classify(TypedDict, total=False):
    knowledge_type: str
    tags: List[str]
    reuse_scenarios: List[str]


class S10Cognitive(TypedDict, total=False):
    cognitive_refinement: List[str]
    digital_human_material: Dict[str, Any]
    ldamc: Dict[str, Any]   # v7.0 5 维: lost/different/added/more/connected


class S11Value(TypedDict, total=False):
    relevance: float
    actionability: float
    innovation: float
    value_score: float
    value_reason: str


class S13Financial(TypedDict, total=False):
    # list[{type, value, quote, speaker, confidence}]
    pass  # 实际是 list, 用 List[Dict] 表达


class S14Scenario(TypedDict, total=False):
    # list of 11-field scenario
    pass


class PipelineState(TypedDict, total=False):
    """单样本完整处理结果(12+2 step + meta)"""
    sample: str
    content_hash: str
    s1: S1Basic
    s2: S2Scene
    s3: S3Summary
    s4: S4FJV
    s5: S5Implicit
    s6: S6Entity
    s7: S7Decision
    s8: S8Risk
    s9: S9Classify
    s10: S10Cognitive
    s11: S11Value
    s13: List[Dict[str, Any]]   # 金融参数 list
    s14: List[Dict[str, Any]]   # scenario list
    _meta: Dict[str, str]
    _integrations: Dict[str, Any]   # 集成层产出(entity_registry/citations/scenarios/review)


# ============ WIKI 页面类型与布局 ============

WIKI_PAGE_TYPES = ["meeting", "person", "organization", "concept",
                   "judgment", "comparison", "scenario"]

# v7.0 §8.1 必填字段(对齐 s12 实际产出, 修复 lint_wiki REQUIRED_FIELDS 不匹配)
REQUIRED_FIELDS_V7 = {
    "meeting": ["subtype", "publishability", "reusable_for",
                "ldamc", "source_ref"],
    "person": ["entity_id", "canonical_name", "thinking_framework",
               "values_beliefs", "decision_style", "emotional_tone"],
    "judgment": ["topic_key", "evidence_chain", "confidence_rationale"],
    "organization": ["entity_id", "org_name", "org_type",
                     "business_model", "cooperation_status"],
    "scenario": ["theme", "customer", "pain_point", "offering",
                 "value_capture", "channel", "key_resources",
                 "key_constraints", "hidden_assumptions",
                 "trigger_signals", "failure_modes"],
}

# 5 类 WIKI 产出 + scenario + organization(v7.0 扩展)
WIKI_LAYOUT = {
    "Meetings": "meeting",
    "Entities/Persons": "person",
    "Entities/Organizations": "organization",
    "Knowledge/Concepts": "concept",
    "Knowledge/Judgments": "judgment",
    "Knowledge/Comparisons": "comparison",
    "Knowledge/Scenarios": "scenario",
}
