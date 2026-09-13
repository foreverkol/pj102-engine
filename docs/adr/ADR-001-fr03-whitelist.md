# ADR-001 · FR-03 需求修订：页面零丢失改为「内容零丢失 + 删页白名单制」

> 状态：已接受（Accepted） · 日期：2026-09-10 · 关联：REQUIREMENTS_SPEC FR-03 / PROJECT_REVIEW_V2_ROADMAP 偏离项 D1

## 背景

FR-03 原文要求"页面数只增不减"。实际执行中 W2→W4 页面 505→472（净减 33）、P2 实体归一 590→552（净减 38），全部删除均为冗余分片/副本页，内容已并入聚合页，零信息丢失。字面条款与工程现实冲突。

## 决策

FR-03 验收语义修订为：

1. **内容零丢失**（原有意图，不变）：任何删除动作前，被删页内容必须已并入目标页或已入备份；
2. **删页白名单制**：物理删除仅允许两类——① polish_pages 冗余分片收敛（(type,hash) 冗余判定）② 归一合并中被并入规范页的旧版本页（merge_entities / merge_concepts / backfill 类）；
3. **全量登记**：每批删除落 `system/state/*_merge.json` / manifest / log.md 三处可审计；
4. **规模断言**（G2）同步修订：页面数允许因归一净减，但"index 收录 = wiki 物理 - 登记白名单"必须成立。

## 影响

- REQUIREMENTS_SPEC FR-03 验收行以本 ADR 为准（v1.1 changelog 引用）；
- 守护协议 G5"只允许两类写操作"与本 ADR 语义对齐；
- 所有删页脚本必须输出登记文件，否则视为违规操作。

## 关联证据

ROADMAP D1 偏离分析、P2_MILESTONE_REPORT §五（590→552 实测对账）、P0_MILESTONE_REPORT（4 样本 93 页无删除）。
