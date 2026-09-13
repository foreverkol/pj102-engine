#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
archive_query.py — T-P5.3 Queries 闸门校准驱动 (P5 检索与回流体验)

用法:
  python scripts/archive_query.py --query "问题"            # 跑查询, 闸门开则归档
  python scripts/archive_query.py --query "问题" --dry-run  # 只跑不归档, 看闸门判定

流程: 复用 run_query.py 的 env/路径引导 → kb_retriever.query_wiki() →
  双闸门 (citations>=2 内建 + 本脚本价值确认) → write_query_page() 归档。
输出 JSON: {citations, gate, archived, page}
"""
import os
import sys
import json
import argparse

# 1. 从 hermes .env 加载 MiniMax key (与 run_query.py 同源, utf-8-sig 防 BOM)
HERMES_ENV = os.path.join(os.environ.get("PJ102_PROJECT_ROOT") or os.getcwd(), ".env")
if os.path.exists(HERMES_ENV):
    with open(HERMES_ENV, encoding="utf-8-sig") as f:
        for line in f:
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                k, _, v = line.partition("=")
                k = k.strip()
                v = v.strip().strip('"').strip("'")
                if k and v and k not in os.environ:
                    os.environ[k] = v

os.environ.setdefault("MINIMAX_CN_BASE_URL", "https://api.minimaxi.com")

PROJECT_ROOT = os.environ.get("PJ102_PROJECT_ROOT") or os.getcwd()
sys.path.insert(0, os.path.join(PROJECT_ROOT, "code"))

from kb_retriever import KBRetriever, write_query_page  # noqa: E402
from llm_client import LLMClient  # noqa: E402
from core.config import AppConfig  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--query", required=True)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    cfg = AppConfig()
    llm = LLMClient()
    persons_master = cfg.paths.system_dir / "registry" / "persons_master.json"
    if not persons_master.exists():
        persons_master.write_text("{}", encoding="utf-8")  # 空结构优雅降级, 不能 touch 空文件
    r = KBRetriever(
        registry_path=cfg.paths.registry_path,
        persons_master_path=persons_master,
        llm_client=llm,
        wiki_root=cfg.paths.wiki_base,
        cfg=cfg,
    )
    result = r.query_wiki(args.query)

    cites = result.get("citations", [])
    gate_open = "suggest_archive" in result
    out = {
        "query": args.query,
        "citations": len(cites),
        "cite_list": [Path_safe(c) for c in cites[:8]],
        "gate": gate_open,
        "synthesis_head": (result.get("synthesis") or "")[:120],
    }

    if gate_open and not args.dry_run:
        page = write_query_page(result, os.path.join(PROJECT_ROOT, "wiki"))
        out["archived"] = bool(page)
        out["page"] = Path_safe(page) if page else None
    else:
        out["archived"] = False
        out["page"] = None

    print(json.dumps(out, ensure_ascii=False, indent=1))


def Path_safe(p):
    return str(p).replace("\\", "/")


if __name__ == "__main__":
    main()
