# PJ-102-02 · Karpathy LLM Wiki 详细设计说明书 v1.0

> 制定时间：2026-09-09 13:38
> 上游文档：`REQUIREMENTS_SPEC.md` v1.0（FR/NFR 编号引用）
> 下游文档：`ENGINEERING_PLAN.md` v1.0（任务分解）
> 设计原则：继承式增量设计——新模块独立成文件，存量模块只追加不改写

---

## 一、总体架构

（五层架构见总案 `KARPATHY_LLMWIKI_MASTER_PLAN.md` 第二章，本文档不重复，只做模块级展开）

核心数据流：

```
源.md ──> [s1-s14 既有管线,不改] ──> state ──> [s15 新增] ──> wiki/Summaries/
                │                                   │
                ├──> [集成层 修改] ──> s12 六类页 + 实体注册 + 引文 + 场景
                │                                   │
                └──> [后处理链 追加] ──> index_builder → fix_index_v2 → lint → dispute → log 追加
                
查询流: 用户问题 ──> kb_retriever 路由 ──┬─ L1 实体卡(entity_registry) <100ms
                                          └─ L2 LLM 读编译层综合 ──> 带引用答案 ──> [回流钩子] Queries/
```

## 二、数据设计

### 2.1 frontmatter schema v7.1（增量扩展，v7.0 全兼容）

新增 3 个可选字段（不填不报错，lint 只警告不阻断）：

```yaml
# 摘要页 (wiki/Summaries/)
---
type: summary                    # 新页面类型
source_file: "20260908_221948张三通话录音@...md"
source_date: 2026-09-08
file_type: type1_meeting
source_hash: 8b563d5e6e9f        # L0 回溯锚点（也是 step 缓存 key）
entities: ["[[张三]]", "[[主理人]]"]   # 实体 wikilink 列表
topics: [finance, product]       # Phase 4 三轴
meta_type: reference
---

# 全部存量页新增可选字段（Phase 4 回填）
topics: []      # Topic 轴,词表受控
meta_type: ""   # Meta 轴,词表受控
# Type 轴复用现有 type 字段，值域对齐 schema.org
```

### 2.2 taxonomy.yaml（Phase 4，三轴单点配置）

```yaml
version: 1
topic:            # Topic 主题域（自建受控词表，≤30 值）
  values: [ai, finance, industry, science, technology, product, methodology]
  rules: {max_count_per_page: 3, allow_free_text: false}
type:             # Type 实体类型（对齐 schema.org）
  values: [person, org, product, model, paper, tool]
  mapping: {meeting: reference, judgment: reference}  # 存量 type 到新轴的映射
meta:             # Meta 页面性质（对齐 Karpathy gist 页型，≤12 值）
  values: [comparison, timeline, controversy, prediction, tutorial, reference]
```

### 2.3 step 缓存扩展（FR-01）

- 新增 `system/cache/steps/{content_hash}/s15.json`，结构与既有 sN.json 一致：`{"status": "ok", "data": {...}, "ts": ...}`
- 读写走 pipeline.py 既有 `_cache_get/_cache_put`，零新机制

### 2.4 log.md 规范格式（FR-12）

```markdown
# 操作日志

## [2026-09-09] ingest | 0903 深圳培训
- 样本: 20260903_164036...md (hash 861abcc681db)
- 产出: 6类页 25 张, 摘要页 1 张, 触及存量实体页 12 张
- lint: PASS (死链0/YAML0/孤儿0)

## [2026-09-09] lint | 例行巡检
- 7维: PASS; 矛盾项: 0; Disputed: 0
```

### 2.5 index.md 条目格式（FR-12）

```markdown
- [[wiki/Summaries/摘要_2026-09-08_个人认知资产变现|摘要 2026-09-08 个人认知资产变现]]
  个人专家知识资产化平台讨论：AI 时代认知变现与数据资产私有化
```

## 三、模块详细设计

### 3.1 s15_summary_page.py（新建，~150 行）【FR-01/02】

```
位置: code/steps/s15_summary_page.py
输入: state（含 s3 五要素总结、s5 实体列表、样本元数据）
输出: wiki/Summaries/摘要_{date}_{主题}.md + step 缓存 s15.json
逻辑:
  1. 从 state 取 s3 summary（五要素）; 若 s3 缓存空 → 调用 LLM 补跑 s3
  2. 实体列表 → wikilink 化（查 entity_registry canonical_name）
  3. 渲染 jinja2 模板（模板落 config/templates/summary_page.md.j2）
  4. 文件名: 摘要_{source_date}_{标题前20字}.md（同名冲突加 (2)，沿用既有约定）
  5. 写缓存, 返回 {"pages": [path]}
存量回填: backfill_s15.py（新建,~80 行）——遍历 41 个 content_hash,
  读缓存 s15.json 存在则跳过, 否则从 s3.json 渲染（0 LLM）;
  s3 也空的样本（0903/0907 早期 2 个）标记后单独补跑
```

### 3.2 run_full.py 集成层修改（2 处）【FR-08/11/12】

```
改动点 A（根治 s12 缺陷, ~15 行）:
  现状: 集成层只写 场景/引文/实体注册
  修改: 在实体注册完成后, 构造 state 调 s12_write_wiki(state)
  注意: s12 生成页带 hash 后缀 → 集成层后追加 polish 等价逻辑
       （中文命名+实体链接,复用 system/tmp/polish_0903_0907.py 的函数,提升为 code/polish_pages.py）

改动点 B（后处理链追加, ~10 行）:
  现状: index_builder → fix_index_v2
  追加: lint_wiki.run_lint(report=True)
       dispute_detector.run_detect()
       _append_log(operation, details)   # 按 2.4 格式追加 log.md
```

### 3.3 CLAUDE.md 契约（新建，~200 行）【FR-05】

```
位置: 项目根 CLAUDE.md
结构:
  §1 项目宪法: 模型 MiniMax-M3 / 零向量库 / 存量零推翻 / verify 最后防线
  §2 目录地图: wiki/ 九类目录用途 + index/log 入口
  §3 页面模板: 9 类（6 存有+3 新增）frontmatter 必填字段与命名规范
  §4 工作流:
     W1 摄入: 跑批铁律命令 → 查 s12 六类页落盘 → 查摘要页 → lint → fix_index_v2 → verify → log
     W2 查询: 路由判断（实体精确→L1 卡; 综合→L2）→ 引用≥2 建议回流
     W3 巡检: lint + dispute → Disputed 项列报告待人工裁决
     W4 统计: stats 输出页面/实体/健康分
  §5 血泪陷阱（必守）:
     T1 沙箱跑批: 前台 Bash+管道 stdout+timeout 570, 禁后台/禁重定向
     T2 后处理必跑 fix_index_v2（index_builder 覆盖陷阱）
     T3 人物同日同名: 按 hash 分组映射, 禁直接覆盖
     T4 判断页 title 英文双引号→全角
     T5 日期字段统一 str()（sort 崩溃教训）
  §6 触发词表: 摄入/查询/lint/摘要/回流/统计
```

### 3.4 kb_retriever 扩展（增量函数，~100 行）【FR-04/06/13】

```
位置: code/kb_retriever.py（只追加,不改既有函数）
+ def query_rewrite(q) -> list[str]        # Phase 5: 规则式改写（实体替换式/时间限定式/角度转换式, 各1条）
+ def answer_with_citations(q) -> dict     # Phase 5: 答案+编号引用 [{ref:"[[页名]]", anchor:"L0:文件:行"}]
+ def suggest_archive(answer) -> dict      # Phase 2: 引用≥2 → {should: true, target: "Queries/Q_...md"}
+ BM25 索引: code/kb_bm25.py（新建 ~80 行, jieba 分词+倒排,启动时构建<3s,内存常驻）
```

### 3.5 kb_mcp_server.py（新建，~120 行）【FR-09】

```
框架: FastMCP (stdio)
工具:
  query(q: str) -> str      # kb_retriever 路由: L1 实体卡 JSON 或 L2 综合文本(带引用)
  lint() -> str             # lint_wiki 报告 JSON
  stats() -> str            # {pages: {meeting: N, person: N, ...}, entities: N, health_score: x}
注册: ~/.workbuddy/mcp.json 增条目 pj102-kb（env: PYTHONIOENCODING=utf-8）
部署: 用户在连接器管理手动信任（agent 不可代点）
```

### 3.6 Schema 回填与 lint 扩展【FR-10】

```
backfill_tags.py（新建 ~100 行）:
  遍历 443 存量页 → frontmatter + 正文首段 → 调 LLM 打标（批量 20 页/次, ~66 万 tokens）
  → 写 topics/meta_type 字段 → 幂等（已有标签跳过）
lint_wiki 扩展（+30 行）:
  新检查项: 孤儿标签（词表外值报警）/ 标签缺失率（>20% 警告）
s5-s9 提示词修改（+各~10 行）:
  输出约束追加: "topics 从 {词表} 选择, 最多 3 个, 严禁杜撰词表外值" + 2 个 few-shot
```

### 3.7 daily_incremental 实测方案【FR-14】

```
步骤: 投 1 个测试样本 → 调 daily_incremental.run() → 检查是否走完 扫新→pipeline→lint
判定: 全通过 → CLAUDE.md W1 主入口= daily_incremental, run_full=兜底
     任一环节失败 → 双入口并存均为 run_full 调用族, daily_incremental 标记待修
```

## 四、目录结构终态

```
张三合伙项目/
├── CLAUDE.md                        ★新增 P1（契约）
├── code/
│   ├── steps/s15_summary_page.py    ★新增 P2
│   ├── polish_pages.py              ★新增 P3（从 system/tmp 提升）
│   ├── kb_bm25.py                   ★新增 P2
│   ├── kb_retriever.py              ◆追加 P2/P5
│   ├── kb_mcp_server.py             ★新增 P3
│   ├── lint_wiki.py                 ◆追加 P4
│   └── （其余全部不动）
├── scripts/
│   ├── run_full.py                  ◆修改 2 处 P0/P3
│   └── backfill_s15.py / backfill_tags.py  ★新增 P2/P4
├── config/
│   ├── taxonomy.yaml                ★新增 P4
│   └── templates/summary_page.md.j2 ★新增 P2
├── wiki/
│   ├── Summaries/                   ★新增 P2（41 页）
│   ├── Queries/                     ★新增 P2（随使用增长）
│   ├── Synthesis/                   ★预留 P2+（Phase 2 只建目录）
│   ├── log.md                       ◆重置 P0（旧→log.legacy.v4.md）
│   ├── index.md                     ◆增强 P1
│   └── （既有 6 类目录全部不动）
└── system/（state/cache/logs 全部不动）
```

图例：★新增 / ◆增量修改 / 无标注=继承不动

## 五、接口设计（对外 MCP 三工具 JSON）

```json
// query 响应
{"route": "L1", "entity_card": {"canonical_name": "主理人", "meetings": [...], "value_grade_A": 3}, "elapsed_ms": 42}
{"route": "L2", "answer": "...", "citations": [{"ref": "[[张三]]", "anchor": "Summaries/摘要_2026-09-08"}, ...]}

// lint 响应
{"dead_links": 0, "yaml_errors": 0, "orphans": [], "disputed": [], "tag_compliance": 0.97, "health_score": 98}

// stats 响应
{"pages": {"meeting": 14, "person": 86, "org": 61, "concept": 111, "judgment": 48, "scenario": 101, "summary": 41}, "entities": 473, "queries_archived": 12}
```

## 六、错误处理与回退设计

| 故障场景 | 处理 |
|---|---|
| s15 LLM 调用失败 | step 缓存重试机制（既有 --retries），失败样本标 PENDING 不阻断其他 |
| 集成层 s12 调用异常 | try/except 包裹，失败降级为旧行为（只写场景）+ log 记录，保留 backfill_s12 应急 |
| daily_incremental 失修 | 双入口兜底（3.7） |
| MCP server 崩溃 | 独立进程不影响主库；WorkBuddy 契约路由仍可用 |
| Schema 回填中断 | backfill_tags 幂等，重跑续填 |
| 任一 Phase 整体失败 | 独立回退：改动全部是"新增文件+追加调用"，删除即回退；改 run_full 前快照 wiki/ |
