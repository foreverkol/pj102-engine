# pj102 快速上手（QUICKSTART）

> 本引擎只含**能力**，不含任何人的数据。你的知识库由你自己的录音转写文件生成，
> 全部数据只存在你自己电脑上。

## 你需要准备的东西

1. 一台电脑（Windows / Linux / macOS）+ Python ≥ 3.10
2. 一个 LLM API key（MiniMax 推荐；任何 OpenAI 兼容接口亦可）
3. 你的录音转写文件（`.md` 文本，多人对话 / 通话纪要，最好带发言人标注）

## 安装（任选其一）

**A. pip 安装（最简）**

```bash
pip install git+https://github.com/<owner>/pj102-engine.git
```

**B. 源码安装（开发者）**

```bash
git clone https://github.com/foreverkol/pj102-engine.git
cd pj102-engine && pip install -e .
```

**C. 绿色包（Windows 小白 / 离线）**：到 Releases 页下载 `pj102-green-*.zip`，
解压双击 `install.bat`，详见包内 `FRIEND_INSTALL_GUIDE.md`。

## 5 步建立你的知识库

```bash
# 1. 创建空白实例
pj102 init 我的知识库

# 2. 配置：编辑 我的知识库/config/project.yaml
#    - scope.source_dir   → 你的转写文件所在目录
#    - scope.core_persons → 对话中最重要的 1-2 人及角色
#    - scope.project_keywords → 业务关键词 3-8 个

# 3. 配置 API key：编辑 我的知识库/.env
#    MINIMAX_CN_API_KEY=你的key

# 4. 摄入 + 编译
pj102 ingest          # 扫描分型（幂等可重跑）
pj102 run             # 13 步管线生成 wiki（内置预算熔断）

# 5. 查询
pj102 ask "某人相关的合作事项有哪些"
```

用 [Obsidian](https://obsidian.md) 打开 `我的知识库/wiki/` 即可图谱化浏览。

## 文件命名规范（影响自动分型）

| 类型 | 命名 | 示例 |
|---|---|---|
| 多人会议/周会纪要 | `20YYMMDDHHMMSS任意中文标题_原文.md` | `20260908221948项目周会_原文.md` |
| 双人通话记录 | `人名@手机号_20YYMMDDHHMMSS标题_原文.md` | `张三@13800000000_20260909100000通话_原文.md` |

命名不规范的文件不会丢（按 unknown 正常入库），但按规则命名分类最准。

## 接入 AI 客户端（可选）

让 WorkBuddy / Codex 等 MCP 客户端直接问答你的知识库，见 README 的
"MCP 接入"一节；或把 `docs/SETUP_AGENT.md` 交给你的 AI Agent 自动完成部署。

## 常用命令

| 命令 | 作用 |
|---|---|
| `pj102 ingest` | 扫描源目录、分型入库（幂等可重跑） |
| `pj102 run` | 运行 13 步全管线，生成 wiki |
| `pj102 ask "问题"` | 检索问答（L1 实体 / L2 综合引用） |
| `pj102 lint` | 12 维质量巡检 |
| `pj102 stats` | 知识库规模统计 |
| `pj102 version` | 查看引擎/实例版本 |

## 卸载

删除实例目录 + `pip uninstall pj102-engine` 即可，零残留。
