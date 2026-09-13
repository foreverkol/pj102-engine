"""
v4.0 concept_merger.py - 跨会议概念合并 (Karpathy LLM Wiki 缺口3)

扫描 wiki/Knowledge/Concepts/, 按概念名分组 (同概念多份会议),
LLM 合并成综合词条, 保留所有 quote_orig + 来源会议。

设计:
  - 文件名格式: concept_{name}_{hash}.md, 按 name 分组
  - 同名 >1 个 → LLM 合并 → concept_{name}_merged.md
  - 合并后保留所有 quote_orig + 来源会议日期
  - 幂等: merged 文件已存在则跳过
  - 守引擎铁律: 抗幻觉, 只基于原文合并, 不新增未提及内容
"""

import os
import sys
import re
import json
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Tuple

sys.path.insert(0, str(Path(__file__).parent))
from core import AppConfig, compute_content_hash, get_logger

import yaml

log = get_logger()


def parse_frontmatter_and_body(content: str) -> Tuple[dict, str]:
    """解析 frontmatter 和 body"""
    if not content.startswith("---"):
        return {}, content
    parts = content.split("---", 2)
    if len(parts) < 3:
        return {}, content
    try:
        fm = yaml.safe_load(parts[1]) or {}
        if not isinstance(fm, dict):
            fm = {}
    except Exception:
        fm = {}
    return fm, parts[2]


def extract_concept_name(file_path: Path) -> str:
    """从文件名提取概念名: concept_{name}_{hash}.md → name"""
    stem = file_path.stem  # concept_供应链金融_c65a0c7a
    # 去掉 concept_ 前缀
    if stem.startswith("concept_"):
        stem = stem[8:]
    # 去掉最后的 _hash (12 位 hex)
    m = re.match(r"^(.+)_([a-f0-9]{8,12})$", stem)
    if m:
        return m.group(1)
    # merged 文件: concept_{name}_merged
    if stem.endswith("_merged"):
        return stem[:-7]
    return stem


def scan_concepts(concepts_dir: Path) -> Dict[str, List[Path]]:
    """扫描 Concepts/ 目录, 按概念名分组

    Returns: {concept_name: [file1, file2, ...]}
    只返回原始文件 (不含 _merged), 待合并的概念 (len > 1)
    """
    if not concepts_dir.exists():
        return {}
    groups: Dict[str, List[Path]] = {}
    for md_file in sorted(concepts_dir.glob("*.md")):
        if md_file.name in ("index.md",):
            continue
        name = extract_concept_name(md_file)
        # 跳过已 merged 的
        if "_merged" in md_file.stem:
            continue
        groups.setdefault(name, []).append(md_file)
    # 只返回需要合并的 (>1 个)
    return {k: v for k, v in groups.items() if len(v) > 1}


def build_merge_prompt(concept_name: str, concept_files: List[Path]) -> Tuple[str, str]:
    """构造 LLM 合并 prompt

    Returns: (system_prompt, user_prompt)
    """
    system_prompt = (
        f"你是知识库合并器。你收到多个关于同一概念「{concept_name}」的 wiki 条目"
        f"（来自不同会议）。请合并成一个综合词条。要求:\n"
        f"1. 合并 definition, 取最完整版本, 不新增未提及内容\n"
        f"2. 保留所有 quote_orig 原文引用, 标注来源会议日期\n"
        f"3. 综合各会议的视角, 去重但保留差异\n"
        f"4. 输出格式: Markdown, 含 ## 概念定义 / ## 各会议原文引用 / ## 综合分析\n"
        f"5. 抗幻觉: 只基于提供的原文, 不编造"
    )

    parts = [f"# 概念名: {concept_name}\n"]
    parts.append(f"# 待合并条目: {len(concept_files)} 个\n")
    for i, f in enumerate(concept_files, 1):
        try:
            content = f.read_text(encoding="utf-8")
        except Exception:
            continue
        fm, body = parse_frontmatter_and_body(content)
        date = fm.get("date", fm.get("meeting_date", "未知日期"))
        parts.append(f"\n## 条目 {i} (来源: {date})\n")
        parts.append(body.strip())

    parts.append(
        f"\n# 合并要求\n"
        f"请把上述 {len(concept_files)} 个条目合并成一个综合概念词条。"
        f"保留所有 quote_orig 原文引用, 标注来源会议。"
    )
    return system_prompt, "\n".join(parts)


def merge_concept(concept_name: str, concept_files: List[Path],
                  concepts_dir: Path, llm_client, version: str) -> dict:
    """合并单个概念

    Returns: {"merged": bool, "merged_path": str, "source_count": int}
    """
    merged_path = concepts_dir / f"concept_{concept_name}_merged.md"

    # 幂等: 已存在则跳过
    if merged_path.exists():
        log.info(f"概念「{concept_name}」已 merged, 跳过", step="concept_merger")
        return {"merged": False, "merged_path": str(merged_path),
                "source_count": len(concept_files), "deduplicated": True}

    if not llm_client:
        log.warning(f"无 LLM, 无法合并概念「{concept_name}」", step="concept_merger")
        return {"merged": False, "merged_path": "", "source_count": len(concept_files)}

    system_prompt, user_prompt = build_merge_prompt(concept_name, concept_files)

    try:
        merged_body = llm_client.call(
            user_prompt, system=system_prompt, max_tokens=8192)
    except Exception as e:
        log.error(f"LLM 合并失败: {e}", step="concept_merger")
        return {"merged": False, "merged_path": "", "source_count": len(concept_files)}

    if not merged_body or not merged_body.strip():
        return {"merged": False, "merged_path": "", "source_count": len(concept_files)}

    # 构建 merged 文件 frontmatter
    now = datetime.now()
    content_hash = compute_content_hash(concept_name + merged_body[:500])
    source_dates = []
    source_files = []
    for f in concept_files:
        try:
            c = f.read_text(encoding="utf-8")
            fm, _ = parse_frontmatter_and_body(c)
            d = fm.get("date", fm.get("meeting_date", ""))
            if d:
                source_dates.append(str(d))
            source_files.append(f.name)
        except Exception:
            pass

    fm = {
        "type": "concept",
        "title": concept_name,
        "canonical_name": concept_name,
        "concept_name": concept_name,
        "is_merged": True,
        "source_count": len(concept_files),
        "source_dates": source_dates,
        "source_files": source_files,
        "content_hash": content_hash,
        "generated_at": now.strftime("%Y-%m-%dT%H:%M:%S"),
        "status_stage": "merged",
        "version": version,
    }

    # 序列化 frontmatter
    fm_yaml = yaml.dump(fm, allow_unicode=True, default_flow_style=False, sort_keys=False)
    md_content = f"---\n{fm_yaml}---\n\n{merged_body}\n"

    merged_path.write_text(md_content, encoding="utf-8")
    log.info(f"合并概念「{concept_name}」: {len(concept_files)} → 1 "
             f"({merged_path.name})", step="concept_merger")

    return {
        "merged": True,
        "merged_path": str(merged_path),
        "source_count": len(concept_files),
        "deduplicated": False,
    }


def merge_all_concepts(cfg: AppConfig = None, llm_client=None) -> dict:
    """主入口: 扫描并合并所有同名概念

    Returns:
        {"total_concepts": N, "merged_count": N, "merged_details": [...]}
    """
    if cfg is None:
        cfg = AppConfig()
    concepts_dir = cfg.paths.wiki_base / "Knowledge" / "Concepts"

    groups = scan_concepts(concepts_dir)
    if not groups:
        log.info("无待合并概念", step="concept_merger")
        return {"total_concepts": 0, "merged_count": 0, "merged_details": []}

    log.info(f"发现 {len(groups)} 个待合并概念", step="concept_merger")

    merged_details = []
    merged_count = 0
    for concept_name, files in groups.items():
        result = merge_concept(concept_name, files, concepts_dir,
                                llm_client, cfg.version)
        merged_details.append({
            "concept": concept_name,
            "source_count": len(files),
            "merged": result["merged"],
            "path": result.get("merged_path", ""),
        })
        if result["merged"]:
            merged_count += 1

    # 更新主索引
    if merged_count > 0:
        try:
            from index_builder import build_index
            build_index(cfg, action=f"concept_merger: {merged_count} merged")
        except Exception as e:
            log.warning(f"index 更新失败: {e}", step="concept_merger")

    return {
        "total_concepts": len(groups),
        "merged_count": merged_count,
        "merged_details": merged_details,
    }


# ============ CLI ============

if __name__ == "__main__":
    import argparse
    import os

    # 加载 hermes .env
    hermes_env = Path(os.path.join(os.environ.get("PJ102_PROJECT_ROOT") or os.getcwd(), ".env"))
    if hermes_env.exists():
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
        description="PJ-102 跨会议概念合并器 (Karpathy 缺口3)")
    parser.add_argument("--dry-run", action="store_true",
                       help="只列出待合并概念, 不调 LLM")
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args()

    cfg = AppConfig()

    if args.dry_run:
        groups = scan_concepts(cfg.paths.wiki_base / "Knowledge" / "Concepts")
        print(f"\n{'=' * 50}")
        print(f"💡 待合并概念 ({len(groups)} 个)")
        print(f"{'=' * 50}")
        for name, files in groups.items():
            print(f"\n「{name}」({len(files)} 个文件):")
            for f in files:
                print(f"  • {f.name}")
    else:
        from llm_client import LLMClient
        llm = LLMClient()
        result = merge_all_concepts(cfg=cfg, llm_client=llm)
        print(f"\n{'=' * 50}")
        print(f"💡 概念合并完成")
        print(f"{'=' * 50}")
        print(f"待合并概念: {result['total_concepts']}")
        print(f"成功合并: {result['merged_count']}")
        for d in result["merged_details"]:
            status = "✅" if d["merged"] else "⏭️"
            print(f"  {status} 「{d['concept']}」({d['source_count']} → 1)")
            if d["path"]:
                print(f"     → {d['path']}")
