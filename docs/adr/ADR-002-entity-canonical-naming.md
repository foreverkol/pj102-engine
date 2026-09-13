# ADR-002 · 实体规范名约定：无日期规范主页 + 时间线聚合 + 人工消歧保留

> 状态：已接受（Accepted） · 日期：2026-09-10 · 关联：P2_MILESTONE_REPORT / lint 维度 11 / polish_pages v1.3

## 背景

P2 前实体页以「姓名（来源会议日期）」命名（polish L152 防冲突拼日期），导致同一人物多页分片（主理人×9 等 11 组），不符合"人物是跨时间单一实体"的现实。P2 已完成存量归一（42→11 页）并修正生成端机制。

## 决策（作为全库实体命名与合并的唯一约定）

1. **规范名**：Persons/Organizations 页一律无日期后缀（`主理人.md`），冲突用语义消歧后缀（`李四（万联网）.md`），禁止日期防冲突；
2. **时间线聚合**：同一实体多次出现聚合为规范页内「📅 出现会议 → 🎯 活动」时间线小节，frontmatter 用 `source_meetings` 列表；
3. **同名不同人**：role/org 冲突的疑似重名**不自动合并**——保留双页 + aliases 消歧注记，进人工审查队列（典型情形：称呼与全名并存、跨名同指、同音不同人）；
4. **增量防回归**：polish_pages v1.3 对同名新页执行 MERGE 分支（幂等守卫），lint 维度 11 `entity_fragments` 检测复发。

## 影响

- 实体页 schema：新增 `source_meetings`（复数列表）为合法字段，`source_meeting`（单数）保留为主来源；
- lint REQUIRED_FIELDS person/org 分型按本约定校验；
- 未来任何实体页生成/合并脚本必须遵守本约定，冲突即 ADR 升级。

## 关联证据

P2_MILESTONE_REPORT §三（消歧审查）、`scripts/merge_entities.py`、`code/polish_pages.py` L152 修正段、`code/lint_wiki.py` 维度 11。
