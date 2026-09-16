# tests/_manual —— 手工诊断脚本（非单元测试）

本目录下的脚本**不是** pytest 单元测试，而是需要真实凭据 / 网络 / 私有语料的
**手工诊断脚本**。它们在 `import` 阶段即执行副作用（联网调用 LLM、读取 `.env`、
实例化 `AppConfig`），因此已由仓库根 `conftest.py` 的 `collect_ignore_glob` 排除，
不参与 `pytest` 自动收集。

## 为什么放在这里（2026-09-16 归档说明）

归档前它们位于 `tests/`，文件名以 `test_` 开头，会被 pytest 当作测试模块收集 ——
但收集即触发真实网络调用；`test_single_step_llm.py` 更在模块级读取
`"~//.hermes/.env"`（**`~` 字面量不会被 `open()` 展开**，路径本身也是错的）
→ 收集阶段直接 `FileNotFoundError`，**整个 `tests/` 无法运行**。

> 该脚本的路径已同步修正为 `os.path.expanduser("~")`（它仍需手工运行）。

## 清单与手动运行方式

| 脚本 | 用途 | 依赖 |
|---|---|---|
| `test_minimax_key.py` | 校验 MiniMax API Key 可用性 | 网络 + `MINIMAX_CN_API_KEY` |
| `test_single_step_llm.py` | 只跑 S2 场景识别，看真实 M3 响应 | 网络 + 凭据 + 源语料 |
| `test_s12_smoke.py` | S12 写 5 类 wiki 冒烟 | 本地 config |
| `test_p3_integration.py` | P3 阶段集成诊断 | 本地 config + 语料 |
| `test_d32_entity_ops.py` | D-32 实体归并装置自检 | **含实例计划表依赖**（`REG_EDITS` 等），故未入 `tests/` |

运行方式（**必须**在仓库根执行）：

```bash
python tests/_manual/test_s12_smoke.py
```

## 单元测试在哪

真正的单元测试在 `tests/` 根下，可直接运行：

```bash
PYTHONPATH=src python -m pytest tests/ -q
```

`tests/test_d42_no_id_ops.py` 是**引擎级**测试（lint 维度 / 引用改写 /
折叠正则），路径解析同时兼容实例仓与引擎仓两种布局，可原样复制到实例仓运行。
