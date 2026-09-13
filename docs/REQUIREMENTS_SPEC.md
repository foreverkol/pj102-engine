# PJ-102-02 · Karpathy LLM Wiki 工程需求规格说明书 v1.0

> 制定时间：2026-09-09 13:35
> 上游文档：`KARPATHY_LLMWIKI_MASTER_PLAN.md`（v4.0 总案）
> 下游文档：`DETAILED_DESIGN.md`（详细设计）、`ENGINEERING_PLAN.md`（工程计划）
> 状态：定稿，作为设计/计划/验收的需求基线
> 编号规则：FR-功能需求 / NFR-非功能需求 / OOS-范围外；全部编号可追踪至工程计划任务

---

## 一、项目背景与目标

### 1.1 背景

本项目已建成一套 13 步 LLM 编译管线，将 41 个录音转写（源 .md）编译为 443 页结构化 wiki（6 类页面 + v7.0 frontmatter + entity_registry 473 实体 + step 缓存断点续跑）。核查证实项目完成度约 85%，但存在**能力孤岛**（检索/巡检/矛盾检测/增量调度四模块已建成未接线）与**集成缺陷**（driver 不调 s12，6 类页需人工 backfill）。

### 1.2 总体目标（一句话）

在**零推翻继承**存量资产的前提下，按 Karpathy LLM Wiki 方法论（写时计算、零向量库）把项目升级为**活的编译知识库**：达成"答案在编译里——遍历编译即遍历所有答案"。

### 1.3 用户角色

| 角色 | 描述 | 核心诉求 |
|---|---|---|
| U1 知识库主人（主理人） | 唯一运维者与主要使用者 | 一句话操作、可信答案、可溯原文 |
| U2 WorkBuddy Agent | 契约执行者 | 读 CLAUDE.md 自主编排 ingest/query/lint |
| U3 外部 Agent（hermes 等） | 经 MCP 接入的消费方 | 标准工具调用查询/巡检/统计 |
| U4 未来的复制者（朋友） | 拿能力框架自建库 | 可移植、零硬编码新增 |

## 二、功能需求（FR）

### FR-01 编译管线继承与扩展 【Phase 2】

- s1-s14 十三步管线**一行不改**，仅在尾部追加 **s15 摘要页生成步骤**
- s15 输出落盘 `wiki/Summaries/`，同时写 step 缓存 `s15.json`（断点续跑）
- 验收：新样本跑批自动产出摘要页；中断重跑不重复调用 LLM

### FR-02 摘要锚点层 【Phase 2】

- 每个源文件（41 个）生成一张摘要页：300-500 字五要素总结 + 源元数据（source_file/source_date/file_type/source_hash）+ 出现实体 wikilink + L0 回溯锚点
- 存量回填优先从 step 缓存 s3 渲染（近零 LLM 费用）；缓存为空的早期样本补跑
- 验收：41/41 源有摘要页；抽查 5 张实体链接可跳转、源锚点可回溯

### FR-03 存量资产零推翻继承 【全程约束】

- 443 页 wiki、v7.0 frontmatter、entity_registry、step 缓存：零重写、零迁移、零改名
- 唯一例外：log.md 旧内容归档为 `log.legacy.v4.md` 后重置（旧内容为已失效统计）
- 验收：每个 Phase 结束 verify.py 死链 0 / YAML 0 错误，页面数只增不减

### FR-04 统一检索（双层查询） 【Phase 0/3】

- L1 实体卡：毫秒级精确查询（"主理人参与哪些 A 级会议"）
- L2 LLM 综合：读已编译 wiki 生成带真实引用的答案，资料不足保守回答
- 全程 BM25 + wikilink + 实体卡路由，**禁用向量检索**（见 NFR-04）
- 验收：两类典型问题分别命中 L1/L2 正确路径

### FR-05 契约驱动操作（CLAUDE.md） 【Phase 1】

- 新建项目根 `CLAUDE.md`（~200 行）：9 类页面模板 + 工作流→CLI 映射 + 血泪陷阱清单 + 触发词表
- 支持自然语言触发："摄入 xx.md" / "查询 X" / "lint 巡检" / "统计"
- 血泪陷阱必须包含：沙箱跑批铁律（前台+管道 stdout+timeout 570）、后处理必跑 fix_index_v2、s12 六类页落盘检查、同日同名人物 hash 分组、判断页 title 全角引号
- 验收：人工监督下 agent 按契约完成 2 个样本的完整摄入流程，零漏步

### FR-06 问答回流 【Phase 2】

- L2 综合答案引用 ≥2 个 wiki 页时，建议归档为 `wiki/Queries/Q_主题_日期.md`
- 防膨胀双闸门：引用数阈值 + agent 价值判断（流水账不存）
- 验收：一次综合问答产出 1 张合规 Query 页

### FR-07 增量更新存量实体页 【Phase 3】

- 新文件摄入时，由 s5 实体识别结果驱动，自动更新被触及的存量实体页（"出现会议/关联判断/其他出现记录"小节），预期触及 10-15 页
- 验收：新样本摄入后，其涉及的既有实体页自动新增本次出现记录，零人工编辑

### FR-08 driver 集成层缺陷修复 【Phase 3】

- run_full.py 集成层补调 s12 六类页生成器，**根治**"只有场景有内容"问题
- 废弃 backfill_s12.py 人工步骤（保留脚本作应急工具）
- 验收：新样本跑批后 6 类页自动落盘，无需任何收尾脚本

### FR-09 MCP 服务化 【Phase 3】

- FastMCP server 暴露三工具：`query(q)` / `lint()` / `stats()`
- 注册 `~/.workbuddy/mcp.json`；用户手动信任后 WorkBuddy 可直接调用
- 验收：三工具调用成功返回结构化结果

### FR-10 Schema 三轴标签 【Phase 4】

- 三轴受控词表单点配置 `config/taxonomy.yaml`：
  - Topic 主题域（自建：ai/finance/industry/science/technology/product/methodology 起步）
  - Type 实体类型（对齐 schema.org：person/org/product/model/paper/tool）
  - Meta 页面性质（对齐 Karpathy gist：comparison/timeline/controversy/prediction/tutorial/reference）
- s5-s9 提示词追加受控词表输出约束 + few-shot + 严禁杜撰
- 存量 443 页回填打标
- 验收：可按 `topic × meta` 组合筛选；lint 报告含词表合规率

### FR-11 质量巡检自动化 【Phase 0】

- lint_wiki（7 维：孤儿页/死链/缺 source_ref/矛盾待审/过时/未索引/必填字段）+ dispute_detector（同主题对立立场）接入 run_full 后处理链
- 验收：跑批即巡检，报告自动产出，死链/YAML 保持 0 错误

### FR-12 操作日志与索引导航 【Phase 0/1】

- log.md 重置为可 grep 规范格式：`## [YYYY-MM-DD] 操作 | 标题`，每次跑批/摄入/巡检自动追加
- index.md 每条目加一行摘要；新增 Summaries/Queries/Synthesis 分区
- 验收：`grep "摄入" wiki/log.md` 能列出全部摄入历史

### FR-13 检索增强（可选） 【Phase 5】

- L2 层 Query Rewrite（复杂问题多角度改写后检索）
- 答案行内引用 chip（[1][2] 指向具体 wiki 页/锚点）
- 验收：综合问题答案带编号引用，可定位到页

### FR-14 增量调度入口 【Phase 0】

- 实测 daily_incremental.py：可用则登记为日常入口；失修则契约中双入口并存（run_full 兜底）
- 验收：两种入口至少一种全自动跑通

## 三、非功能需求（NFR）

| # | 需求 | 指标 |
|---|---|---|
| NFR-01 | 查询性能 | L1 实体查询 <100ms；L2 综合 <30s（单次） |
| NFR-02 | 总成本 | 全部 Phase LLM 费用 <14 元；不新增付费组件 |
| NFR-03 | 可靠性 | 断点续跑（step 缓存扩展至 s15）；每 Phase 独立回退，零存量数据丢失 |
| NFR-04 | 范式约束 | **零向量库、零 embedding 检索、零 RAG 重排**（卡帕西写时计算铁律） |
| NFR-05 | 可移植性 | 新代码零新增硬编码绝对路径（相对项目根）；GitHub 分发预留 |
| NFR-06 | 安全 | API key 不入 git/wiki；敏感内容不入编译层 |
| NFR-07 | 可维护性 | 契约与代码同步（改行为先改 CLAUDE.md）；lint 守门 |
| NFR-08 | 兼容性 | Obsidian 双链/图谱/反链面板全程可用；v7.0 schema 校验照常生效 |

## 四、范围外（OOS，明确不做）

| # | 不做的事 | 理由 |
|---|---|---|
| OOS-1 | 向量库 / embedding 检索 / chromadb | 违背卡帕西写时计算范式（v1.0 方案已废弃的教训） |
| OOS-2 | 重写/迁移 443 页存量 | 零推翻继承铁律 |
| OOS-3 | 多模态接入（音频/PDF 直读） | NotebookLM 对标分析确认非本项目短板优先级 |
| OOS-4 | chunk→page 800 页自由层 | v2.0 教训：非卡帕西原做法，降级为远期实验 |
| OOS-5 | GitHub 发布 / 朋友分发 | 独立线索（已有 GITHUB_RELEASE_PLAN.md），不阻塞本工程 |

## 五、需求-Phase 追踪矩阵

| Phase | 覆盖需求 |
|---|---|
| 0 接线（0.5 天） | FR-04（部分）、FR-11、FR-12（log）、FR-14 |
| 1 契约（1 天） | FR-05、FR-12（index） |
| 2 摘要+回流（1.5 天） | FR-01、FR-02、FR-06 |
| 3 增量+MCP（2 天） | FR-07、FR-08、FR-09、FR-04（完全体） |
| 4 Schema（2.5 天） | FR-10 |
| 5 检索增强（可选 1.5 天） | FR-13 |
| 全程约束 | FR-03、NFR-01~08 |

## 六、验收总门（终态 DoD）

全部 Phase 完成后，满足以下 5 项即整体验收通过：

1. **一句话操作**：对 agent 说"摄入新文件"，全自动落盘 6 类页 + 摘要页 + 实体页更新 + lint 零错误，零人工收尾
2. **四层齐备**：覆盖（41 摘要页）× 密度（443+ 结构页）× 新鲜（增量更新）× 遍历（检索+导航）全部通电
3. **零回归**：verify.py 死链 0 / YAML 0 错误 / 存量 443 页零丢失
4. **双 agent 可用**：WorkBuddy 契约驱动 + MCP 三工具
5. **成本达标**：累计 LLM 费用 <14 元

---

## 变更日志（Doc Sync Protocol · 见 ADR 与 MASTER_ITERATION_PLAN）

### v1.1（2026-09-10，基线 v1.3.0-p2-milestone）

本节为 v1.0 定稿后的结构性修订登记，正文不回改，**以本节 + ADR 为准**：

| 条目 | 修订 | 依据 |
|---|---|---|
| FR-03 | 「页面数只增不减」修订为「内容零丢失 + 删页白名单制」 | [ADR-001](adr/ADR-001-fr03-whitelist.md)（ROADMAP 偏离 D1 正式化） |
| 实体命名 | 新增实体规范名约定：无日期主页 + 时间线聚合 + 人工消歧保留；`source_meetings` 列表为合法字段 | [ADR-002](adr/ADR-002-entity-canonical-naming.md)（P2 攻坚结论） |
| 摄入类型 | 明确 L0 文本契约不变 + 预处理层扩展原则 + `file_class` 分型（T1/T2/T3） | [ADR-003](adr/ADR-003-l0-text-contract.md) |
| lint 必填口径 | FR-11 巡检维度演进：v7.0 理想字段降为 LINT_STRICT 可选，必填按 s12 实际产出分型（维度扩至 11） | P1/P2 里程碑报告 |
| 二期路线 | 原 ROADMAP §五 P2（检索体验）平移为 MASTER_ITERATION_PLAN P5；P0/P1 已于 2026-09-09/10 执行完毕（v1.1.0/v1.2.0） | MASTER_ITERATION_PLAN |
| 批量摄入 | 新增稳定性 SLA（S1–S6）与三道防线，属 FR-08/FR-14 的工程化深化 | EXECUTION_PLAN_P3P4 §四 |

> 适用基线 ≥ v1.3.0；后续里程碑按 Doc Sync Protocol（守护协议 G2 第五断言）在本节追加登记。

### v1.2（2026-09-10，基线 v1.5.0-p4-milestone）

| 条目 | 修订 | 依据 |
|---|---|---|
| 摄入复检 | `processed_files.json` 中 `status≠ok` 的墓碑条目不再视为已处理——校验/分型规则升级后被误杀文件可重新入队（FR-14 断点续跑语义修正） | P4 T-P4.7（0902 chat 实战发现） |
| 命名变体 | L0 文本契约的文件名日期-标题分隔符扩展认可 `-`（如 `20260902_2109-标题.md`），s1 标题提取剥前导分隔符与 `.md` 后缀 | P4 T-P4.8 根因修复（ADR-003 §五 预处理层扩展原则的落地） |
| 摄入类型验收 | `file_class=chat` 首个真样本（千问智能体对话导出）端到端跑通：44 页产出、十一维全绿——T2 分型从工程验证升为实战验证 | P4_MILESTONE_REPORT §二 |

> 遗留决策项：D-3（25 个 ok 源文件无会议页，v4 重构期范围遗留，是否回补待用户裁决）。

### v1.3（2026-09-10，基线 v1.6.0-p5-milestone）

| 条目 | 修订 | 依据 |
|---|---|---|
| 检索四维 | FR 检索体验扩展：tag_query 支持 `--date-range`（时间窗）与 `--source-meeting`（来源会议）第四维组合查询；有效日期按页型分字段口径（date/source_date/query_date/source_dates） | P5 T-P5.2 |
| 问答回流 | Queries 页归档驱动（archive_query.py）落地：引用 ≥2 双闸门 + agent 价值确认；Queries 页 graph_orphans 豁免（与 Summaries 同口径） | P5 T-P5.3 |
| 质量口径 | lint 升为十二维：维度 1 更名 graph_orphans（遍历断点）+ 新增维度 12 content_orphans（密度缺口），D7 口径分歧消解 | P5 T-P5.4 |
| 链接规范 | write_query_page wikilink 目标剥 .md 后缀（库内约定），存量 30 处修正 | P5 T-P5.3 校准发现 |
| 检索词表 | SYNTHESIS_KEYWORDS 增补 8 词（演进/过程/历程/决策标准/发展等）；词表法覆盖率 60% 实证，P6 query_rewrite 必要性确认 | P5 T-P5.3 校准发现 |

> 决策记录：D-3 已裁决（2026-09-10，用户）——不回补 25 个历史源会议页，wiki 以 18 源主干继续增量。

### v1.4（2026-09-10，基线 v2.0.0-terminal）

| 条目 | 修订 | 依据 |
|---|---|---|
| FR-13 检索增强 | **落地完成**：query_rewrite 三改写（LLM+确定性兜底）+ 行内编号引用（[n] 越界钳制 + 尾部 wikilink 映射）+ 复合意图启发（L1 误中率 40%→0）；citations 扩召回 5-8→18 | P6 T-P6.1 |
| 检索路由 | SYNTHESIS_KEYWORDS 移除"是谁/是什么"（L1 实体卡片本职查询归位） | P6 T-P6.1 |
| A/B 评测 | B 侧 10 题实测全过（路由 10/10 / 可定位 44 / 越界 0 / 0.041 元）；A 侧 NotebookLM 认证阻塞待补测 | P6 T-P6.2 + EVAL_NOTEBOOKLM_AB.md |
| 终态判定 | DoD 五项复验全过，项目转入纯运维节奏（MASTER_ITERATION_PLAN §八） | P6 T-P6.3 |

> 终态锚点：v2.0.0-terminal。累计成本 3.937/14 元。
