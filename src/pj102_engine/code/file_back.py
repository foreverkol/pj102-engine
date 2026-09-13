"""
v4.0 file_back.py - 归档回写 (Karpathy LLM Wiki 缺口2)

把 query 产出归档回 wiki/Knowledge/Answers/, 实现知识复利:
  - query 的综合答案成为新的 wiki 条目
  - 后续 query 能检索到之前的问答 (知识复利飞轮)

设计:
  - synthesis 已是 LLM 综合的高质量内容, file_back 只加结构化 frontmatter
  - 不额外调 LLM (零成本), 可选 LLM 提取 tags
  - 幂等: content_hash 去重, 相同 query+synthesis 不重复归档
  - 归档后触发 index_builder 更新主索引

流程:
  archive_query(query, synthesis, citations)
    → 生成 answer_{date}_{hash}.md (frontmatter + synthesis body)
    → 写入 wiki/Knowledge/Answers/
    → 触发 index_builder 更新 index.md + log.md
"""

import sys
import re
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Optional

sys.path.insert(0, str(Path(__file__).parent))
from core import AppConfig, compute_content_hash, get_logger

import yaml

log = get_logger()


def _extract_tags(text: str, max_tags: int = 8) -> List[str]:
    """从 synthesis 文本提取标签 (出现频率高的 2-4 字词)"""
    # 提取中文 2-4 字词
    words = re.findall(r"[\u4e00-\u9fff]{2,4}", text)
    # 统计频率
    from collections import Counter
    counter = Counter(words)
    # 去停用词
    stopwords = {"的", "了", "是", "在", "和", "与", "及", "或", "为", "对",
                 "到", "从", "被", "把", "给", "向", "于", "以", "由", "此",
                 "其", "之", "者", "也", "都", "还", "又", "再", "就", "只",
                 "才", "便", "然", "但", "一个", "这个", "那个", "我们",
                 "他们", "可以", "需要", "应该", "可能", "或者"}
    tags = [w for w, c in counter.most_common(30)
            if w not in stopwords and c >= 2][:max_tags]
    return tags


def _build_frontmatter(query: str, synthesis: str, citations: List[str],
                       content_hash: str, version: str) -> str:
    """构建 answer 条目的 frontmatter"""
    now = datetime.now()
    date = now.strftime("%Y-%m-%d")

    tags = _extract_tags(synthesis)

    fm = {
        "type": "answer",
        "title": query[:60] + ("..." if len(query) > 60 else ""),
        "query": query,
        "date": date,
        "content_hash": content_hash,
        "generated_at": now.strftime("%Y-%m-%dT%H:%M:%S"),
        "status_stage": "archived",
        "source_citations": citations,
        "tags": tags,
        "version": version,
    }
    # 手动序列化为可读 YAML (避免 yaml.dump 顺序问题)
    lines = ["---"]
    for k, v in fm.items():
        if isinstance(v, list):
            lines.append(f"{k}:")
            for item in v:
                lines.append(f"  - {item}")
        elif isinstance(v, str) and ("'" in v or '"' in v or ":" in v or "#" in v):
            # 需要引号
            escaped = v.replace("'", "''")
            lines.append(f"{k}: '{escaped}'")
        else:
            lines.append(f"{k}: {v}")
    lines.append("---")
    return "\n".join(lines)


def archive_query(query: str, synthesis: str, citations: List[str],
                 cfg: AppConfig = None, llm_client=None) -> dict:
    """把 query 产出归档回 wiki/Knowledge/Answers/

    Args:
        query: 原始查询
        synthesis: LLM 综合答案
        citations: 引用文件路径列表
        cfg: AppConfig
        llm_client: 可选 LLM (用于提取更精炼 tags)

    Returns:
        {"archived": bool, "answer_path": str, "content_hash": str,
         "deduplicated": bool, "index_updated": bool}
    """
    if cfg is None:
        cfg = AppConfig()

    # 幂等: content_hash 去重
    content_hash = compute_content_hash(query + synthesis)
    answer_dir = cfg.paths.wiki_base / "Knowledge" / "Answers"
    answer_dir.mkdir(parents=True, exist_ok=True)
    answer_path = answer_dir / f"answer_{datetime.now().strftime('%Y-%m-%d')}_{content_hash}.md"

    # 去重检查
    if answer_path.exists():
        log.info(f"answer 已存在, 跳过归档: {answer_path.name}",
                 step="file_back", sample=query[:30])
        return {
            "archived": False,
            "answer_path": str(answer_path),
            "content_hash": content_hash,
            "deduplicated": True,
            "index_updated": False,
        }

    # 构建 answer 条目
    frontmatter = _build_frontmatter(query, synthesis, citations,
                                       content_hash, cfg.version)
    body = synthesis if synthesis.strip() else "(无综合内容)"

    md_content = f"{frontmatter}\n\n## 查询问题\n\n{query}\n\n## 综合答案\n\n{body}\n"

    # 如果有引用, 附加引用来源
    if citations:
        md_content += "\n## 引用来源\n\n"
        for c in citations:
            md_content += f"- [{c}]({c})\n"

    # 写入
    answer_path.write_text(md_content, encoding="utf-8")
    log.info(f"归档 answer: {answer_path.name} (hash={content_hash})",
             step="file_back", sample=query[:30])

    # 触发 index_builder 更新主索引
    try:
        from index_builder import build_index
        build_index(cfg, action=f"file_back: {query[:40]}")
        index_updated = True
    except Exception as e:
        log.warning(f"index_builder 更新失败: {e}", step="file_back")
        index_updated = False

    return {
        "archived": True,
        "answer_path": str(answer_path),
        "content_hash": content_hash,
        "deduplicated": False,
        "index_updated": index_updated,
    }


def query_and_archive(query: str, cfg: AppConfig = None,
                      llm_client=None, retriever=None) -> dict:
    """查询 + 归档一键流程 (知识复利闭环)

    1. 调用 kb_retriever 查询
    2. 把结果归档回 wiki/Knowledge/Answers/
    3. 更新主索引

    Returns:
        {"query": str, "level": "L1"|"L2", "archived": bool, "answer_path": str}
    """
    if cfg is None:
        cfg = AppConfig()

    # 1. 查询
    if retriever is None:
        from kb_retriever import KBRetriever
        persons_master = cfg.paths.system_dir / "registry" / "persons_master.json"
        llm = llm_client
        if llm is None:
            try:
                from llm_client import LLMClient
                llm = LLMClient()
            except Exception:
                llm = None
        retriever = KBRetriever(
            registry_path=cfg.paths.registry_path,
            persons_master_path=persons_master,
            llm_client=llm,
            wiki_root=cfg.paths.wiki_base,
            cfg=cfg,
        )

    result = retriever.query_wiki(query)

    # 2. 归档 (L2 综合才有归档价值)
    if result.get("level") == "L2" and result.get("synthesis"):
        archive_result = archive_query(
            query=query,
            synthesis=result["synthesis"],
            citations=result.get("citations", []),
            cfg=cfg,
        )
        return {
            "query": query,
            "level": result["level"],
            "archived": archive_result["archived"],
            "answer_path": archive_result.get("answer_path", ""),
            "deduplicated": archive_result["deduplicated"],
            "index_updated": archive_result["index_updated"],
            "synthesis_preview": result["synthesis"][:200] + "...",
        }
    else:
        # L1 命中, 无需归档
        return {
            "query": query,
            "level": result["level"],
            "archived": False,
            "answer_path": "",
            "deduplicated": False,
            "index_updated": False,
            "matches": len(result.get("matches", [])),
        }


# ============ CLI ============

if __name__ == "__main__":
    import argparse

    # 加载 hermes .env (复用 run_query 的逻辑)
    hermes_env = Path(os.path.join(os.environ.get("PJ102_PROJECT_ROOT") or os.getcwd(), ".env"))
    if hermes_env.exists():
        import os
        try:
            with open(hermes_env, encoding="utf-8-sig") as f:
                for line in f:
                    line = line.strip()
                    if "=" in line and not line.startswith("#"):
                        k, _, v = line.partition("=")
                        k = k.strip()
                        v = v.strip().strip('"').strip("'")
                        if k and k not in os.environ:
                            os.environ[k] = v
            os.environ.setdefault("MINIMAX_CN_BASE_URL", "https://api.minimaxi.com")
        except Exception:
            pass

    parser = argparse.ArgumentParser(
        description="PJ-102 知识库归档回写 (Karpathy 缺口2: 知识复利)")
    parser.add_argument("--query", required=True, help="查询问题")
    parser.add_argument("--synthesis", default=None,
                       help="综合答案 (不提供则自动查询)")
    parser.add_argument("--citations", default="",
                       help="引用文件 (逗号分隔, 不提供则自动)")
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args()

    if args.synthesis:
        # 直接归档已有效果
        cfg = AppConfig()
        citations = [c.strip() for c in args.citations.split(",") if c.strip()]
        result = archive_query(
            query=args.query,
            synthesis=args.synthesis,
            citations=citations,
            cfg=cfg,
        )
    else:
        # 查询 + 归档一键
        result = query_and_archive(args.query)

    import json
    print(f"\n{'=' * 50}")
    print(f"📝 归档回写结果")
    print(f"{'=' * 50}")
    print(json.dumps(result, ensure_ascii=False, indent=2))
