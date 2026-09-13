"""PJ-102-LLM-MeetingKB core 层 — 配置 / schema / 日志

重构 v4.0 三大支柱:
  - 跨平台路径(PathConfig, 消灭 Linux 硬编码)
  - schema 驱动(compute_content_hash 统一 + TypedDict IO 定义, 杜绝字段名 bug)
  - 结构化日志(get_logger, 替代 print+emoji)

守引擎铁律: MiniMax-M3 / max_tokens=524288 / SAMPLE_LIMIT<=10 / 不引入向量库.
"""
from .config import AppConfig, PathConfig, LLMConfig, StepConfig, PROJECT_ROOT
from .schema import compute_content_hash, PipelineState, WIKI_LAYOUT
from .logging_setup import get_logger, setup_logging

__all__ = [
    "AppConfig", "PathConfig", "LLMConfig", "StepConfig", "PROJECT_ROOT",
    "compute_content_hash", "PipelineState", "WIKI_LAYOUT",
    "get_logger", "setup_logging",
]
