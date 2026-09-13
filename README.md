# pj102-engine

> LLM Wiki 编译知识库引擎 —— 把录音转写/对话纪要编译成结构化、可检索、可溯源的 wiki 知识库。
> 引擎与实例彻底分离：**本仓库只含能力，不含任何数据**——你的知识库由你自己的文件生成，全部数据只存在你自己的电脑上。

[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue)]()
[![License: Apache-2.0](https://img.shields.io/badge/License-Apache--2.0-green)]()
[![Platform](https://img.shields.io/badge/platform-windows%20%7C%20linux%20%7C%20macos-lightgrey)]()

## 这是什么

一套把"非结构化对话文本"变成"结构化知识库"的完整编译管线：

| 能力 | 说明 |
|---|---|
| **13 步 LLM 编译管线** | 转写原文 → 实体抽取 → 关系构建 → 概念沉淀 → 判断定义 → 洞察归纳 → wiki 页生成（Meetings / Judgments / Scenarios / Synthesis / Entities / Summaries 等分区） |
| **五类内容分型** | 多人会议纪要 / 双人通话 / 判断 / 情景 / 综合等，按文件名与内容形态自动分型 |
| **12 维质量门（lint）** | 链接完整性 / 孤页 / 日期规范 / 空页 / 重名等十二个维度的自动巡检 |
| **两级检索栈** | L1 实体导航（纯规则，毫秒级，实体卡直出）/ L2 综合问答（三改写扩召回 → wiki 上下文 → LLM 综合 → 行内编号引用可溯源） |
| **MCP 三工具** | `kb_query` 问答 / `kb_lint` 质检 / `kb_stats` 统计——可注册进任何支持 MCP 的 AI 客户端（WorkBuddy / Codex 等） |
| **工程红线内建** | 幂等可重跑 / 断点续跑 / 预算熔断 / 占位符守卫 / 异常注入自检 |

依赖极简：Python ≥3.10 + PyYAML，纯标准库风格实现，无平台专属调用（whl 为 `py3-none-any`）。

## 架构总览

```
你的源文件(.md 转写/纪要)
      │  pj102 ingest —— 扫描 / 五类分型 / 幂等记账
      ▼
   索引 state
      │  pj102 run —— 13 步 LLM 编译管线（s1…s15）
      ▼
   粗编 wiki ── 后处理链: polish → merger → backlink → fix_index → lint → dispute → log
      ▼
 你的 wiki 知识库（Obsidian 可直接打开的 markdown 目录）
      │
      ├── pj102 ask "……"        检索问答（L1 实体 / L2 综合引用）
      ├── pj102 lint / stats      质检与统计
      └── MCP 三工具              kb_query / kb_lint / kb_stats
```

## 快速开始（三通道任选）

### 通道 ① git clone（开发者推荐）

```bash
git clone https://github.com/<owner>/pj102-engine.git
cd pj102-engine
pip install -e .
pj102 init 我的知识库
```

### 通道 ② 直接 pip 安装

```bash
pip install git+https://github.com/foreverkol/pj102-engine.git
pj102 init 我的知识库
```

### 通道 ③ 绿色包（Windows 小白 / 离线环境）

到 [Releases](../../releases) 页下载 `pj102-green-*.zip`，解压后双击 `install.bat`，
照着包内 `FRIEND_INSTALL_GUIDE.md` 做即可（含 Python / WorkBuddy / Obsidian 全链路指引）。

### 通用四步（通道 ① ② 用户）

```bash
pj102 init 我的知识库                    # 1. 生成空白实例（全占位符配置）
# 2. 编辑 我的知识库/config/project.yaml：
#    source_dir 指向你的转写文件目录；填核心人物与业务关键词
# 3. 编辑 我的知识库/.env：填入你的 LLM API key
pj102 ingest                             # 4. 分型入库（幂等可重跑）
pj102 run                                # 5. 运行 13 步管线，生成你的 wiki
pj102 ask "某人相关的合作事项有哪些"       # 6. 检索问答
```

生成的 wiki 用 [Obsidian](https://obsidian.md) 打开实例目录下的 `wiki/` 即可图谱化浏览。

## CLI 命令表

| 命令 | 作用 |
|---|---|
| `pj102 init <目录>` | 创建全新空白知识库实例 |
| `pj102 ingest` | 扫描源目录、分型入库（幂等可重跑） |
| `pj102 run` | 运行 13 步全管线，生成 wiki（需 API key，有预算熔断） |
| `pj102 ask "问题"` | 检索问答（L1 实体卡 / L2 综合引用） |
| `pj102 lint` | 12 维质量巡检 |
| `pj102 stats` | 知识库规模统计 |
| `pj102 mcp` | 启动 MCP 服务器（stdio，供 AI 客户端接入） |
| `pj102 version` | 引擎/实例版本 |

## MCP 接入（AI 客户端三工具）

任何支持 MCP（Model Context Protocol）的客户端都可接入：

```jsonc
// 客户端 mcp 配置示例（WorkBuddy: ~/.workbuddy/mcp.json；Codex: ~/.codex/config.toml 的 [mcp_servers]）
{
  "mcpServers": {
    "pj102-kb": {
      "command": "pj102",
      "args": ["mcp", "-i", "/你的/实例目录"]
    }
  }
}
```

| 工具 | 作用 |
|---|---|
| `kb_query` | 知识库问答（自动 L1/L2 路由，答案带可溯源引用） |
| `kb_lint` | 12 维质量巡检 |
| `kb_stats` | 知识库统计 |

## 环境要求

- Python ≥ 3.10（Windows / Linux / macOS 均可）
- 一个 LLM API key（MiniMax 推荐；任何 OpenAI 兼容接口亦可，经 `.env` 配置）
- LLM 用量：编译为主，检索级查询为分钱级；`pj102 run` 内置预算熔断（`--budget-yuan`）

## 文档

| 文档 | 内容 |
|---|---|
| [QUICKSTART.md](QUICKSTART.md) | 三步上手（给用户） |
| [docs/SETUP_AGENT.md](docs/SETUP_AGENT.md) | 部署手册（给 AI Agent 的操作指引，问答式完成配置） |
| [docs/FRIEND_INSTALL_GUIDE.md](docs/FRIEND_INSTALL_GUIDE.md) | Windows 新机全链路安装指引（含 WorkBuddy / Obsidian） |
| [docs/REQUIREMENTS_SPEC.md](docs/REQUIREMENTS_SPEC.md) | 需求规格：能力边界与功能契约 |
| [docs/DETAILED_DESIGN.md](docs/DETAILED_DESIGN.md) | 详细设计：13 步管线 / 分型规则 / 检索栈架构 |
| [docs/INGEST_FILE_TYPES.md](docs/INGEST_FILE_TYPES.md) | 摄入分型规格：支持的文件类型与命名规范 |
| [docs/VERSIONING_GUIDE.md](docs/VERSIONING_GUIDE.md) | 版本管理指南 |
| [docs/adr/](docs/adr/) | 架构决策记录（ADR） |

## 目录结构

```
pj102-engine/
├── src/pj102_engine/     # 引擎源码
│   ├── code/             # 管线步骤 / 后处理链 / 检索栈 / lint / MCP 服务器
│   ├── scripts/          # 摄入 / 全量运行 / 查询归档等入口
│   ├── cli.py            # pj102 命令入口
│   └── defaults/         # 默认配置与实例模板
├── docs/                 # 设计与使用文档（本仓库自带完整规格）
├── examples/             # 虚构示例源（冒烟自检用，非真实数据）
├── tests/                # 单元测试（虚构化语料）
├── pyproject.toml
└── README.md
```

## 设计原则

1. **引擎 / 实例分离**：引擎是能力，实例是你的数据——实例由 `pj102 init` 在任意目录生成，引擎绝不经手数据回传；
2. **幂等优先**：所有批次操作可安全重跑，中断续跑不重不漏；
3. **质量门内建**：12 维 lint 是管线的一部分而非事后补丁；
4. **可溯源**：每个综合答案带行内编号引用与源页 wikilink，不允许无出处的编造。

## License

[Apache-2.0](LICENSE) —— 可自由使用、修改、分发与商用，需保留版权与许可声明。
