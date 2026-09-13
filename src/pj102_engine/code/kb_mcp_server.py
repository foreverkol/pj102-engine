# -*- coding: utf-8 -*-
"""pj102-kb MCP Server: 知识库三工具 (W3-T3.3)

stdio JSON-RPC 2.0 / MCP 协议 2024-11-05, 纯 stdlib 实现 (无 mcp 包依赖)

工具:
  kb_query  - L1 实体卡直答 / L2 BM25+LLM 综合问答 (citations 标注来源页)
  kb_lint   - 12 维巡检 (图孤儿/密度孤儿/死链/缺来源/矛盾/过时/未索引/乱码/必填/标签/分片)
  kb_stats  - 知识库规模统计 (页数/索引/死链/孤儿)

注册: %USERPROFILE%/.workbuddy/mcp.json -> mcpServers["pj102-kb"]
"""
import os
import sys
import json

PROJECT_ROOT = os.environ.get("PJ102_PROJECT_ROOT") or os.getcwd()
sys.path.insert(0, os.path.join(PROJECT_ROOT, "code"))
os.chdir(PROJECT_ROOT)


def _load_env():
    """LLM key 从 ~/.hermes/.env 加载 (磁盘文件, 非环境注入)"""
    env_path = os.path.join(os.environ.get("PJ102_PROJECT_ROOT") or os.getcwd(), ".env")
    if os.path.exists(env_path):
        for line in open(env_path, encoding="utf-8-sig"):
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                k, _, v = line.partition("=")
                k = k.strip()
                if k not in os.environ:
                    os.environ[k] = v.strip().strip('"').strip("'")


def _tool_kb_query(query: str) -> str:
    _load_env()
    from pathlib import Path
    from llm_client import LLMClient
    from kb_retriever import KBRetriever
    r = KBRetriever(
        registry_path=Path("system/registry/entity_registry.json"),
        persons_master_path=Path("system/registry/persons_master.json"),
        llm_client=LLMClient(),
        wiki_root=Path("wiki"))
    res = r.query_wiki(query)
    out = [f"[{res.get('level', '?')}] 查询: {query}", ""]
    if res.get("matches"):
        for m in res["matches"][:5]:
            out.append(f"• 实体: {m.get('canonical_name', m.get('name', '?'))}"
                       f" ({m.get('entity_type', '')})")
    if res.get("synthesis"):
        out += ["", res["synthesis"]]
    if res.get("citations"):
        out += ["", "引用来源:"]
        out += [f"  - [[{c}]]" for c in res["citations"]]
    if res.get("suggest_archive"):
        out += ["", f"建议归档: {res['suggest_archive'].get('path', '')}"]
    return "\n".join(out)


def _tool_kb_lint() -> str:
    from pathlib import Path
    from lint_wiki import lint_wiki
    r = lint_wiki(Path("wiki"))
    lines = ["知识库巡检结果 (12 维):"]
    for k, v in r.items():
        if k == "2_dead_links" and v:
            lines.append(f"  ❌ 死链: {len(v)} -> {v[:5]}")
        elif isinstance(v, list):
            mark = "✓" if not v else "⚠"
            lines.append(f"  {mark} {k}: {len(v)}")
        else:
            lines.append(f"    {k}: {v}")
    return "\n".join(lines)


def _tool_kb_stats() -> str:
    from pathlib import Path
    W = Path("wiki")
    counts = {}
    total = 0
    for p in W.rglob("*.md"):
        if ".obsidian" in p.parts:
            continue
        total += 1
        top = p.relative_to(W).parts[0] if p.relative_to(W).parts else "?"
        counts[top] = counts.get(top, 0) + 1
    lines = ["知识库统计:", "  总页数: %d" % total]
    idx = W / "index.md"
    if idx.exists():
        lines.append("  索引链接: %d" % idx.read_text(encoding="utf-8").count("[["))
    if counts:
        lines.append("  分区:")
        lines += ["    %s: %d" % (k, v) for k, v in
                  sorted(counts.items(), key=lambda x: -x[1])]
    return "\n".join(lines)


TOOLS = [
    {
        "name": "kb_query",
        "description": "pj102 engine知识库问答。实体问题返回实体卡(角色/机构/关系), "
                       "综合问题返回带引用来源的多页综合回答。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "自然语言问题"}
            },
            "required": ["query"],
        },
    },
    {
        "name": "kb_lint",
        "description": "知识库 12 维健康巡检: 图孤儿/密度孤儿/死链/缺来源/矛盾待检/过时页/"
                       "未索引/必填字段/乱码。",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "kb_stats",
        "description": "知识库规模统计: 总页数/索引链接数/各分区页数。",
        "inputSchema": {"type": "object", "properties": {}},
    },
]


def _result(text: str) -> dict:
    return {"content": [{"type": "text", "text": text}]}


def _error(msg: str) -> dict:
    return {"content": [{"type": "text", "text": f"ERROR: {msg}"}],
            "isError": True}


def handle(req: dict) -> dict | None:
    method = req.get("method", "")
    req_id = req.get("id")
    if method == "initialize":
        return {"jsonrpc": "2.0", "id": req_id, "result": {
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "pj102-kb", "version": "1.0.0"},
        }}
    if method == "notifications/initialized":
        return None
    if method == "ping":
        return {"jsonrpc": "2.0", "id": req_id, "result": {}}
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": req_id, "result": {"tools": TOOLS}}
    if method == "tools/call":
        params = req.get("params", {})
        name = params.get("name", "")
        args = params.get("arguments", {}) or {}
        try:
            if name == "kb_query":
                return {"jsonrpc": "2.0", "id": req_id,
                        "result": _result(_tool_kb_query(args.get("query", "")))}
            if name == "kb_lint":
                return {"jsonrpc": "2.0", "id": req_id,
                        "result": _result(_tool_kb_lint())}
            if name == "kb_stats":
                return {"jsonrpc": "2.0", "id": req_id,
                        "result": _result(_tool_kb_stats())}
            return {"jsonrpc": "2.0", "id": req_id,
                    "result": _error(f"unknown tool: {name}")}
        except Exception as e:
            return {"jsonrpc": "2.0", "id": req_id,
                    "result": _error(f"{type(e).__name__}: {e}")}
    if req_id is not None:
        return {"jsonrpc": "2.0", "id": req_id,
                "error": {"code": -32601, "message": f"method not found: {method}"}}
    return None


def main():
    sys.stderr.write("pj102-kb MCP server ready\n")
    sys.stderr.flush()
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError:
            continue
        resp = handle(req)
        if resp is not None:
            sys.stdout.write(json.dumps(resp, ensure_ascii=False) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
