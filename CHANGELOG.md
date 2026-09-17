# Changelog

本项目的所有重要变更记录在此。格式参照 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，
版本号遵循 [SemVer](https://semver.org/lang/zh-CN/)。

## [2.5.0] - 2026-09-17

**引擎设施补全：LLM 输入截断统一入口 · 缓存熔断 · 内容承接门 · 日期权威分层判据**，
并**补齐引擎自身两处既有缺陷**（后处理装置死于无人调用 / ASR 别名探测路径差一级）。
测试 **85 → 118 passed**。

> 上游范围经 `scripts/engine_sync_probe_20260917.py` 勘察裁定：先**归一化**
> （去 BOM / CRLF→LF / 去行尾空白）再比对，并按**行的语法角色**分型 ——
> 避免把「实例中性化差异」误当工作量。**环境适配与部署侧数据一律不上游**。

### 新增

- **`code/excerpt.py` —— LLM 输入截断的单一入口**。
  原先 12 个 LLM 步骤各自硬编码 `content[:N]`（4000~10000 不等），且**都不告知
  模型「末尾已省略」** ⇒ 长会议（中位 25664 字）中后段被系统性丢弃，模型对残缺
  上下文臆测或弃答 ⇒ 落盘空骨架被判为「无产出」。现统一为
  `excerpt_for_llm(content, default)`，超限时把「原文共 X 字 / 末尾 Y 字未提供 /
  不要臆测」**直接拼进 excerpt**；环境变量 `PJ102_EXCERPT_LIMIT` 提供统一下限。
  12 个消费方同步接线（`steps/{s2,s4,s5,s6,s7,s8,s9,s10,s11,s13,s14}.py` + `s3_summary`）。
- **`code/pipeline.py`：B3 缓存熔断 `fuse_check`（两级）**。
  `hard` ＝ 已实证的确定性退化（如 s3 的 `one_sentence` 为空/占位）⇒ **中止该样本**；
  `soft` ＝ 「全字段空/占位」⇒ **不落盘但样本继续**（保持可重试、不误伤批次）。
  `s13/s14` 合法产物是 list，空 list **不**判退化。
  开关 `PJ102_FUSE_DISABLE=1` 应急关闭。
  理由：缓存是「可信重放」的契约 —— 写入退化产物即违约（曾致下游 s15 重放抛
  `S15MissingS3`，而批跑依然报「成功」）。
- **`code/polish_pages.py` v1.6：分片页丢弃必须过「内容承接」门**。
  三条无校验丢弃路径曾致 210 个分片页中 20 份的**实质内容未被任何规范页承接即被
  unlink**。现统一为一条不变式：**分片页只有在其实质内容已被目标页承接时才可丢弃**；
  未承接 ⇒ **强制并入目标页**（而非新建「（2）」副本），保证只增不减。
  含 `_norm_line` / `_body_lines` / `_subst_lines` / `_contained` 装置。
- **`scripts/run_full.py` 接线 4 个后处理装置**：2.5 `link_orphans`（孤儿回链补齐，
  必须排在 backlink_builder 之后、index_builder 之前）、7.5 `normalize_tree`
  （出口署名校正，幂等）、7.6 registry 别名健康度巡检（只读 + 告警）、
  8 `baseline_check`（19 维标尺对拍，使「每批次后自动断言」成为管线固有行为）。
  ⇒ 原版上述装置**死于无人调用**（与旧基线 `p1_lint_baseline.json` 同一病因）。
- **`scripts/baseline_check.py`（19 维标尺对拍）** 与
  **`scripts/audit_registry_aliases.py`（registry 别名健康度巡检）** 随引擎首次分发。
- **`scripts/s3_fidelity_gate_20260916.py`（s3 值级忠实度门）**：把 s3 抽出的每个
  数字**回原始转写稿**做值级比对（不采信 wiki 派生文本），分层判据
  L1 exact → L2 去分隔 → L3 口读连写（含**降序链** `1亿1511万`）→ L4 量级换算，
  MISS 即可疑编造。支持多源回退，并打印 `skipped` 计数防「单源假绿」。
- **`scripts/engine_sync_probe_20260917.py`（引擎 ↔ 部署仓差异勘察器）**：
  落实「每处热修都问：引擎侧是否同步」的自动化装置。**只读**。

### 修复

- **`code/steps/s1_basic.py`：日期权威改为分层判据**。
  源稿**文件名的年月日可能笔误**（有孪生副本 sha256 完全相同却日期不同者），
  而**文件头也可能被污染**（与内部标题自相矛盾）⇒ 单一证据源都不可信。
  改为：⓪ `config/date_authority.json` 覆盖表 → ① 头部与内部标题**年月日交叉一致**
  则采信 → ② 不一致/缺失则回退文件名（保持历史行为，零回归）。
  判据**只用年月日、不比时分**（时分本就不一致，比了反使判据失效）。
- **`code/steps/s3_summary.py`（四项）**：
  1. **截断上限 6000 → 20000 字**（原值只覆盖源稿中位长的约 23%），并在提示词中
     **显式告知「末尾 N 字未提供、不要臆测」**；
  2. 提示词新增**署名硬规则**：方括号内只写人名本身，**严禁**「发言人 / 发言人本人 /
     说话人 / 本人 / 关键发言人」等转写口条词；
  3. **抓取规则扩展**：人数（几百人 / 十几人）、时长（一年左右）、倍数、月份等
     **非货币数字**同样是关键数字，严禁因缺少货币单位而漏抓；
  4. 出口兜底清洗（幂等，仅 T1/T2）—— 白名单归约（T3）依赖部署侧数据，**刻意不启用**
     以保持引擎可移植。
- **`code/entity_resolver.py`（ASR 别名探测路径差一级）**：
  原 `<registry>/../../config/asr_alias.json` 在多种布局下解析错位 ⇒ 探测失败 ⇒
  `load_asr_alias(None)` **静默降级为空表** ⇒ ASR 音近错听映射在整个链路中失效。
  改为自 registry **逐级上溯**探测 `<ancestor>/config/asr_alias.json`（布局无关）。
- **`code/pipeline.py`（线程泄漏）**：脉冲线程停止原先只在成功路径执行 ⇒
  **抛异常的样本会让 daemon 线程永久泄漏**，日志出现「多个样本同时在跑」的假象
  （曾被误判为并发跑批）。改为 `try/finally`。
- **`code/llm_client.py`（四项）**：
  1. **空响应必须计为重试** —— SSE 建连成功、随即 0 字节结束时原实现直接 `return ""`，
     被当作「成功」⇒ 不再重试 ⇒ 步骤产出全字段空 ⇒ 被软熔断拒落盘；
  2. **`base_resp` 透出** —— MiniMax 的业务级错误以 **HTTP 200 + SSE** 返回、
     `choices` 为 `null`，真实原因在 `base_resp.status_code`；原实现直接 `continue`
     ⇒ **错误被静默吞掉**，与真正的网络抖动无法区分；
  3. **429/5xx 重试条件修正** —— 原 `e.code == 429 and e.code >= 500` **恒假**，
     限流与服务端错误从未触发重试；
  4. **JSON 解析失败可见化**（写 `sys.stderr`）：原静默兜底把「解析失败」伪装成
     「确无产出」；另补 `import sys`（原缺失 ⇒ 兜底分支 `NameError`）。
- **`code/judgments_aggregator.py` 补 `import os`**：使用了 `os.environ` 但顶部未 import。
- **写入侧统一声明 `newline="\n"`**（8 文件 / 10 处）：`.gitattributes` 只管 **git 侧**，
  写入侧不显式指定则在 Windows 上写出 CRLF 污染工作区。

### 测试

- 新增 6 个**布局无关**测试（33 例）：`test_llm_empty_retry`(4) /
  `test_llm_server_refusal`(6) / `test_newline_contract`(8) / `test_pulse_thread_leak`(2) /
  `test_s3_prompt_contract`(5) / `test_s3_value_gate`(8)。
  `test_llm_server_refusal` 内嵌**实测原始报文**做回归；
  `test_s3_value_gate` 含**负控**（真编造必须仍被抓，防「宽容」演化成「放水」）。
- **修复既有测试的路径脆弱性**：`test_entity_alias_guard` 与 `test_fidelity_gate`
  原先只写 `ROOT/"code"`（src layout 下不存在），**依赖收集顺序副作用**才能 import ——
  单独跑必 collection error、逆序跑会中断整个套件。现统一为**双布局**解析
  （模板见 `tests/test_d42_no_id_ops.py`）。
- 合计 **118 例**（85 → 118）。

## [2.4.0] - 2026-09-16

**backlink 归属修复 + LLM 调用可观测性 + 引擎测试体系建立**。
本次上游把实例侧 D-44 / D-51 / D-52 的引擎级缺陷一次修完，并首次为引擎仓
补上**布局无关**的回归测试（17 → **85 passed**）。

### 修复

- **`code/backlink_builder.py`（D-52，四处真缺陷）**
  1. **glob 元字符**：`glob(f"*{entity_name}*.md")` 把实体名里的 `(` `)` `[` `]`
     当模式解释 ⇒ `千问(Qwen)` / `难度(原南都)` / `王总(人民王总)` 一类实体页
     **永远收不到 backlinks**（实测单页 backlinks 归零、缩水 44.5%）。
     改为纯子串匹配 `_find_by_substr`，语义等价且无元字符风险。
  2. **只写首个匹配页**（D-44）：`entity_id` 对应多页时（T2 时间分页
     `X（2023-09-07）` / `X（2025-05-29）`），第一页被反复重建、
     **其余页 backlinks 永远停在旧值**（表现为 `13_stale_backlinks` 僵尸条目）。
     新增 `find_all_wiki_files_for_entity()` 让同族每页都获得 backlinks。
  3. **归属错误 + 计数虚高**：子串匹配会让**一个页被多个实体争抢**
     （实测 20 页，如 `阿里千问办公.md` ← `阿里` / `千问` / `阿里千问办公`）。
     页的 backlinks 由「最后写入者」决定 ⇒ **挂错对象**；且每次运行都重写该页，
     即使内容已收敛仍稳定报「N 个文件更新」，**幂等性无法用计数验证**。
     新增 **`build_entity_file_map()`**：按特异性 **P1 精确同名 > P2 T2 时间分页族
     > P3 子串兜底（最短优先）** 一次性分配，**一个文件只归属一个实体**。
  4. **非幂等（拼接多一个 `\n`）**：`parse_frontmatter_and_body` 用
     `content.split("---", 2)`，故 `body` **自身以 `"\n"` 开头**；
     原拼接 `f"---\n{fm}---\n{body}"` 每次重建都在正文前**多累积一个空行**。
     正确拼法为 `f"---\n{fm}---{body}"`。修复后连跑三次 = **0 / 0 / 0 变更**。
  另：`load_entity_types()` 一次性读入 `canonical_name → entity_type`
  （原实现**每个实体**都全量 `json.loads` 一遍 registry）。

- **`code/llm_client.py`（D-51）**：调用**全程可观测**。
  原实现在 `urlopen` 阻塞期间零输出，叠加 300s 单值超时 × `max_retries=4`
  ⇒ 最长 20 分钟**静默黑洞**（补跑表现为"停在 s7、无 traceback、无 FAIL"，
  实测进程累计 CPU 仅 0.09s ⇒ 阻塞在 socket 等待而非计算）。
  现每轮 attempt 开始/结束各写一行，并加 `TOTAL_TIMEOUT` 总时限兜底；
  单次超时改为 `REQ_TIMEOUT`（默认 180s，环境变量 `PJ102_LLM_TIMEOUT` 可覆盖）。

### 新增

- **`code/lint_cache.py`**：缓存体检 4 维 —— C1 完整度 / C2 有效性（含元话语）/
  C3 s3 哨兵 / C4 摘要副本。与 `lint_wiki` 13 维合成 **17 维**口径。
- **`code/speaker_norm.py`**：署名规范化 T1（剥离转写标签前缀）/
  T2（多署名拆分）/ T3（白名单规范化）。**三护栏缺一即错**：双链掩码、
  **转述护栏**（`X转述Y` 宁可残留也不归错人）、并列不猜。
  ⚠ 引擎侧 `_DEFAULT_CANONICAL` **刻意置空** —— 白名单是实例数据，
  由 `config/speaker_alias.json` 提供；引擎只做 T1/T2。

### 测试

- 新增 `tests/test_backlink_entity_lookup.py`（12 项）：glob 元字符回归、
  归属唯一性不变量（**任何页不得同时归属两个实体**）、P1 优先于 P3、
  T2 族整族归属、子串兜底取最短、源码护栏（禁止再把实体名拼进 glob 模式）。
- 引擎测试集**只收布局无关用例**：实例专属测试（依赖 `config/*.json`、
  实例 `scripts/`、实例路径）**不上游**，留在实例仓。
- 累计 **85 passed**。

### 已知遗留（v2.5.0）

- 部分引擎文件的 **docstring 仍含实例实体名**（`asr_alias` / `entity_alias_guard` /
  `entity_resolver` / `fidelity_gate` / `lint_wiki` / `speaker_norm`）。
  仅注释层，不影响行为，计划统一中性化。
- 实例侧 `output_renderer` / `index_builder` / `concept_merger` / `file_back` 等
  与引擎差异较大（数百至近千行），需**逐块 cherry-pick** 评估，不在本次载荷内。

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
