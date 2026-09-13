"""PJ-102 core 日志层 — 结构化 logging, 替代 print + emoji

修复的历史问题:
  - 全代码用 print + emoji(✅❌⚠️📋), 生产日志不可解析
  - 无日志级别, 无结构化字段, 无日志文件

设计:
  - 标准 logging 模块, JSON 格式化(可选), 文件 + 控制台双输出
  - 关键字段: timestamp / level / step / sample / event / message
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Optional

_LOGGER_NAME = "pj102"
_INITIALIZED = False


class PJ102Formatter(logging.Formatter):
    """简洁单行格式: [时间] 级别 [step/sample] 消息"""

    def format(self, record: logging.LogRecord) -> str:
        # 注入 step/sample 字段(若有)
        ctx = []
        if hasattr(record, "step") and record.step:
            ctx.append(f"step={record.step}")
        if hasattr(record, "sample") and record.sample:
            ctx.append(f"sample={record.sample}")
        ctx_str = f" [{', '.join(ctx)}]" if ctx else ""
        # 时间只取到秒
        ts = self.formatTime(record, "%Y-%m-%d %H:%M:%S")
        return f"[{ts}] {record.levelname:5s}{ctx_str} {record.getMessage()}"


class StructuredLogger:
    """支持 step=/sample= 关键字参数的日志包装器

    用法: logger.info("消息", step="s3", sample="meeting_001.md")
    底层将 step/sample 注入 LogRecord.extra, 由 PJ102Formatter 格式化输出
    """

    def __init__(self, logger: logging.Logger):
        self._logger = logger

    def _emit(self, level: int, msg: str, **kwargs):
        extra = {}
        if "step" in kwargs:
            extra["step"] = kwargs.pop("step")
        if "sample" in kwargs:
            extra["sample"] = kwargs.pop("sample")
        self._logger.log(level, msg, extra=extra, **kwargs)

    def info(self, msg, **kwargs):
        self._emit(logging.INFO, msg, **kwargs)

    def warning(self, msg, **kwargs):
        self._emit(logging.WARNING, msg, **kwargs)

    def error(self, msg, **kwargs):
        self._emit(logging.ERROR, msg, **kwargs)

    def debug(self, msg, **kwargs):
        self._emit(logging.DEBUG, msg, **kwargs)

    def setLevel(self, level):
        self._logger.setLevel(level)

    @property
    def handlers(self):
        return self._logger.handlers


def setup_logging(logs_dir: Optional[Path] = None, level: int = logging.INFO) -> StructuredLogger:
    """初始化全局日志(文件 + 控制台). 幂等. 返回 StructuredLogger."""
    global _INITIALIZED
    logger = logging.getLogger(_LOGGER_NAME)
    if _INITIALIZED:
        return StructuredLogger(logger)
    logger.setLevel(level)
    logger.propagate = False
    fmt = PJ102Formatter()

    # 控制台
    sh = logging.StreamHandler(sys.stderr)
    sh.setFormatter(fmt)
    logger.addHandler(sh)

    # 文件(若提供 logs_dir)
    if logs_dir is not None:
        logs_dir = Path(logs_dir)
        logs_dir.mkdir(parents=True, exist_ok=True)
        # 主日志
        fh = logging.FileHandler(logs_dir / "pipeline.log", encoding="utf-8")
        fh.setFormatter(fmt)
        logger.addHandler(fh)
        # 错误日志
        eh = logging.FileHandler(logs_dir / "error.log", encoding="utf-8")
        eh.setLevel(logging.WARNING)
        eh.setFormatter(fmt)
        logger.addHandler(eh)

    _INITIALIZED = True
    return StructuredLogger(logger)


def get_logger(name: str = _LOGGER_NAME) -> StructuredLogger:
    """获取 StructuredLogger(支持 step=/sample= 参数)"""
    logger = logging.getLogger(name)
    if not logger.handlers:
        logger = setup_logging()._logger
    return StructuredLogger(logging.getLogger(name))


class LoggerAdapter(logging.LoggerAdapter):
    """附加 step/sample 上下文的适配器"""

    def __init__(self, logger: logging.Logger, step: str = "", sample: str = ""):
        super().__init__(logger, {"step": step, "sample": sample})

    def process(self, msg, kwargs):
        self.extra["step"] = kwargs.pop("step", self.extra.get("step", ""))
        self.extra["sample"] = kwargs.pop("sample", self.extra.get("sample", ""))
        return msg, kwargs
