"""pytest 引导（2026-09-16）。

**诊断脚本误收集**：``tests/_manual/`` 下是**手工诊断脚本**（非单元测试），
它们在 ``import`` 阶段即联网 / 读取凭据（如 ``~/.hermes/.env``）/
实例化 ``AppConfig``。自动收集会触发真实的网络调用，且缺凭据时直接
``FileNotFoundError`` 中断**整个测试套件**（实测会导致 tests/ 零收集）。
故在此排除。

注：引擎为 src layout（``src/pj102_engine/``），不存在实例仓那种
顶层 ``code/`` 遮蔽标准库 ``code`` 的问题，无需改写 ``sys.path``。
"""
collect_ignore_glob = ["tests/_manual/*"]
