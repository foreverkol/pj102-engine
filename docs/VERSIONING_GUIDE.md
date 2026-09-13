# PJ-102-02 · 版本管理与发布规范及使用指南（面向新手详解）

> 面向：不熟悉 git/GitHub 的使用者 · 编写日期：2026-09-10 · 基线 v2.0.1-release
> 阅读本文后您将能：看懂本项目的版本体系 / 自行查看与使用任何版本 / 理解发布全过程

---

## 一、先厘清三个概念（一句话版）

| 概念 | 是什么 | 本项目现状 |
|---|---|---|
| **Git** | 一个装在您电脑上的"时光机"软件，记录每次变更（谁/何时/改了什么），可随时回到任意时点 | ✅ 在用（项目目录下的隐藏 `.git` 文件夹就是它的数据库） |
| **GitHub** | 微软提供的**网站**，把本地 git 仓库同步到云端备份/分享 | ❌ **尚未使用**——本项目全部版本在您本机 F 盘，云端发布是 D-5 待决项 |
| **发布（Release）** | 在某个稳定版本上打"封条"（tag）+ 存一份完整快照（zip）+ 写发布说明 | ✅ 每个里程碑都做，最新为 v2.0.1-release |

**关键理解**：本项目"发布"= 本地 git 打标签 + zip 快照落盘 + 发布说明文档，**不依赖 GitHub**。当前所有版本您在本机即可完整查看与使用。

---

## 二、本项目的三层版本管理规范

| 层 | 载体 | 作用 | 位置 |
|---|---|---|---|
| 1. 代码与文档历史 | git 提交（commit） | 逐次变更记录，可回溯任何一次修改 | 项目目录 `.git` |
| 2. 版本锚点 | git 标签（tag） | 里程碑封条，指向某次提交 | 本地 git |
| 3. wiki 全量快照 | zip 压缩包 + manifest | 知识库成品的整包存档（git 不管 wiki 正文，按既定策略由 zip 管理） | `system/backup/` |

**版本号命名规范**：`主版本.次版本.修订号-性质`
- `v2.0.1-release` = 主版本 2（终态架构）· 次版本 0 · 修订 1 · 性质 release（正式发布）
- 里程碑性质后缀：`-p0~p6-milestone`（阶段成果）/ `-terminal`（终态锚点）/ `-release`（正式发布）

**何时打版本（发布三条件，缺一不可）**：
1. 该阶段任务卡 DoD 全部实测通过
2. lint + verify 质量门全绿（零回归）
3. 文档全向同步（里程碑报告 + 需求规格 changelog + 总计划状态）

---

## 三、版本链全景（13 个标签，从旧到新）

| 标签 | 日期 | 含义 |
|---|---|---|
| v1.0.0-w5-terminal | 09-09 | W5 阶段收口 |
| v1.0.1 ~ v1.0.4 | 09-09 | 回归/守护协议/3样本新跑/工具链还债 |
| v1.1.0-p0-milestone | 09-09 | P0 工具链治理 |
| v1.2.0-p1-milestone | 09-10 | P1 数据质量攻坚 |
| v1.3.0-p2-milestone | 09-10 | P2 实体归一 |
| v1.4.0-p3-milestone | 09-10 | P3 质量尾巴清零 |
| v1.5.0-p4-milestone | 09-10 | P4 批量摄入稳定性+真新样本实战 |
| v1.6.0-p5-milestone | 09-10 | P5 检索与回流体验 |
| **v2.0.0-terminal** | 09-10 | **终态锚点**：DoD 五项复验全过，转入运维节奏 |
| **v2.0.1-release** | 09-10 | **当前最新**：七项测试验证后的首个正式发布 |

每个标签都有对应 zip 快照在 `system/backup/`（命名 `wiki_版本_日期_说明.zip`，内含 MANIFEST.txt）。

---

## 四、如何查看版本（实操命令）

在项目目录打开命令行（Win+R 输入 cmd，或资源管理器地址栏输 cmd 回车）：

```
cd /d D:\my-kb-project

git tag                          # 1. 列出全部版本标签（按字母序，v2.0.1-release 最新）
git log --oneline -10            # 2. 最近 10 次变更（一行一摘要，含版本号说明）
git show v2.0.1-release --stat   # 3. 看本次发布改了哪些文件（只列文件名）
git show v2.0.0-terminal --stat # 4. 对比查看终态锚点的内容
git log v1.5.0-p4-milestone..v2.0.1-release --oneline   # 5. 查两个版本之间发生了哪些变更
```

无需任何账号密码——这些都是**读本机文件**，不联网。

## 五、如何使用某个已发布版本

### 场景 A：只读浏览某个历史版本的 wiki 内容（推荐，零风险）

直接解压对应 zip 快照到任意临时目录查看：
```
system/backup/wiki_v2.0.1_20260910_release.zip   ← 当前正式发布版（583 页）
system/backup/wiki_v2.0.0_20260910_1005_terminal.zip
```
zip 内 MANIFEST.txt 记录了快照时间/范围/变更说明。

### 场景 B：日常使用（就是现在）

**当前工作区 = v2.0.1-release 发布态**，正常使用即可：
- 问答：`python -X utf8 -c "...kb_query..."`（见 RELEASE 文档）
- 新文件摄入：`python scripts/ingest_source.py` → `python scripts/run_full.py --budget-yuan 1.0`

### 场景 C：回退到历史版本（⚠️ 少用，需谨慎）

git 方式（改代码/文档层）：
```
git stash                                # 先保存当前未提交修改（如有）
git checkout v2.0.0-terminal             # 切到终态版本浏览（"detached"状态，只看不改）
git checkout master                      # 用完切回最新主线
```
wiki 内容层回退 = 解压旧 zip 覆盖 `wiki/` 目录（操作前先备份当前 wiki/，zip 覆盖不可逆，**执行前请找我确认**）。

---

## 六、当前这次发布（v2.0.1-release）的过程说明（七步实录）

| 步 | 动作 | 产出 |
|---|---|---|
| 1 | **测试验证**：七项测试实跑（lint/verify/幂等/异常注入/分型/MCP/成本） | 7/7 全过 + 发现 1 个分型缺陷 |
| 2 | **缺陷修复**：分型器 v1.2（纪要误判 chat 边界修复）+ 回归验证 | 0902 真样本零影响 |
| 3 | **文档落盘**：测试方案/类型详解/发布说明 三份文档 | docs/ 下 3 个新文件 |
| 4 | **快照打包**：wiki 583 页全量 zip + MANIFEST | `system/backup/wiki_v2.0.1_20260910_release.zip` |
| 5 | **版本号更新**：VERSION 文件 → `2.0.1-release` | VERSION |
| 6 | **git 提交**：5 文件变更（+258 行）详细提交说明 | commit `2e1bda7` |
| 7 | **打标签封版**：`git tag -a v2.0.1-release` | 本地标签，永久锚点 |

提交与打标**不可变**（封条性质）；每步产物均有据可查。

---

## 七、关于 GitHub（D-5 待决项）

**现状**：本项目尚无远程仓库。若未来您决定发布到 GitHub（对外分享/云端备份），流程为：
1. 注册 GitHub 账号 → 新建仓库（如 `pj102-liangchaojie-wiki`）
2. `git remote add origin https://github.com/您的用户名/仓库名.git`
3. `git push -u origin master --tags`（代码+全部 13 个标签一次推上）
4. 在 GitHub 网页 Releases 页为 `v2.0.1-release` 创建 Release 并上传 zip 快照附件

届时我可以代为执行并逐步指导。**注意**：语料含商业对话内容，是否公开需您权衡（可建私有仓库仅自己可见）。

---

## 八、主理人常用命令速查卡

| 想做什么 | 命令（在项目目录执行） |
|---|---|
| 看当前什么版本 | `type VERSION` |
| 看所有版本 | `git tag` |
| 看最近变更 | `git log --oneline -5` |
| 看某版本改了什么 | `git show v2.0.1-release --stat` |
| 验证当前库健康 | `python -X utf8 scripts/verify.py` |
| 全库质量巡检 | `python -X utf8 -c "import sys;sys.path.insert(0,'code');from lint_wiki import lint_wiki;from pathlib import Path;[print(k,len(v)) for k,v in lint_wiki(Path('wiki')).items()]"` |
| 投喂新文件（先扫描） | `python -X utf8 scripts/ingest_source.py --dry-run` |
