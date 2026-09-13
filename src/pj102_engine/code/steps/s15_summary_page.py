"""
S15: 摘要锚点页生成器 (Karpathy LLM Wiki · 覆盖层) - W2 T2.1

每个源文件一张锚点页 (wiki/Summaries/摘要_{date}_{主题}.md):
  - s3 五要素 + quantitative_params (来自 step 缓存, 0 LLM)
  - 实体 wikilink 化 (优先 s6 实体名匹配已有 wiki 页, 兜底反向索引)
  - 会议页/场景页回溯链接 (按 content_hash / source_ref 匹配)
  - 建议问题 (规则式, NotebookLM 借鉴, 不杜撰内容)

入口: s15_summary_page(state, cfg)
  state 需含: sample(文件名)/content_hash/s1(可选)/s3(可选)/s6(可选)/file_type(可选)/date(可选)
  s3 缺失时抛 S15MissingS3 (由调用方决定是否补跑 LLM)
"""
import json
import re
import sys
from datetime import date as _date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from jinja2 import Environment, FileSystemLoader, StrictUndefined

TEMPLATE_DIR = Path(__file__).parent.parent.parent / "config" / "templates"


class S15MissingS3(RuntimeError):
    """s3 摘要数据缺失, 调用方需补跑 LLM"""


def _yq(s: str) -> str:
    """YAML 安全双引号字符串 (血泪陷阱 T4: 内容可能含英文双引号)"""
    return json.dumps(str(s), ensure_ascii=False)


def _sanitize_filename(s: str) -> str:
    """Windows + Obsidian 文件名非法字符清洗"""
    return re.sub(r'[/\\:*?"<>|\[\]#^]', "", s).strip()


def _topic_from_title(title: str, limit: int = 20) -> str:
    return _sanitize_filename(title)[:limit].rstrip(" @_-.，。、；;：:") or "未命名"


def _frontmatter_of(text: str) -> dict:
    """极简 frontmatter 提取 (只要 content_hash / source / source_ref)"""
    fm = {}
    m = re.match(r"^---\s*\n(.*?)\n---", text, flags=re.DOTALL)
    if not m:
        return fm
    for line in m.group(1).splitlines():
        kv = re.match(r'^([A-Za-z_]+)\s*:\s*"?([^"\n]*)"?\s*$', line)
        if kv:
            fm[kv.group(1)] = kv.group(2).strip()
    return fm


def _find_meeting_link(wiki_root: Path, content_hash: str):
    """按 frontmatter content_hash 找本源的会议页"""
    meetings = wiki_root / "Meetings"
    if not meetings.exists():
        return None
    for f in meetings.glob("*.md"):
        try:
            fm = _frontmatter_of(f.read_text(encoding="utf-8", errors="ignore")[:1500])
        except Exception:
            continue
        if fm.get("content_hash") == content_hash or fm.get("file_hash") == content_hash:
            return f"[[Meetings/{f.stem}|{f.stem}]]"
    return None


def _find_scenario_links(wiki_root: Path, source_file: str):
    """按 frontmatter source_ref 找本源的场景页"""
    out = []
    sc = wiki_root / "Knowledge" / "Scenarios"
    if not sc.exists():
        return out
    for f in sorted(sc.glob("*.md")):
        try:
            head = f.read_text(encoding="utf-8", errors="ignore")[:1500]
        except Exception:
            continue
        fm = _frontmatter_of(head)
        if fm.get("source_ref") == source_file or source_file in head[:1500]:
            out.append(f"[[Knowledge/Scenarios/{f.stem}|{f.stem}]]")
    return out[:5]


def _entity_stems(wiki_root: Path):
    """全部实体页 stem 列表 (Persons + Organizations)"""
    stems = []
    for sub in ("Entities/Persons", "Entities/Organizations"):
        d = wiki_root / sub
        if d.exists():
            stems.extend(f.stem for f in d.glob("*.md"))
    return stems


def _resolve_entities_from_s6(s6: dict, stems, source_date: str):
    """pipeline 路径: s6 实体名 → 匹配已有 wiki 页 stem
    匹配规则: 精确 stem == 名字; 否则 stem 以 名字（ 开头且括号内日期 == 本源日期;
    再否则同名前缀取最近日期页 (备选, 保守不误链: 仅当 stem 形如 名字（YYYY-MM-DD）)"""
    links, plain = [], []
    names = []
    for p in s6.get("persons", []):
        if isinstance(p, dict) and p.get("name"):
            names.append(p["name"])
    for o in s6.get("organizations", []):
        if isinstance(o, dict) and o.get("name"):
            names.append(o["name"])
    for name in dict.fromkeys(names):  # 去重保序
        target = None
        if name in stems:
            target = name
        else:
            dated = [s for s in stems
                     if s.startswith(f"{name}（") and s.endswith("）")
                     and re.match(r".*（\d{4}-\d{2}-\d{2}）$", s)]
            same_date = [s for s in dated if source_date and source_date in s]
            if same_date:
                target = sorted(same_date)[-1]
            elif dated:
                continue  # 有同名实体但非本源日期 → 不硬链, 降级纯文本
        if target:
            links.append(f"[[{target}]]")
        else:
            plain.append(name)
    return links, plain


def _resolve_entities_from_reverse_index(wiki_root: Path, source_file: str):
    """backfill 路径(旧样本无 s6): 扫实体页内容引用了本源文件名的页面"""
    links = []
    for sub in ("Entities/Persons", "Entities/Organizations"):
        d = wiki_root / sub
        if not d.exists():
            continue
        for f in sorted(d.glob("*.md")):
            try:
                text = f.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue
            if source_file in text:
                links.append(f"[[{f.stem}]]")
    return links[:15]


def s15_summary_page(state: dict, cfg) -> dict:
    """生成一张摘要锚点页。返回 {"pages": [绝对路径], "entities": n, ...}"""
    wiki_root = Path(cfg.paths.wiki_base)
    out_dir = wiki_root / "Summaries"
    out_dir.mkdir(parents=True, exist_ok=True)

    sample_file = state.get("sample") or state.get("filename") or ""
    content_hash = state.get("content_hash", "")
    s1 = state.get("s1") or {}
    s3 = state.get("s3")
    if not s3 or not isinstance(s3, dict) or s3.get("one_sentence") in (None, "未提取"):
        raise S15MissingS3(f"s3 摘要缺失: {sample_file}")

    source_date = (state.get("date") or s1.get("date") or "")[:10]
    file_type = state.get("file_type") or ""
    title = s1.get("title") or _title_from_filename(sample_file)
    topic = _topic_from_title(title)

    # 实体解析: s6 优先, 兜底反向索引
    stems = _entity_stems(wiki_root)
    s6 = state.get("s6") or {}
    if isinstance(s6, dict) and (s6.get("persons") or s6.get("organizations")):
        entity_links, _plain = _resolve_entities_from_s6(s6, stems, source_date)
    else:
        entity_links = _resolve_entities_from_reverse_index(wiki_root, sample_file)

    meeting_link = _find_meeting_link(wiki_root, content_hash)
    scenario_links = _find_scenario_links(wiki_root, sample_file)
    qp = s3.get("quantitative_params") or []
    if not isinstance(qp, list):
        qp = []

    fname = f"摘要_{source_date}_{topic}.md"
    target = out_dir / fname
    n = 2
    while target.exists():  # 同名冲突加 (2), 沿用既有约定
        target = out_dir / f"摘要_{source_date}_{topic}（{n}）.md"
        n += 1

    env = Environment(loader=FileSystemLoader(str(TEMPLATE_DIR)),
                      undefined=StrictUndefined,
                      trim_blocks=True, lstrip_blocks=True)
    # Jinja2 默认 {{ }} 与 frontmatter 无冲突
    tpl = env.get_template("summary_page.md.j2")
    rendered = tpl.render(
        title_yaml=_yq(f"摘要 {source_date} {topic}"),
        source_file_yaml=_yq(sample_file),
        source_file=sample_file,
        source_date=source_date or "未知日期",
        file_type=file_type or "unknown",
        source_hash=content_hash,
        entities_yaml=", ".join(_yq(l) for l in entity_links),
        generated_at=str(_date.today()),
        topic=topic,
        topics=state.get("s9", {}).get("topics", []),
        meta_type=state.get("s9", {}).get("meta_type", "reference"),
        one_sentence=s3.get("one_sentence", "未提取"),
        background=s3.get("background", "未提取"),
        problem=s3.get("problem", "未提取"),
        method=s3.get("method", "未提取"),
        outcome=s3.get("outcome", "未提取"),
        insight=s3.get("insight", "未提取"),
        quantitative_params=qp,
        entity_links=entity_links,
        meeting_link=meeting_link,
        scenario_links=scenario_links,
    )
    target.write_text(rendered, encoding="utf-8")
    return {
        "pages": [str(target)],
        "page": target.name,
        "entities": len(entity_links),
        "meeting_linked": bool(meeting_link),
        "scenarios": len(scenario_links),
    }


def _title_from_filename(filename: str) -> str:
    """20230907_083619万联网梁老师到访深度老板高管参加_原文.md → 万联网梁老师到访深度老板高管参加"""
    base = re.sub(r"_原文\.md$", "", filename)
    base = re.sub(r"^\d{8}_\d{6}", "", base)
    base = base.lstrip("@ ")
    return base.strip() or filename
