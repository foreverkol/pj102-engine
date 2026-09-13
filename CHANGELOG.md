# Changelog

本项目的所有重要变更记录在此。格式参照 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，
版本号遵循 [SemVer](https://semver.org/lang/zh-CN/)。

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
