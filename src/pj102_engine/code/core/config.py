"""PJ-102 core 配置层 — 跨平台路径 + LLM 参数 + step 配置

设计原则:
  1. 路径全部 pathlib.Path, 默认项目内(跨平台可跑), 可被环境变量覆盖
  2. 配置来源优先级: 环境变量 > config/pipeline.yaml > 代码默认值
  3. 守引擎铁律: MiniMax-M3 / max_tokens=524288 / SAMPLE_LIMIT 默认 10

修复的历史问题:
  - pipeline.py WIKI_BASE 硬编码 /mnt/d/BaiduSyncdisk/... (Windows 不可跑)
  - registry.yaml llm_model: MiniMax-Text-01 (主理人 09-04 纠正未同步)
  - launcher.yaml packages: [] 全标准库 (v4.0 引入 pydantic/pyyaml/jinja2)
  - excerpt/max_tokens/temperature 全硬编码, 不可 per-step 调优
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Optional

# 项目根: core/config.py -> parents[2] = pj102 engine根
# PJ-102 原始布局: parents[3] (因 code/ 在 03-执行/code/ 下)
# 本项目布局:   parents[2] (因 code/ 直接在项目根下)
# sync_from_pj102.sh 升级 PJ-102 时需手动合并此行
PROJECT_ROOT = Path(os.environ.get("PJ102_PROJECT_ROOT") or Path.cwd())

# 默认路径(跨平台, 项目内)
# PJ-102 默认: system/data/raw (源数据放在项目内)
# 本项目适配: 源数据在外部(数据资产 3已治理), 优先级 env > config/project.yaml > 本项目默认
# 已修复 (2026-09-08): 默认指向 system/state/index.json, 与 ingest_source.py 写入路径一致
# 旧默认 system/data/index.json 含错位 demo 文件名, 之前 driver 永远读不到真实数据
DEFAULT_DATA_RAW = Path(
    os.environ.get(
        "PJ102_DATA_RAW",
        # 兜底: 用 config/project.yaml 里的 source_dir (如果存在)
        str(
            Path(__file__).resolve().parents[1] / "system" / "state" / "raw"
        ),
    )
)
DEFAULT_DATA_INDEX = PROJECT_ROOT / "system" / "state" / "index.json"
DEFAULT_SYSTEM_DIR = PROJECT_ROOT / "system"
DEFAULT_WIKI_BASE = PROJECT_ROOT / "wiki"
DEFAULT_REGISTRY_PATH = DEFAULT_SYSTEM_DIR / "registry" / "entity_registry.json"
DEFAULT_PROCESSED_STATE = DEFAULT_SYSTEM_DIR / "state" / "processed_files.json"
DEFAULT_LOGS_DIR = PROJECT_ROOT / "logs"

CONFIG_YAML = PROJECT_ROOT / "config" / "pipeline.yaml"

# 引擎铁律常量
LLM_MODEL_MINIMAX = "MiniMax-M3"          # 09-04 纠正, 严禁 MiniMax-Text-01
LLM_MAX_TOKENS = 524288                    # 官方上限, 主理人 09-04 18:30
DEFAULT_SAMPLE_LIMIT = 10                  # 主理人限制 <=10(可放宽到 13 已认可)
PROJECT_VERSION = "v4.0-refactor"


@dataclass
class PathConfig:
    """跨平台路径配置, 默认项目内, 环境变量可覆盖"""

    project_root: Path = PROJECT_ROOT
    data_raw: Path = DEFAULT_DATA_RAW
    data_index: Path = DEFAULT_DATA_INDEX
    system_dir: Path = DEFAULT_SYSTEM_DIR
    wiki_base: Path = DEFAULT_WIKI_BASE
    registry_path: Path = DEFAULT_REGISTRY_PATH
    processed_state: Path = DEFAULT_PROCESSED_STATE
    logs_dir: Path = DEFAULT_LOGS_DIR

    # WIKI 统一布局(对齐 v7.0 设计 + lint_wiki/scenario_extractor/citations 期望)
    wiki_meetings: Path = field(default_factory=lambda: Path())
    wiki_persons: Path = field(default_factory=lambda: Path())
    wiki_organizations: Path = field(default_factory=lambda: Path())
    wiki_concepts: Path = field(default_factory=lambda: Path())
    wiki_judgments: Path = field(default_factory=lambda: Path())
    wiki_comparisons: Path = field(default_factory=lambda: Path())
    wiki_scenarios: Path = field(default_factory=lambda: Path())

    def __post_init__(self) -> None:
        # 环境变量覆盖 wiki_base(支持外置知识库目录)
        env_wiki = os.environ.get("PJ102_WIKI_BASE")
        if env_wiki:
            self.wiki_base = Path(env_wiki)
        # 统一子目录布局(分层, 首字母大写, 对齐 v7.0 设计文档)
        self.wiki_meetings = self.wiki_base / "Meetings"
        self.wiki_persons = self.wiki_base / "Entities" / "Persons"
        self.wiki_organizations = self.wiki_base / "Entities" / "Organizations"
        self.wiki_concepts = self.wiki_base / "Knowledge" / "Concepts"
        self.wiki_judgments = self.wiki_base / "Knowledge" / "Judgments"
        self.wiki_comparisons = self.wiki_base / "Knowledge" / "Comparisons"
        self.wiki_scenarios = self.wiki_base / "Knowledge" / "Scenarios"
        # W2-T2.1: 摘要锚点层 (Karpathy 覆盖层)
        self.wiki_summaries = self.wiki_base / "Summaries"
        self.wiki_queries = self.wiki_base / "Queries"

    def wiki_dir_for(self, page_type: str) -> Path:
        """按页面类型返回对应 WIKI 目录"""
        mapping = {
            "meeting": self.wiki_meetings,
            "person": self.wiki_persons,
            "organization": self.wiki_organizations,
            "concept": self.wiki_concepts,
            "judgment": self.wiki_judgments,
            "comparison": self.wiki_comparisons,
            "scenario": self.wiki_scenarios,
            "summary": self.wiki_summaries,
            "query": self.wiki_queries,
        }
        return mapping.get(page_type, self.wiki_base)

    def ensure_dirs(self) -> None:
        """创建所有必要目录"""
        targets = [
            self.data_raw, self.system_dir, self.wiki_base,
            self.wiki_meetings, self.wiki_persons, self.wiki_organizations,
            self.wiki_concepts, self.wiki_judgments, self.wiki_comparisons,
            self.wiki_scenarios, self.wiki_summaries, self.wiki_queries,
            self.registry_path.parent,
            self.processed_state.parent, self.logs_dir,
        ]
        for p in targets:
            p.mkdir(parents=True, exist_ok=True)


@dataclass
class LLMConfig:
    """LLM 调用配置(守主理人 MiniMax-M3 铁律)"""

    provider: str = "minimax"
    model: str = LLM_MODEL_MINIMAX
    max_tokens: int = LLM_MAX_TOKENS
    temperature: float = 0.3
    timeout: int = 60
    max_retries: int = 3
    base_url: str = "https://api.minimaxi.com/v1"  # .env.example 推荐值
    system_prompt: str = "你是一个专业的中文会议纪要分析师。"

    def __post_init__(self) -> None:
        env = os.environ.get
        if env("MINIMAX_CN_BASE_URL"):
            self.base_url = env("MINIMAX_CN_BASE_URL").rstrip("/")
        if env("PJ102_LLM_PROVIDER"):
            self.provider = env("PJ102_LLM_PROVIDER")
        if env("PJ102_LLM_MODEL"):
            self.model = env("PJ102_LLM_MODEL")


@dataclass
class StepConfig:
    """单步配置: excerpt 截断长度 + max_tokens(可 per-step 覆盖全局)"""

    name: str
    excerpt_length: int = 6000
    max_tokens: int = LLM_MAX_TOKENS
    uses_llm: bool = True


# 12+2 步默认配置(对齐 v3.0 各 step excerpt 实测值)
DEFAULT_STEPS: Dict[str, StepConfig] = {
    "s1": StepConfig("s1_basic", excerpt_length=10 ** 9, uses_llm=False),  # 全文
    "s2": StepConfig("s2_scene", excerpt_length=4000),
    "s3": StepConfig("s3_summary", excerpt_length=6000),
    "s4": StepConfig("s4_fjv", excerpt_length=8000),
    "s5": StepConfig("s5_implicit", excerpt_length=6000),
    "s6": StepConfig("s6_entity", excerpt_length=10000),
    "s7": StepConfig("s7_decision", excerpt_length=8000),
    "s8": StepConfig("s8_risk", excerpt_length=6000),
    "s9": StepConfig("s9_classify", excerpt_length=8000),
    "s10": StepConfig("s10_cognitive", excerpt_length=10000),
    "s11": StepConfig("s11_value", excerpt_length=4000),
    "s13": StepConfig("s13_financial", excerpt_length=8000),
    "s14": StepConfig("s14_scenario", excerpt_length=10000),
}


class AppConfig:
    """全局配置入口, 合并 yaml + 环境变量 + 默认值"""

    def __init__(self) -> None:
        self.paths = PathConfig()
        self.llm = LLMConfig()
        self.steps: Dict[str, StepConfig] = {k: StepConfig(**v.__dict__) for k, v in DEFAULT_STEPS.items()}
        self.sample_limit = DEFAULT_SAMPLE_LIMIT
        self.version = PROJECT_VERSION
        self._load_yaml()

    def _load_yaml(self) -> None:
        """加载 config/pipeline.yaml, 覆盖默认值"""
        try:
            import yaml
        except ImportError:
            return
        if not CONFIG_YAML.exists():
            return
        try:
            data = yaml.safe_load(CONFIG_YAML.read_text(encoding="utf-8")) or {}
        except Exception:
            return
        # sample_limit
        sl = data.get("sample_limit")
        if isinstance(sl, int) and sl > 0:
            self.sample_limit = sl
        # llm 覆盖
        llm_cfg = data.get("llm", {})
        if llm_cfg.get("model"):
            self.llm.model = llm_cfg["model"]
        if llm_cfg.get("temperature") is not None:
            self.llm.temperature = float(llm_cfg["temperature"])
        if llm_cfg.get("timeout"):
            self.llm.timeout = int(llm_cfg["timeout"])
        # step 覆盖(excerpt / max_tokens)
        steps_cfg = data.get("steps", {})
        if isinstance(steps_cfg, dict):
            for sid, sc in steps_cfg.items():
                if sid in self.steps and isinstance(sc, dict):
                    if sc.get("excerpt_length") is not None:
                        self.steps[sid].excerpt_length = int(sc["excerpt_length"])
                    if sc.get("max_tokens") is not None:
                        self.steps[sid].max_tokens = int(sc["max_tokens"])

    def excerpt(self, content: str, step_id: str) -> str:
        """按 step 配置截取内容(替代各 step 硬编码 content[:N])"""
        length = self.steps[step_id].excerpt_length if step_id in self.steps else 6000
        return content[:length] if length < len(content) else content
