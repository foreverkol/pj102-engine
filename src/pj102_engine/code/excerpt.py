# -*- coding: utf-8 -*-
"""LLM 输入截断的**单一入口**（2026-09-16）

为什么必须集中
--------------
原先 12 个 LLM 步骤各自硬编码 `content[:N]`（4000~10000 不等），且**都不告知
模型「末尾已省略」**。后果（实证）：
  · 长会议（43 份源稿中位 25664 字）的中后段被系统性丢弃；
  · 模型对着残缺上下文要么臆测，要么弃答 → 落盘空骨架 → 被软熔断判为"无产出"，
    在体检里表现为 C1/C2 长期不清零（第二轮补跑实测 s7 返回 8180 字却全字段空）。
s3 曾单独修过（6000→20000 + 显式告知），但**没有推广**——本模块即推广后的统一入口。

约定
----
· `excerpt_for_llm(content, default)` 返回 `(excerpt, limit)`；
  超限时把「原文共 X 字 / 末尾 Y 字未提供 / 不要臆测」**直接拼进 excerpt**，
  故调用方提示词里的 `{excerpt}` 自动带上该告知，无需改提示词结构。
· 环境变量 `PJ102_EXCERPT_LIMIT` 提供**统一下限**：实际上限 = max(default, 该值)。
  全量重跑前建议 `PJ102_EXCERPT_LIMIT=20000`（见项目 MEMORY.md 时序铁律：
  **先修引擎 + registry，再重跑**）。
"""
from __future__ import annotations

import os

ENV_LIMIT = "PJ102_EXCERPT_LIMIT"

TAIL_NOTICE = (
    "\n\n⚠ 注意: 原文共 {total} 字, 此处仅含前 {limit} 字, "
    "末尾 {missing} 字**未提供** —— 不要臆测未提供部分的内容."
)


def excerpt_limit(default: int) -> int:
    """实际截断上限 = max(default, $PJ102_EXCERPT_LIMIT)"""
    raw = os.environ.get(ENV_LIMIT, "").strip()
    if not raw:
        return int(default)
    try:
        v = int(raw)
    except ValueError:
        return int(default)
    return max(int(default), v) if v > 0 else int(default)


def excerpt_for_llm(content: str, default: int):
    """返回 (excerpt, limit)。超限时 excerpt 末尾自带「未提供」告知。"""
    content = content or ""
    limit = excerpt_limit(default)
    if len(content) <= limit:
        return content, limit
    tail = TAIL_NOTICE.format(total=len(content), limit=limit,
                              missing=len(content) - limit)
    return content[:limit] + tail, limit
