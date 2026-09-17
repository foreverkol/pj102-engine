"""pytest 引导（2026-09-16）。

**诊断脚本误收集**：``tests/_manual/`` 下是**手工诊断脚本**（非单元测试），
它们在 ``import`` 阶段即联网 / 读取凭据（如 ``~/.hermes/.env``）/
实例化 ``AppConfig``。自动收集会触发真实的网络调用，且缺凭据时直接
``FileNotFoundError`` 中断**整个测试套件**（实测会导致 tests/ 零收集）。
故在此排除。

注：引擎为 src layout（``src/pj102_engine/``），故**每个测试文件必须自行做
双布局路径解析**（模板见 ``tests/test_d42_no_id_ops.py`` 的 ``_ROOT`` 写法）。
反例（2026-09-17 实测）：``test_entity_alias_guard`` 与 ``test_fidelity_gate``
仅写 ``ROOT/"code"``（引擎 layout 下不存在），**依赖收集顺序副作用**才 import
成功 —— 单独跑必 collection error，逆序跑会中断整个套件。
"""
collect_ignore_glob = ["tests/_manual/*"]
