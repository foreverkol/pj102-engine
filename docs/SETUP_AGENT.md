# SETUP_AGENT.md — pj102 引擎部署手册（给 WorkBuddy Agent 的操作指引）

> **本文件的读者是 AI Agent。** 用户把绿色包（GitHub Releases 下载的 zip）交给你并让你
> "按 SETUP_AGENT.md 部署"时，
> 按本手册逐步执行。用户是不熟悉命令行的小白，所有需要用户提供的信息，
> 用问答方式逐项收集，不要让他一次性填写表格。

## 0. 前置检查

1. 确认包目录存在以下内容（缺任何一项让用户重新解压）：
   - `install.bat`、`whl/pj102_engine-2.1.0-py3-none-any.whl`、
     `tools/register_mcp.py`、`examples/20260101120000虚构周会纪要_原文.md`、`SETUP_AGENT.md`
2. 确认 `install.bat` 已经执行过（标志：包内存在 `venv\Scripts\pj102.exe`）。
   若没执行过，先指导用户双击运行；若运行报错，读 `install.bat` 输出排障
   （99% 是 Python 未装或版本低于 3.10，让用户在 PowerShell 执行
   `winget install -e --id Python.Python.3.12` 后重试）。
3. 确认 WorkBuddy 连接器管理里已出现 `pj102-kb` 服务器并完成"信任"。
   （`install.bat` 已自动注册；提醒用户去点一下 Trust。）

## 1. 定位实例与命令

- 实例目录（知识库数据根）：`%USERPROFILE%\pj102-kb`
  （`install.bat` 已自动创建空白实例；若没有，执行
  `<包目录>\venv\Scripts\pj102.exe init %USERPROFILE%\pj102-kb`）
- CLI 命令：`<包目录>\venv\Scripts\pj102.exe`（下文简称 `pj102`）
- 所有实例命令须加 `--instance %USERPROFILE%\pj102-kb` 或在实例目录内执行

## 2. 收集用户配置（问答式，逐项来）

编辑 `%USERPROFILE%\pj102-kb\config\project.yaml`，替换以下占位符：

| 字段 | 问用户什么 | 示例 |
|---|---|---|
| `scope.source_dir` | "你放录音转写文件的文件夹在哪？"（帮他确认路径存在） | `D:\我的录音转写` |
| `scope.core_persons` | "对话里最重要的一两个人是谁？什么角色？" | 张三（老板） |
| `scope.project_keywords` | "你们聊的主要话题/业务关键词？给 3-8 个" | 供应链、融资 |
| `project.description` | "这个知识库一句话说明？" | 我的商业对话沉淀 |

**命名规则提醒用户**（影响自动分型）：
- 多人会议/周会纪要：`20YYMMDDHHMMSS任意中文标题_原文.md`（日期数字开头）
- 2 人通话记录：`人名@手机号_20YYMMDDHHMMSS标题_原文.md`

## 3. 配置 API key（只存用户本地）

1. 问用户要 LLM API key（MiniMax 推荐；其他 OpenAI 兼容接口亦可）
2. 写入 `%USERPROFILE%\pj102-kb\.env`：
   ```
   MINIMAX_CN_API_KEY=<用户的key>
   # 如需自定义接口再改 MINIMAX_CN_BASE_URL
   ```
3. 明确告知用户：key 只存在他自己电脑的这个文件里，包的作者拿不到。

## 4. 虚构示例冒烟（不碰用户真实数据）

1. 把包内 `examples\20260101120000虚构周会纪要_原文.md` 复制到用户源目录
2. 执行 `pj102 --instance <实例> ingest`，预期输出：`total: 1, type1: 1`
3. 删掉源目录里这个示例文件，再执行 `pj102 ingest`，确认回到 `total: 0`
   （验证幂等与可清理）
4. 冒烟不过就停，按输出排障；过了才进入第 5 步。

## 5. 首次真实摄入（用户自己的文件）

1. 让用户把转写 `.md` 文件放进他的源目录
2. 执行 `pj102 ingest`：报告 total / type1 / type2 / unknown 数量
3. 执行 `pj102 run`（提醒：会调用 LLM 产生少量费用，按字数计，通常几分钱/文件）
4. 跑完执行 `pj102 stats` 与 `pj102 lint`，把页数与巡检结果汇报给用户

## 6. 验收清单（逐项向用户确认）

- [ ] `pj102 version` 显示引擎与实例版本
- [ ] WorkBuddy 连接器里 `pj102-kb` 已信任，工具 kb_query / kb_lint / kb_stats 可用
- [ ] 虚构示例冒烟通过且已清理
- [ ] 用户真实文件已摄入并跑完管线
- [ ] 在 WorkBuddy 里问一个用户关心的问题（走 kb_query），能回答并带引用

## 7. 常见问题

| 现象 | 处置 |
|---|---|
| `source_dir 仍是占位符未配置` | project.yaml 没填，回到第 2 步 |
| `不是实例目录(缺 config/)` | 命令没加 `--instance` 或目录搞错 |
| run 中途报 429/额度 | 稍后重跑 `pj102 run`（断点续跑，已完成的文件自动跳过） |
| 乱码 | 让用户用 PowerShell `chcp 65001` 后再跑 |
| 想再来一个知识库 | `pj102 init D:\另一个知识库`，互不干扰 |
