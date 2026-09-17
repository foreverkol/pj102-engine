"""
v4.0 index_builder.py - 主索引 + 操作日志 (Karpathy LLM Wiki 缺口4)

扫描 wiki/ 所有 .md 文件, 解析 frontmatter, 生成:
  - wiki/index.md  人类可读主索引 (按类型分组, 含统计)
  - wiki/log.md    操作日志 (记录编译事件)

其他缺口模块 (file_back/concept_merger/daily_incremental) 依赖此索引。

设计:
  - 不引入新依赖, 用 pyyaml 解析 frontmatter (core 已用)
  - 幂等: 每次运行覆盖 index.md, 追加 log.md
  - 守引擎铁律: 跨平台 pathlib, 配置注入 AppConfig
"""

import sys
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Optional

sys.path.insert(0, str(Path(__file__).parent))
from core import AppConfig, get_logger

import yaml

log = get_logger()


def parse_frontmatter(content: str) -> dict:
    """解析 markdown frontmatter (--- 包围的 YAML)"""
    if not content.startswith("---"):
        return {}
    parts = content.split("---", 2)
    if len(parts) < 3:
        return {}
    try:
        fm = yaml.safe_load(parts[1]) or {}
        return fm if isinstance(fm, dict) else {}
    except Exception:
        return {}


def extract_title(content: str, fm: dict, file_path: Path) -> str:
    """提取文件标题 (优先 frontmatter.title, 其次 body 一级标题, 最后文件名)"""
    if fm.get("title"):
        return str(fm["title"])
    # body 一级标题
    for line in content.split("\n"):
        line = line.strip()
        if line.startswith("# ") and not line.startswith("## "):
            return line[2:].strip()
    return file_path.stem


def _extract_summary(content: str, fm: dict) -> str:
    """W1-T1.2: 提取条目一行摘要 (优先 frontmatter, 否则正文首个内容行)"""
    for k in ("summary", "description"):
        if fm.get(k):
            return str(fm[k])[:80]
    # 去掉 frontmatter 块
    body = content
    if content.startswith("---"):
        parts = content.split("---", 2)
        body = parts[2] if len(parts) > 2 else content
    for s in (l.strip() for l in body.split("\n")):
        if s and not s.startswith(("#", "-", "|", ">", "!", "*", "[")):
            clean = s.replace("**", "").replace("*", "")[:80]
            # 过滤占位词 (s12 生成的空字段占位)
            if clean.strip("：: ") in ("未提取", "待补充", "暂无", "无", "N/A"):
                continue
            return clean
    return ""


def scan_wiki(wiki_root: Path) -> List[Dict]:
    """扫描 wiki/ 所有 .md 文件, 返回条目列表"""
    entries = []
    if not wiki_root.exists():
        return entries
    for md_file in sorted(wiki_root.rglob("*.md")):
        # 跳过 index.md / log.md 自身及归档文件
        if md_file.name in ("index.md", "log.md") or md_file.name.startswith("log.legacy"):
            continue
        try:
            content = md_file.read_text(encoding="utf-8")
        except Exception:
            continue
        fm = parse_frontmatter(content)
        title = extract_title(content, fm, md_file)
        rel_path = md_file.relative_to(wiki_root)
        entries.append({
            "file": md_file,
            "rel_path": rel_path,
            "title": title,
            "summary": _extract_summary(content, fm),  # W1-T1.2
            "type": fm.get("type", _infer_type_from_path(rel_path)),
            "entity_id": fm.get("entity_id", ""),
            "canonical_name": fm.get("canonical_name", ""),
            "date": str(fm.get("date", fm.get("meeting_date", "")) or ""),
            "value_grade": fm.get("value_grade", ""),
            "status_stage": fm.get("status_stage", ""),
            "tags": fm.get("tags", []),
            "content_hash": fm.get("content_hash", ""),
            "generated_at": fm.get("generated_at", ""),
        })
    return entries


def _infer_type_from_path(rel_path: Path) -> str:
    """从路径推断 type (frontmatter 无 type 时)"""
    parts = str(rel_path).replace("\\", "/")
    if "Meetings" in parts:
        return "meeting"
    if "Persons" in parts:
        return "person"
    if "Organizations" in parts:
        return "organization"
    if "Concepts" in parts:
        return "concept"
    if "Judgments" in parts:
        return "judgment"
    if "Comparisons" in parts:
        return "comparison"
    if "Scenarios" in parts:
        return "scenario"
    if "Answers" in parts:
        return "answer"
    # W1-T1.2: Karpathy 新增三类路径推断
    if "Summaries" in parts:
        return "summary"
    if "Queries" in parts:
        return "query"
    if "Synthesis" in parts:
        return "synthesis"
    return "unknown"


def group_by_type(entries: List[Dict]) -> Dict[str, List[Dict]]:
    """按 type 分组"""
    groups: Dict[str, List[Dict]] = {}
    for e in entries:
        t = e["type"]
        groups.setdefault(t, []).append(e)
    return groups


TYPE_META = {
    "meeting":      ("📅 会议纪要 (Meetings)",       "Meetings"),
    "person":       ("👥 人物档案 (Persons)",        "Entities/Persons"),
    "organization": ("🏢 机构档案 (Organizations)",  "Entities/Organizations"),
    "concept":      ("💡 概念卡片 (Concepts)",       "Knowledge/Concepts"),
    "judgment":     ("⚖️ 判断记录 (Judgments)",       "Knowledge/Judgments"),
    "comparison":   ("🔍 对比分析 (Comparisons)",     "Knowledge/Comparisons"),
    "scenario":     ("🎯 场景文件 (Scenarios)",       "Knowledge/Scenarios"),
    "answer":       ("📝 问答归档 (Answers)",         "Knowledge/Answers"),
    # W1-T1.2: Karpathy LLM Wiki 新增三类 (W2 起有页面自动出现)
    "summary":      ("📄 源摘要 (Summaries)",         "Summaries"),
    "query":        ("❓ 问答回流 (Queries)",         "Queries"),
    "synthesis":    ("🧩 综合分析 (Synthesis)",       "Synthesis"),
}
TYPE_ORDER = ["meeting", "person", "organization", "concept",
             "judgment", "comparison", "scenario", "answer",
             "summary", "query", "synthesis"]


def build_index_md(entries: List[Dict], wiki_root: Path, version: str) -> str:
    """生成 wiki/index.md 内容"""
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    groups = group_by_type(entries)
    total = len(entries)

    lines = [
        f"# PJ-102 知识库主索引",
        "",
        f"> 由 index_builder 自动生成 · {version} · 最后更新: {now}",
        f"> 共 **{total}** 个条目 · "
        f"{len(groups.get('person', [])) + len(groups.get('organization', []))} 个实体",
        "",
        "---",
        "",
    ]

    # 统计概览
    lines.append("## 📊 统计概览")
    lines.append("")
    lines.append("| 类型 | 数量 |")
    lines.append("|------|------|")
    for t in TYPE_ORDER:
        if t in groups:
            label = TYPE_META.get(t, (t, ""))[0]
            lines.append(f"| {label} | {len(groups[t])} |")
    lines.append(f"| **总计** | **{total}** |")
    lines.append("")

    # 按类型分组列表
    for t in TYPE_ORDER:
        if t not in groups:
            continue
        label = TYPE_META.get(t, (t, ""))[0]
        lines.append(f"## {label}")
        lines.append("")
        # 按日期倒序 (meeting/answer) 或按名称 (person/org/concept)
        items = groups[t]
        if t in ("meeting", "answer", "judgment"):
            items.sort(key=lambda x: x.get("date", ""), reverse=True)
        else:
            items.sort(key=lambda x: x.get("canonical_name") or x["title"])
        for e in items:
            title = e["title"]
            rel = str(e["rel_path"]).replace("\\", "/")
            meta_parts = []
            if e.get("value_grade"):
                meta_parts.append(f"{e['value_grade']}级")
            if e.get("entity_id"):
                meta_parts.append(e["entity_id"])
            if e.get("date"):
                meta_parts.append(str(e["date"]))
            if e.get("status_stage") and e["status_stage"] != "compiled":
                meta_parts.append(e["status_stage"])
            meta = " | ".join(meta_parts) if meta_parts else ""
            if meta:
                lines.append(f"- [{title}]({rel}) — {meta}")
            else:
                lines.append(f"- [{title}]({rel})")
            # W1-T1.2: 一行摘要 (Karpathy index 约定)
            if e.get("summary"):
                lines.append(f"  <sub>{e['summary']}</sub>")
        lines.append("")

    lines.append("---")
    lines.append("")
    lines.append("*此索引由 `index_builder.py` 自动维护, 请勿手动编辑。*")
    lines.append(f"*运行 `python scripts/build_index_md.py` 重新生成。*")
    return "\n".join(lines)


def append_log_md(entries: List[Dict], wiki_root: Path, version: str,
                  action: str = "index_builder") -> None:
    """追加操作日志到 wiki/log.md

    W1-T0.2 校准: 统一 Gist 规范格式 "## [YYYY-MM-DD] 操作 | 标题",
    并改为 append 到文件尾 (与 run_full._append_log 方向一致, 时间自然序)。
    """
    log_path = wiki_root / "log.md"
    now = datetime.now().strftime("%Y-%m-%d")
    groups = group_by_type(entries)

    lines = [f"\n## [{now}] {action} | index 重建"]
    lines.append(f"- 扫描 wiki/ 共 {len(entries)} 个文件")
    # 统计
    stats = []
    for t in TYPE_ORDER:
        if t in groups:
            label = TYPE_META.get(t, (t, ""))[0].split("(")[0].strip()
            stats.append(f"{label} {len(groups[t])}")
    lines.append(f"- 统计: {', '.join(stats)}")
    lines.append(f"- 版本: {version}")

    if log_path.exists():
        with open(log_path, "a", encoding="utf-8", newline="\n") as f:
            f.write("\n".join(lines) + "\n")
    else:
        log_path.write_text("# PJ-102 知识库操作日志\n" + "\n".join(lines) + "\n",
                            encoding="utf-8", newline="\n")


def build_index(cfg: AppConfig = None, action: str = "index_builder") -> dict:
    """主入口: 扫描 wiki 生成 index.md + 追加 log.md

    Returns:
        {"total": N, "by_type": {type: count}, "index_path": str, "log_path": str}
    """
    if cfg is None:
        cfg = AppConfig()
    wiki_root = cfg.paths.wiki_base

    entries = scan_wiki(wiki_root)
    groups = group_by_type(entries)

    if not entries:
        log.warning("wiki 目录为空, 无可索引条目", step="index_builder")
        return {"total": 0, "by_type": {}, "index_path": "", "log_path": ""}

    # 生成 index.md
    index_content = build_index_md(entries, wiki_root, cfg.version)
    index_path = wiki_root / "index.md"
    index_path.write_text(index_content, encoding="utf-8", newline="\n")
    log.info(f"生成主索引: {index_path} ({len(entries)} 条目)", step="index_builder")

    # 追加 log.md
    append_log_md(entries, wiki_root, cfg.version, action=action)
    log_path = wiki_root / "log.md"
    log.info(f"追加操作日志: {log_path}", step="index_builder")

    by_type = {t: len(v) for t, v in groups.items()}
    return {
        "total": len(entries),
        "by_type": by_type,
        "index_path": str(index_path),
        "log_path": str(log_path),
    }


# ============ CLI ============

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="PJ-102 知识库主索引生成器")
    parser.add_argument("--action", default="index_builder",
                       help="日志记录的操作名 (默认 index_builder)")
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args()

    result = build_index(action=args.action)
    print(f"\n{'=' * 50}")
    print(f"📚 知识库主索引生成完成")
    print(f"{'=' * 50}")
    print(f"总条目: {result['total']}")
    print(f"分类统计:")
    for t, n in sorted(result["by_type"].items(), key=lambda x: -x[1]):
        print(f"  {t}: {n}")
    print(f"\nindex: {result['index_path']}")
    print(f"log:   {result['log_path']}")
