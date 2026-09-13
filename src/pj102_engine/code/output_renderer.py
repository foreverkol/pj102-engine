"""
v4.0 output_renderer.py - 多格式输出 (Karpathy LLM Wiki 缺口5)

把 wiki 内容转成多格式输出:
  1. Marp slides (Markdown 格式, 可被 marp-cli 转 PPTX/PDF)
  2. HTML dashboard (jinja2 模板, 一页总览所有 wiki)
  3. matplotlib 图表 (可选, 需安装 matplotlib)

设计:
  - jinja2 已安装 (core 已用), HTML dashboard 用 jinja2 模板
  - Marp slides 用标准库 Markdown 格式
  - matplotlib 可选 (安装则生成图表, 不安装则跳过)
  - 守金融科技调性: 深海藏蓝/石墨黑/银灰
"""

import sys
import re
import json
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Optional

sys.path.insert(0, str(Path(__file__).parent))
from core import AppConfig, get_logger

import yaml

try:
    from jinja2 import Template
    HAS_JINJA2 = True
except ImportError:
    HAS_JINJA2 = False

log = get_logger()

OUTPUT_DIR_NAME = "outputs"


def parse_frontmatter_and_body(content: str) -> tuple:
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


def render_meeting_slides(meeting_file: Path, output_dir: Path = None) -> str:
    """把 meeting wiki 文件转成 Marp slides (Markdown)

    Returns: slides 文件路径
    """
    if not meeting_file.exists():
        return ""

    content = meeting_file.read_text(encoding="utf-8")
    fm, body = parse_frontmatter_and_body(content)

    title = fm.get("title", meeting_file.stem)
    date = fm.get("date", fm.get("meeting_date", ""))
    value_grade = fm.get("value_grade", "")
    meeting_type = fm.get("meeting_type", fm.get("subtype", ""))
    scene_type = fm.get("scene_type", "")

    # 从 body 提取关键段落
    sections = _extract_sections(body)

    slides = []
    # Marp frontmatter
    slides.append("---")
    slides.append("marp: true")
    slides.append("theme: default")
    slides.append(f"title: {title}")
    slides.append("---")

    # 标题页
    slides.append(f"# {title}")
    slides.append("")
    if date:
        slides.append(f"📅 {date}")
    if meeting_type:
        slides.append(f"🏷️ {meeting_type}")
    if value_grade:
        slides.append(f"📊 价值评级: {value_grade} 级")
    slides.append("")
    slides.append("---")

    # 摘要页
    if "一句话摘要" in sections or "核心摘要" in sections:
        summary = sections.get("一句话摘要", sections.get("核心摘要", ""))
        slides.append("# 核心摘要")
        slides.append("")
        slides.append(summary[:500])
        slides.append("")
        slides.append("---")

    # 金融参数页
    if "金融参数" in sections or "定量参数" in sections:
        params = sections.get("金融参数", sections.get("定量参数", ""))
        slides.append("# 金融参数")
        slides.append("")
        slides.append(params[:800])
        slides.append("")
        slides.append("---")

    # 实体页
    if "涉及人物" in sections or "人物" in sections:
        persons = sections.get("涉及人物", sections.get("人物", ""))
        slides.append("# 关键人物")
        slides.append("")
        slides.append(persons[:600])
        slides.append("")
        slides.append("---")

    # 判断页
    if "核心判断" in sections or "判断" in sections:
        judgments = sections.get("核心判断", sections.get("判断", ""))
        slides.append("# 核心判断")
        slides.append("")
        slides.append(judgments[:800])
        slides.append("")
        slides.append("---")

    # ldamc 自检页
    if "ldamc" in sections or "LDAMC" in sections:
        ldamc = sections.get("ldamc", sections.get("LDAMC", ""))
        slides.append("# 知识自检 (LDAMC)")
        slides.append("")
        slides.append(ldamc[:600])
        slides.append("")
        slides.append("---")

    # 结论页
    slides.append("# 结论与下一步")
    slides.append("")
    if value_grade:
        slides.append(f"- 价值评级: **{value_grade} 级**")
    slides.append(f"- 来源: {meeting_file.name}")
    slides.append(f"- 知识库版本: {fm.get('version', 'v4.0')}")

    slides_md = "\n".join(slides)

    # 写入
    if output_dir is None:
        output_dir = meeting_file.parent.parent.parent / OUTPUT_DIR_NAME / "slides"
    output_dir.mkdir(parents=True, exist_ok=True)
    slides_path = output_dir / f"{meeting_file.stem}_slides.md"
    slides_path.write_text(slides_md, encoding="utf-8")
    log.info(f"生成 slides: {slides_path.name}", step="output_renderer")
    return str(slides_path)


def _extract_sections(body: str) -> Dict[str, str]:
    """从 body 提取 ## 二级标题段落"""
    sections = {}
    current_title = ""
    current_content = []
    for line in body.split("\n"):
        if line.strip().startswith("## "):
            if current_title:
                sections[current_title] = "\n".join(current_content).strip()
            current_title = line.strip()[3:].strip()
            current_content = []
        else:
            current_content.append(line)
    if current_title:
        sections[current_title] = "\n".join(current_content).strip()
    return sections


# ============ HTML Dashboard ============

DASHBOARD_TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>PJ-102 知识库总览</title>
<style>
:root {
  --bg: #0F1B2D; --panel: #1A2942; --card: #243B5C;
  --text: #E8EEF7; --muted: #8B9BB4; --accent: #4A90E2;
  --gold: #D4A744; --green: #4ECB71; --red: #E74C3C;
  --border: #2D4263;
}
* { margin:0; padding:0; box-sizing:border-box; }
body { font-family: -apple-system, "Segoe UI", "Microsoft YaHei", sans-serif;
       background: var(--bg); color: var(--text); line-height: 1.6; }
.container { max-width: 1200px; margin: 0 auto; padding: 24px; }
header { text-align: center; padding: 32px 0 24px; border-bottom: 1px solid var(--border); }
header h1 { font-size: 28px; color: var(--text); font-weight: 600; }
header .subtitle { color: var(--muted); font-size: 13px; margin-top: 8px; }
header .meta { color: var(--accent); font-size: 12px; margin-top: 12px; }
.stats-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
             gap: 16px; margin: 24px 0; }
.stat-card { background: var(--card); border-radius: 10px; padding: 20px;
             text-align: center; border: 1px solid var(--border); }
.stat-card .num { font-size: 28px; font-weight: 700; color: var(--accent); }
.stat-card .label { font-size: 12px; color: var(--muted); margin-top: 4px; }
section { margin: 32px 0; }
section h2 { font-size: 18px; color: var(--gold); margin-bottom: 16px;
             padding-bottom: 8px; border-bottom: 1px solid var(--border); }
.meeting-list { display: grid; gap: 12px; }
.meeting-card { background: var(--panel); border-radius: 8px; padding: 16px;
                border-left: 3px solid var(--accent); }
.meeting-card .title { font-size: 15px; font-weight: 500; color: var(--text); }
.meeting-card .meta { font-size: 12px; color: var(--muted); margin-top: 6px; }
.grade-A { color: var(--green); font-weight: 600; }
.grade-B { color: var(--gold); font-weight: 600; }
.grade-C { color: var(--muted); }
.entity-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
              gap: 10px; }
.entity-item { background: var(--panel); padding: 10px 14px; border-radius: 6px;
               font-size: 13px; border: 1px solid var(--border); }
.entity-item .name { color: var(--text); font-weight: 500; }
.entity-item .type { color: var(--muted); font-size: 11px; }
footer { text-align: center; color: var(--muted); font-size: 11px;
         padding: 24px 0; border-top: 1px solid var(--border); margin-top: 40px; }
</style>
</head>
<body>
<div class="container">
<header>
  <h1>PJ-102 知识库总览</h1>
  <div class="subtitle">基于 MiniMax-M3 + 12步Pipeline 的会议转写→知识库系统</div>
  <div class="meta">v{{ version }} · 最后更新 {{ updated }} · {{ total }} 个条目</div>
</header>

<div class="stats-grid">
{% for stat in stats %}
<div class="stat-card">
  <div class="num">{{ stat.count }}</div>
  <div class="label">{{ stat.label }}</div>
</div>
{% endfor %}
</div>

<section>
  <h2>📅 会议纪要 ({{ meetings | length }})</h2>
  <div class="meeting-list">
  {% for m in meetings %}
  <div class="meeting-card">
    <div class="title">{{ m.title }}</div>
    <div class="meta">
      {{ m.date }} ·
      <span class="grade-{{ m.value_grade }}">{{ m.value_grade }}级</span> ·
      {{ m.meeting_type }}
      {% if m.entity_id %}· {{ m.entity_id }}{% endif %}
    </div>
  </div>
  {% endfor %}
  </div>
</section>

<section>
  <h2>👥 人物档案 ({{ persons | length }})</h2>
  <div class="entity-grid">
  {% for p in persons %}
  <div class="entity-item">
    <div class="name">{{ p.canonical_name }}</div>
    <div class="type">{{ p.entity_id }} · {% if p.backlinks %}{{ p.backlinks | length }} 反链{% endif %}</div>
  </div>
  {% endfor %}
  </div>
</section>

<section>
  <h2>💡 概念卡片 ({{ concepts | length }})</h2>
  <div class="entity-grid">
  {% for c in concepts[:20] %}
  <div class="entity-item">
    <div class="name">{{ c.title }}</div>
    <div class="type">{% if c.is_merged %}🔀 合并{% else %}📄 单条{% endif %}</div>
  </div>
  {% endfor %}
  {% if concepts | length > 20 %}
  <div class="entity-item"><div class="name">... 还有 {{ concepts | length - 20 }} 个</div></div>
  {% endif %}
  </div>
</section>

<section>
  <h2>⚖️ 判断记录 ({{ judgments | length }})</h2>
  <div class="entity-grid">
  {% for j in judgments[:15] %}
  <div class="entity-item">
    <div class="name">{{ j.title }}</div>
    <div class="type">{{ j.date }} · <span class="grade-{{ j.value_grade }}">{{ j.value_grade }}级</span></div>
  </div>
  {% endfor %}
  {% if judgments | length > 15 %}
  <div class="entity-item"><div class="name">... 还有 {{ judgments | length - 15 }} 个</div></div>
  {% endif %}
  </div>
</section>

<footer>
  PJ-102-LLM-MeetingKB · Karpathy LLM Wiki 方法论落地 ·
  自动生成 by output_renderer.py
</footer>
</div>
</body>
</html>"""


def render_dashboard(cfg: AppConfig = None) -> str:
    """生成 HTML dashboard 总览页

    Returns: html 文件路径
    """
    if not HAS_JINJA2:
        log.warning("jinja2 未安装, 无法生成 dashboard", step="output_renderer")
        return ""
    if cfg is None:
        cfg = AppConfig()
    wiki_root = cfg.paths.wiki_base

    # 扫描所有 wiki 文件
    from index_builder import scan_wiki
    entries = scan_wiki(wiki_root)
    groups = {}
    for e in entries:
        t = e["type"]
        groups.setdefault(t, []).append(e)

    # 统计
    stats = []
    type_labels = {
        "meeting": "📅 会议", "person": "👥 人物", "organization": "🏢 机构",
        "concept": "💡 概念", "judgment": "⚖️ 判断",
        "comparison": "🔍 对比", "scenario": "🎯 场景", "answer": "📝 问答",
    }
    for t in ["meeting", "person", "organization", "concept", "judgment",
              "comparison", "scenario", "answer"]:
        if t in groups:
            stats.append({"label": type_labels.get(t, t), "count": len(groups[t])})
    stats.append({"label": "📦 总计", "count": len(entries)})

    # meetings
    meetings = []
    for e in sorted(groups.get("meeting", []), key=lambda x: x.get("date", ""), reverse=True):
        meetings.append({
            "title": e["title"],
            "date": e.get("date", ""),
            "value_grade": e.get("value_grade", "C"),
            "meeting_type": e.get("type", ""),
            "entity_id": e.get("entity_id", ""),
        })

    # persons (含 backlinks 数)
    persons = []
    for e in groups.get("person", []):
        try:
            fm, _ = parse_frontmatter_and_body(e["file"].read_text(encoding="utf-8"))
        except Exception:
            fm = {}
        persons.append({
            "canonical_name": e.get("canonical_name") or e["title"],
            "entity_id": e.get("entity_id", ""),
            "backlinks": fm.get("backlinks", []),
        })
    persons.sort(key=lambda x: -len(x["backlinks"]))

    # concepts
    concepts = []
    for e in groups.get("concept", []):
        try:
            fm, _ = parse_frontmatter_and_body(e["file"].read_text(encoding="utf-8"))
        except Exception:
            fm = {}
        concepts.append({
            "title": e["title"],
            "is_merged": fm.get("is_merged", False),
        })

    # judgments
    judgments = []
    for e in sorted(groups.get("judgment", []),
                    key=lambda x: x.get("date", ""), reverse=True):
        judgments.append({
            "title": e["title"],
            "date": e.get("date", ""),
            "value_grade": e.get("value_grade", "C"),
        })

    # 渲染
    template = Template(DASHBOARD_TEMPLATE)
    html = template.render(
        version=cfg.version,
        updated=datetime.now().strftime("%Y-%m-%d %H:%M"),
        total=len(entries),
        stats=stats,
        meetings=meetings,
        persons=persons[:21],
        concepts=concepts,
        judgments=judgments,
    )

    output_dir = wiki_root.parent / OUTPUT_DIR_NAME / "dashboard"
    output_dir.mkdir(parents=True, exist_ok=True)
    html_path = output_dir / "dashboard.html"
    html_path.write_text(html, encoding="utf-8")
    log.info(f"生成 dashboard: {html_path}", step="output_renderer")
    return str(html_path)


def render_all_slides(cfg: AppConfig = None) -> List[str]:
    """为所有 meeting 生成 slides"""
    if cfg is None:
        cfg = AppConfig()
    meetings_dir = cfg.paths.wiki_meetings
    if not meetings_dir.exists():
        return []
    paths = []
    for md_file in sorted(meetings_dir.glob("*.md")):
        p = render_meeting_slides(md_file)
        if p:
            paths.append(p)
    return paths


def render_all(cfg: AppConfig = None, formats: List[str] = None) -> dict:
    """主入口: 生成所有格式输出

    Args:
        formats: ["slides", "dashboard"] 默认全部
    """
    if cfg is None:
        cfg = AppConfig()
    if formats is None:
        formats = ["slides", "dashboard"]

    result = {"slides": [], "dashboard": ""}

    if "slides" in formats:
        result["slides"] = render_all_slides(cfg)
    if "dashboard" in formats:
        result["dashboard"] = render_dashboard(cfg)

    return result


# ============ CLI ============

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(
        description="PJ-102 多格式输出 (Karpathy 缺口5)")
    parser.add_argument("--format", choices=["slides", "dashboard", "all"],
                       default="all", help="输出格式")
    parser.add_argument("--meeting", default=None,
                       help="指定 meeting 文件 (仅 slides)")
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args()

    cfg = AppConfig()

    if args.meeting:
        p = render_meeting_slides(Path(args.meeting))
        print(f"slides: {p}")
    elif args.format == "slides":
        paths = render_all_slides(cfg)
        print(f"\n生成 {len(paths)} 份 slides:")
        for p in paths:
            print(f"  • {p}")
    elif args.format == "dashboard":
        p = render_dashboard(cfg)
        print(f"dashboard: {p}")
    else:
        result = render_all(cfg)
        print(f"\n{'=' * 50}")
        print(f"📊 多格式输出完成")
        print(f"{'=' * 50}")
        print(f"slides: {len(result['slides'])} 份")
        print(f"dashboard: {result['dashboard']}")
