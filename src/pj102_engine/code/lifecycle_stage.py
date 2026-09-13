"""
v7.0 FR-v7.0-005 status_stage 5 阶段状态机 + §8.4 版本规则

5 阶段合法跃迁:
  raw       → compiled
  compiled  → reviewed | superseded
  reviewed  → canonical | superseded
  canonical → superseded
  superseded → 终结态(无跃迁)

§8.4 版本规则:
  - Update 时 version 递增
  - 旧版本追加到 previous_versions 栈
  - previous_versions 记录 superseded_at + by_source
"""

from enum import Enum
from datetime import datetime, timezone
from typing import Optional


class Stage(Enum):
    """v7.0 §一 status_stage 5 阶段"""
    RAW = "raw"
    COMPILED = "compiled"
    REVIEWED = "reviewed"
    CANONICAL = "canonical"
    SUPERSEDED = "superseded"


# 合法跃迁表
TRANSITIONS = {
    Stage.RAW: {Stage.COMPILED},
    Stage.COMPILED: {Stage.REVIEWED, Stage.SUPERSEDED},
    Stage.REVIEWED: {Stage.CANONICAL, Stage.SUPERSEDED},
    Stage.CANONICAL: {Stage.SUPERSEDED},
    Stage.SUPERSEDED: set(),   # 终结态
}


def transition_validation(current: Stage, target: Stage) -> bool:
    """§ v7.0 一 验证状态跃迁是否合法"""
    if not isinstance(current, Stage) or not isinstance(target, Stage):
        return False
    return target in TRANSITIONS.get(current, set())


def transition_safe(current: Stage, target: Stage) -> Stage:
    """安全跃迁,非法时抛异常"""
    if not transition_validation(current, target):
        raise ValueError(f"illegal transition: {current.value} -> {target.value}")
    return target


def update_with_version(frontmatter: dict, source_ref: str) -> dict:
    """v7.0 §8.4 版本规则:Update 时 version+1,旧版本入栈"""
    current_version = frontmatter.get("version", 1)

    # 记录旧版本
    log_entry = {
        "version": current_version,
        "superseded_at": _now_iso(),
        "by_source": source_ref,
    }
    previous_versions = frontmatter.get("previous_versions", [])
    previous_versions.append(log_entry)

    frontmatter["version"] = current_version + 1
    frontmatter["updated"] = _today_iso()
    frontmatter["previous_versions"] = previous_versions
    return frontmatter


def init_frontmatter(
    type_: str,
    date: str,
    title: str,
    source_ref: str,
    extra: dict = None,
) -> dict:
    """新建页面 frontmatter 默认值"""
    fm = {
        "type": type_,
        "date": date,
        "title": title,
        "source_origin": "transcript",
        "source_ref": source_ref,
        "content_hash": "",            # 由 pipeline 写入
        "generated_at": _today_iso(),
        "generator": "pj102-llm-meetingkb-v3.0",
        # v7.0 §8.1 必填
        "status_stage": Stage.COMPILED.value,
        "version": 1,
        "previous_versions": [],
        # v7.0 §三 价值
        "value_grade": "A",
        "sensitivity": "internal",
        "confidence": "extracted",
    }
    if extra:
        fm.update(extra)
    return fm


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _today_iso() -> str:
    return datetime.now(timezone.utc).date().isoformat()
