# ADR-003 · L0 文本契约与摄入类型多样性的边界原则

> 状态：已接受（Accepted） · 日期：2026-09-10 · 关联：REQUIREMENTS_SPEC OOS-3 / EXECUTION_PLAN_P3P4 §五 / ingest_source.py

## 背景

用户要求摄入支持多样性与灵活性。当前摄入契约（`scripts/ingest_source.py` 实证）：文本 `.md` + 三型命名正则 + 中文>50% + 含"发言人"行 + SHA256 去重；在库 42 样本全部为录音/通话转写。卡帕西方法论（RESEARCH_REPORT 实证）的唯一硬约束是"能进 md 文件夹的文本"，未限定内容类型。

## 决策（边界原则）

1. **L0 永远是文本 .md**（只读纪律不变）——13 步管线 s1–s15 保持**类型无关**，不新增任何"直读"分支；
2. **多样性在预处理层解决**：任何源类型（PDF/网页/docx/音频）先经外置预处理转换为满足 L0 契约的 .md，再进入管线。音频→转写本就是现状；PDF/网页→文本提取属外置工具，不违背 OOS-3（OOS 禁的是"直读"，不是"外置预处理"）；
3. **`file_class` 分型校验**：`index.json` 样本记录新增 `file_class ∈ {transcript, minutes, article, note, chat}`（旧样本默认 transcript）；"发言人"行与命名正则校验仅对 transcript/phone 类强制，article/note/chat 类走宽松校验（非空 + 中文比例）；
4. **分级支持**：T1（满足现行契约的 .md，现在可用）→ T2（file_class 分型 + 外置转换器，P4 做）→ T3（PDF/网页预处理，按需）。

## 影响

- ingest_source.py 的扩展仅限**新增字段与新增校验分支**，既有字段语义与正则不改（G3 合规）；
- 预处理转换器独立目录（如 `scripts/preprocess/`），产出物必须带来源元数据（origin_type/origin_ref）写入 frontmatter，保证可溯源；
- L1c 综合层与 Queries 对 file_class 透明（无需感知类型）。

## 关联证据

`scripts/ingest_source.py` L30-38（三型正则）、RESEARCH_REPORT §2.6（Memex 未限定类型）与 §三（一个 md 文件夹 + LLM）、REQUIREMENTS_SPEC OOS-3。
