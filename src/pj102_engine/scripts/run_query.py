# -*- coding: utf-8 -*-
"""pj102 engine · query launcher v2.0 (CLI ask 通道, v2.2.0 修复)

用法(cli.py 转发):
  pj102 ask "问题" -i <实例>
  pj102 ask "问题" --stub -i <实例>    (stub 模式, 不调 LLM, 快速 L1 测试)

行为与 MCP kb_query 工具同构:
  L1 实体卡直答 / L2 BM25+LLM 综合问答, 行内编号引用可溯源。
"""
import os
import sys
from pathlib import Path

# 1. 实例根与工作目录 (cli.py 已设 PJ102_PROJECT_ROOT)
PROJECT_ROOT = Path(os.environ.get("PJ102_PROJECT_ROOT") or os.getcwd()).resolve()
os.chdir(PROJECT_ROOT)

# 2. 实例 .env 加载 (utf-8-sig, 已有环境变量不覆盖)
env_path = PROJECT_ROOT / ".env"
if env_path.exists():
    for line in env_path.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if "=" in line and not line.startswith("#"):
            k, _, v = line.partition("=")
            k = k.strip()
            if k and k not in os.environ:
                os.environ[k] = v.strip().strip('"').strip("'")

# 3. LLM 网关默认
os.environ.setdefault("MINIMAX_CN_BASE_URL", "https://api.minimaxi.com")

# 4. 引擎 code/ 目录入 path (cli.py 已加, 此处幂等兜底)
ENGINE_CODE = Path(__file__).resolve().parent.parent / "code"
if str(ENGINE_CODE) not in sys.path:
    sys.path.insert(0, str(ENGINE_CODE))

# 5. 参数: 位置参数为问题, 可选 --stub / -v
argv = sys.argv[1:]
stub = "--stub" in argv
verbose = "-v" in argv
question = " ".join(a for a in argv if not a.startswith("-")).strip()
if not question:
    print("用法: pj102 ask \"问题\" [-i 实例目录] [--stub]")
    sys.exit(2)

# 6. LLM 接入 (失败优雅降级 stub)
llm = None
if not stub:
    try:
        from llm_client import LLMClient
        llm = LLMClient()
        if verbose:
            print(f"[init] LLM provider={llm.provider}, model={llm.model}",
                  file=sys.stderr)
    except Exception as e:
        print(f"[warn] LLM 初始化失败, 降级 stub: {e}", file=sys.stderr)

# 7. 检索栈调用 (与 kb_mcp_server._tool_kb_query 同构)
from kb_retriever import KBRetriever

r = KBRetriever(
    registry_path=Path("system/registry/entity_registry.json"),
    persons_master_path=Path("system/registry/persons_master.json"),
    llm_client=llm,
    wiki_root=Path("wiki"))
res = r.query_wiki(question)

out = [f"[{res.get('level', '?')}] 查询: {question}", ""]
if res.get("matches"):
    for m in res["matches"][:5]:
        out.append(f"• 实体: {m.get('canonical_name', m.get('name', '?'))}"
                   f" ({m.get('entity_type', '')})")
if res.get("synthesis"):
    out += ["", res["synthesis"]]
if res.get("citations"):
    out += ["", "引用来源:"]
    out += [f"  - [[{c}]]" for c in res["citations"]]
print("\n".join(out))
