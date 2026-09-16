# Changelog

本项目的所有重要变更记录在此。格式参照 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，
版本号遵循 [SemVer](https://semver.org/lang/zh-CN/)。

## [2.3.0] - 2026-09-16

实体图谱能力上游版：**4 个引擎级新模块 + 3 处接线 + 标尺 15 维**。
把实例侧 D-32 / D-38 / D-39 / D-40 / D-42 的全部引擎级能力一次上游，
并补齐 2.2.4 未覆盖文件的 **LF 行尾**写回侧修复。

### 新增

- **`code/entity_alias_guard.py`**（D-38/39）：实体别名护栏 —— 弱标识判定
  （泛化称呼 / 源稿口条 / 电话号码 / 单字姓 / 带注解 …）、`split_aliases()`
  强弱别名分离、`strong_aliases()`、`is_junk_entity_name()`（机器标签拦截）、
  **`colliding_aliases()`（别名自污染闸）**：别名若等于**另一实体的
  `canonical_name`** 一律剔除（canonical 具"指名性"）。**纯规则、零实例数据。**
- **`code/asr_alias.py`**（D-40）：ASR 音近错听映射装载器（`map()` 精确匹配、
  不做子串；`map_all()` / `group_of()` / `allows_cross_type()`）。
  错字是**源稿固有属性**，LLM 无法自纠 → 必须在 resolver 出口映射一次。
  配置外置 `config/asr_alias.json`，缺失即降级空表（引擎可在无该配置的环境跑通）。
- **`code/ref_rewrite.py`**（D-32）：**四形态**引用改写器 —— ①全路径双链
  ②短名双链 ③显示名 ④`backlinks` 裸路径（形态 4 **整行锚定**防误伤散文）+
  `stale_backlinks()`。⚠ 铁律：必须用完整目标边界 `(?=[\]|#])`，禁裸 `replace`
  （实测 `深度` 是 `深度数科` 前缀 → 死链 10 → 68）。
  `rewrite_wikilinks(..., dry_run=True)` **只统计不落盘**。
- **`code/fidelity_gate.py`**：摘要忠实度门（F1 关键数字行数／F2 署名噪声／
  F3 双链／F4 字节缩水／F5 泛指词入实体表），退出码 1 = FAIL。

### 修复

- **LF 行尾写回侧补齐**（D-34 遗留）：`steps/s12_wiki.py`(6) / `polish_pages.py`(5) /
  `backlink_builder.py`(1) / `entity_resolver.py` 的 `write_text` 全部补
  `newline="\n"` —— Windows 下不指定会把 `\n` 翻译为 `\r\n`，**重新引入 CRLF**。
- **`entity_resolver._find()` 两阶段化**（D-38/39 实体黑洞根治）：原实现把
  canonical 匹配与 alias 命中放在**同一循环**，返回值**取决于 registry 遍历顺序**
  （同一名字既是他者 canonical、又出现在本者 aliases → 谁排前归谁，不确定）。
  现改：阶段 1 `canonical_name` 精确优先；阶段 2 仅**强 alias** 才归并。
  update 分支只并入强 alias（弱标识另存 `weak_aliases`，仅供展示）。
- **`steps/s12_wiki.py` 页名绑定 `canonical_name`**（D-40）：原实现 `name` 写 s6
  原始名，而 `polish_pages` 按 `name` 判同源 → 同一 `entity_id` 因称法不同裂成多页
  （实例实测 20 组「同 id 多页」）。现 `name`／文件名／H1 一律取 `canonical_name`，
  本次称法降为 alias 保留溯源；orgs 同步。

### 变更

- **`lint_wiki` 13 → 15 维**：
  - `14_dup_h2` —— 同名 H2 重复（判据与 `polish_pages._h2_norm` 同源，
    剥离尾部计数后缀 `(N)`／`(N 次出现)`）。合并类操作的**盲区**：
    合并天然产生重复同名小节（实例实测 12 页），既有 13 维无一覆盖
    → 标尺「零回归」是**假阴性**。
  - `15_multi_page_entity` —— 同 `entity_id` 多页（页面层与身份层脱钩）。
    与 `11_entity_fragments` 分工：11 维按**页名基名**抓命名分片；
    15 维按**页名完全不同但 id 相同**抓身份脱钩。二者互补、可同时命中。
    豁免台账 `system/state/known_multi_page_entities.json`（仅收录刻意设计者，
    缺失即空集 —— 引擎发行版不内置实例数据）。
  - 配套标尺 `scripts/baseline_check.py` 由 17 维 → **19 维**。

## [2.2.4] - 2026-09-15

分叉清账版：实例侧 4 处热修一次上游 + 实体页并入重复小节根治。**换 4 个文件即可**
（`code/pipeline.py` / `code/lint_wiki.py` / `code/polish_pages.py` / `scripts/link_orphans.py`，
另 `scripts/ingest_source.py` 仅加注释），已部署 2.2.0+ 的环境可按文件覆盖升级。

### 修复

- **`pipeline.py mark_processed()` count 冻结 + 重跑非幂等**（分叉 #1）：原实现只 append、
  从不同步 `count` 元数据，导致 count 永久冻结在最后一次 ingest 运行时的值（实例实测
  39 vs 实际 43）。现补：同 `content_hash` 旧 ok 条目出栈（重跑幂等，墓碑保留）+
  `count` 与 ingest 口径同步 + `updated_at` 时间戳。
- **`polish_pages.py` merge_mode 并入带回整套骨架**（分叉 #4 / D-d）：原实现把被并入页
  的 H1 + 全套骨架 H2 原样追加进规范主页，多次并入后出现重复同名小节（实例实测 23 页）。
  现改为**回并既有 H2 结构**：剥离 H1；骨架小节并入目标页同名 H2 末尾（计数后缀
  `(N)`/`(N 次出现)` 归一化匹配）；无名可并的小节降级 H3 挂在 `### {date} 补充出现`
  标记下。幂等守卫（source_meeting 检查）不变。

### 变更

- **`lint_wiki.py` 人工审查白名单外置**（分叉 #2）：`MANUAL` 从代码硬编码改为读取
  `<project_root>/system/state/manual_entities.json`（字符串数组，与 `known_orphans.json`
  同套路：代码同构、数据分离）。文件缺失时为空集，引擎不内置任何实例人名。
- **`scripts/link_orphans.py` 上游引擎**（分叉 #3）：真孤儿回链工具（幂等、零 LLM、
  Synthesis/Queries/Summaries 豁免、`source_meeting → source_ref` 别名回退）首次进入
  引擎发行版；路径锚点改为 `PJ102_PROJECT_ROOT` 环境变量 / cwd。
- **`scripts/ingest_source.py` 非递归护栏**：`glob("*.md")` 处加代码注释 —— 严禁改为
  递归（非递归是"汇总包不入扫描范围"的隐性保护）。

## [2.2.3] - 2026-09-15

补丁版：修复「同源重跑必产重复摘要页」的污染型缺陷。**只换 `s15_summary_page.py` 一个文件即可**，
已部署 2.2.0 的环境无需重装（覆盖该文件，或重装本补丁版的 whl / 绿色包）。

### 修复

- **同源重跑累积「（2）」重复摘要页**：`code/steps/s15_summary_page.py` 原先只做
  `while target.exists(): target = …（n）.md` —— 只判**文件名是否被占用**，从不读旧页的
  `source_hash`。后果：同一源文件每重跑一次就必然新产出一张 `…（2）`、`…（3）` 页，
  且重跑产物质量可能**低于**既有版本（实测 2026-09-08：新版 2585B / 8 链 < 旧版 3905B / 15 链，
  即"重跑倒退"）。
  现改为**三级命名判定**：

  | 情形 | 判定 | 行为 |
  |---|---|---|
  | 目标不存在 | `direct` | 直写 |
  | 存在且 `source_hash` **相同**（同源重跑） | `same_source` | 渲染后按 `_content_grade` **择优覆盖**（新版不劣于旧版才落地，否则保留既有版本 → `same_source_kept_old`） |
  | 存在且 `source_hash` **不同**（异源真冲突） | `suffixed` | 沿用既有约定加 `（n）` |

  返回值新增 `naming_decision` 字段，便于批次审计（`system/cache/steps/<hash>/s15.json` 可见）。

  新增 `_content_grade(text) -> (双链数, 五要素已填数, 字节数)` 作为同源择优的排序键。

### 变更

- 引擎版本标识升为 `2.2.3-s15fix`（`pj102 version` 可见）；`pyproject.toml` / `__init__.py`
  版本号同步（`__init__.py` 此前滞留在 `2.1.0-dist`，本次一并归位）。

### 说明

- 本补丁**不含**以下三项（属"结果不一致/误报"的一致性缺陷，不产生新垃圾页，
  合并到下一次重构批次处理）：
  `code/pipeline.py mark_processed()` 状态文件 count 不同步 / `code/lint_wiki.py`
  实体分片白名单 / `scripts/link_orphans.py` 来源字段别名回退。

## [2.2.0] - 2026-09-13

一引擎三环境达成（WorkBuddy / codex / hermes 共享 venv + 三隔离实例）。

### 修复

- **CLI `ask` 通道崩溃**：`scripts/run_query.py` 为原项目遗留启动器，引用 `kb_retriever.main()`
  （引擎版无此导出）导致 `ImportError`——重写为与 MCP `kb_query` 同构的实现
  （L1 实体卡直答 / L2 综合问答，支持 `--stub` 快速 L1 测试与 LLM 失败优雅降级）；
  此前冒烟仅覆盖 `--help` 未实跑 ask，由 M 阶段三环境验收暴露。

### 变更

- 引擎版本标识升为 `2.2.0-multienv`（`pj102 version` 可见）。

## [2.1.0] - 2026-09-12

首个纯净发行版（v2.1.0-dist）。

### 新增

- **引擎/实例分离架构**：引擎只含能力，实例由 `pj102 init` 生成（全占位符配置、零预置数据）；
- **CLI 全套**：`init` / `ingest` / `run` / `ask` / `lint` / `stats` / `mcp` / `version`；
- **13 步 LLM 编译管线** + 五类内容分型（多人会议纪要 / 双人通话 / 判断 / 情景 / 综合）；
- **后处理链**：polish → merger → backlink → fix_index → lint → dispute → log；
- **12 维质量门**：graph_orphans / content_orphans 拆分定稿；
- **两级检索栈**：L1 实体导航（纯规则毫秒级）+ L2 综合问答（三改写扩召回 / 行内编号引用 / 越界钳制）；
- **MCP 三工具**：`kb_query` / `kb_lint` / `kb_stats`（stdio，可接入任意 MCP 客户端）；
- **工程红线**：幂等记账 / 断点续跑 / 预算熔断（`--budget-yuan`）/ 占位符守卫（source_dir 未配置显式报错）；
- **虚构示例**（`examples/`）与**单元测试**（`tests/`，虚构化语料）；
- **完整设计文档**：需求规格 / 详细设计 / 摄入分型规格 / 版本指南 / ADR。

### 修复

- `ingest` 读实例配置改从实例根解析（原脚本相对路径在 pip 安装态失效，静默扫 0 文件）；
- MCP `kb_stats` 在空实例上优雅降级（原读取不存在的 index.md 崩溃）；
- 分型判定：minutes 结构词行首锚定 + 判定顺序调整（冒号行统计信号不再优先于强结构信号）。

### 发行

- `pj102_engine-2.1.0-py3-none-any.whl`（约 152KB）；
- Windows 绿色包 `pj102-green-*.zip`（含离线依赖 PyYAML 3.11/3.12/3.13、一键 `install.bat`、
  MCP 幂等注册脚本、完整安装指引）。

### 内部质量

- 纯净性终审：全树敏感词零命中（真实人名 / 商业词 / 本机路径 / 密钥特征）；
- 干净环境八项 DoD 开箱终验全过（解压 / 离线安装 / init / MCP 注册 / 虚构示例分型摄入 /
  stats / lint / MCP 三工具响应 / 幂等清理）。
