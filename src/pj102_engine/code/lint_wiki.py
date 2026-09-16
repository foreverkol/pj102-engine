"""
v3.0 lint_wiki.py - 7 维健康巡检 + v7.0 §8.1 必填字段检查
v1.1 (P1/T-P1.2, 2026-09-09): 必填字段分型 schema 校准 —— 按 s12 实际产出字段
  按类型定义 required (person.name / concept.name|title any-of / scenario 正文日期不查),
  WARN 级 v7.0 理想字段降为 LINT_STRICT=1 可选; _SOURCE_FIELDS 增补 source_files;
  Queries/ 豁免缺来源维度 (L2 综合产出设计口径)。

7 维度:
  1. graph_orphans     — 遍历断点: 无 inbound link 的页面 (T-P5.4 由 orphan_pages 更名, 消除 D7 口径分歧)
  2. dead_links         — [[wikilink]] 指向不存在的页面
  3. missing_sources    — frontmatter 缺 source_ref
  4. contradiction_pending — Status: Disputed 待 verified_by
  5. stale_pages        — >90 天未更新
  6. unindexed          — 在 WIKI/ 但没在 index.md
  7. emoji_garbled      — frontmatter emoji 解析异常
  12. content_orphans   — 密度缺口: 可遍历但正文有效行数过少 (T-P5.4 新增, 与维度 1 语义互补:
                          1 管"进得来吗"(图结构), 12 管"来了有东西看吗"(内容密度))

v7.0 §8.1 必填字段检查(集成进维度 3):
  - meeting: subtype + publishability + reusable_for + ldamc + source_ref
  - person: entity_id + thinking_framework + values_beliefs + decision_style + emotional_tone
  - judgment: topic_key + evidence_chain + confidence_rationale
  - organization: entity_id + org_name + org_type + business_model + cooperation_status
  - scenario: theme + customer + pain_point + offering + value_capture + channel + key_resources

返回 JSON report,feishu_lint_alert 可直接读
"""

import os
import re
import json
import datetime
from pathlib import Path
from typing import Dict, List
from collections import defaultdict


# v1.1 分型 schema (P1/T-P1.2, 2026-09-09): 必填字段按 s12 实际产出字段分型定义
# 根因: v7.0 口径要求 person/org 用 title、scenario 有 theme/customer 等 7 字段 —— s12 从未
# 实现该 schema (person/org 实际用 name, scenario 七要素在正文), 导致 ~390 假阳性。
# 校准依据: 2026-09-09 23:45 全库 frontmatter 覆盖率实测 (105 person / 100 org / 143 concept /
# 111 scenario / 53 judgment / 17 meeting 页, 字段出现率 100% 的才进 required)。
# 元组语义 = any-of (任一存在即可, 兼容新旧两代 concept 页 schema)。
# source_meeting/source_hash 要求基于 T-P1.1 回填后语义: org 54 页 W2 期生成时未写 source,
# 回填前会真实报红 (真阳性, 非假阳性)。
REQUIRED_FIELDS = {
    "meeting": ["title", "date", "status_stage", "value_grade", "content_hash"],
    "person": ["name", "canonical_name", "relation_to_wang", "status_stage",
               "date", "source_meeting"],
    "organization": ["name", "canonical_name", "entity_id", "org_type",
                     "business_model", "cooperation_status", "status_stage",
                     "date", "source_meeting", "source_hash"],
    "concept": [("name", "title"), ("definition", "concept_name"), "status_stage",
                ("source_meeting", "source_files")],
    "judgment": ["title", "author", "date", "status_stage", "source_meeting"],
    "scenario": ["scenario_id", "source_ref", "status_stage", "created", "updated"],
    "comparison": ["date", "status_stage", "source_meeting"],
    "query": ["question", "query_date", "status_stage", "citations_count"],
}

# v7.0 理想字段 (s12 未实现的愿望 schema)。默认不参与维度 8 计数 (386 条 WARN 全为噪声),
# 仅 LINT_STRICT=1 时输出, 供后续 s12 升级时对照。
RECOMMENDED_FIELDS = {
    "person": ["thinking_framework", "values_beliefs",
               "decision_style", "emotional_tone"],
    "judgment": ["topic_key", "evidence_chain", "confidence_rationale"],
    "organization": ["org_name", "org_type"],
    "scenario": ["theme", "customer", "pain_point", "offering",
                 "value_capture", "channel", "key_resources"],
}


def lint_wiki(wiki_root: Path) -> Dict[str, List[str]]:
    """主入口:返回 7 维报告"""
    wiki_root = Path(wiki_root)
    if not wiki_root.exists():
        return {"error": [f"wiki root 不存在: {wiki_root}"]}

    md_files = list(wiki_root.rglob("*.md"))
    md_files = [f for f in md_files
                if f.name not in ("index.md", "log.md")
                and not f.name.startswith("log.legacy")]

    return {
        "1_graph_orphans": _check_orphans(md_files),  # T-P5.4: 原 1_orphan_pages, 语义=遍历断点 (无 inbound link)
        "2_dead_links": _check_dead_links(md_files),
        "3_missing_sources": _check_missing_sources(md_files),
        "4_contradiction_pending": _check_contradiction_pending(md_files),
        "5_stale_pages": _check_stale_pages(md_files, threshold_days=90),
        "6_unindexed": _check_unindexed(md_files, wiki_root),
        "7_emoji_garbled": _check_emoji_garbled(md_files),
        "8_required_field_violations": _check_required_fields(md_files),  # v7.0 增强
        "9_tag_violations": _check_tag_violations(md_files),  # W4: 词表合规
        "10_tag_coverage": _check_tag_coverage(md_files),  # W4: 标签覆盖率
        "11_entity_fragments": _check_entity_fragments(md_files, wiki_root),  # P2: 同名分片
        "12_content_orphans": _check_content_orphans(md_files),  # T-P5.4: 语义=密度缺口 (可遍历但内容稀薄)
        "13_stale_backlinks": _check_stale_backlinks(wiki_root),  # D-32: 僵尸反向链接 (裸路径指向已归档/改名页)
        "14_dup_h2": _check_dup_h2(md_files),  # D-42: 同名 H2 重复 (合并类操作的盲区)
        "15_multi_page_entity": _check_multi_page_entity(md_files, wiki_root),  # D-43: 同 entity_id 多页
    }


# ============ 维度 14: dup_h2 (D-42 接线 2026-09-16) ============


def _check_dup_h2(md_files: List[Path]) -> List[str]:
    """实体页正文**同名 H2 重复** —— 合并类操作的盲区维度。

    为什么单独成维
    --------------
    D-32 / D-40 的合并装置把被并页的**全套骨架 H2**（`🏢 机构信息` / `📅 出现会议` /
    `📑 元信息` …）原样追加进规范主页 → 页面出现**重复同名小节**。
    而既有 13 维**无一覆盖**：`2_dead_links` 只数 `[[双链]]`，`11_entity_fragments`
    只按页名基名判分片。（实测 2026-09-16：12 页中招、全部源于合并，
    标尺却全程显示"零回归" → 假阴性。）

    判据与 `polish_pages._h2_norm` **同源**：剥离尾部计数后缀 `(N)` / `(N 次出现)`
    —— 即 `## 📅 出现会议 (11)` 与 `## 📅 出现会议` 视为同名。
    可见性修复走 `scripts/fix_dup_h2_20260915.py`。
    """
    try:
        from polish_pages import _h2_norm                      # 一处实现
    except Exception:                                          # 引擎目录未在 path 上
        def _h2_norm(t: str) -> str:
            return re.sub(r"\s*\(\d+(?:\s*次出现)?\)$", "", t.strip())

    out = []
    for f in md_files:
        try:
            body = _strip_frontmatter(f.read_text(encoding="utf-8", errors="ignore"))
        except Exception:
            continue
        h2 = [ln.strip() for ln in body.split("\n") if re.match(r"^## (?!#)", ln.strip())]
        cnt: dict = {}
        for t in h2:
            k = _h2_norm(t)
            cnt[k] = cnt.get(k, 0) + 1
        dup = {k: n for k, n in cnt.items() if n > 1}
        if dup:
            out.append(f"{f.as_posix()}: "
                       + ", ".join(f"{k} ×{n}" for k, n in sorted(dup.items())))
    return out


# ============ 维度 15: multi_page_entity (D-43 接线 2026-09-16) ============


def _load_known_multi_page(wiki_root: Path = None) -> set:
    """同 id 多页的**豁免台账**（实例数据外置，同 `known_orphans.json` 套路）。

    读取 <project_root>/system/state/known_multi_page_entities.json（字符串数组，
    元素为 `entity_id`）。**只有"刻意设计"的族才可入册** —— 当前 T2 时间分页
    尚未入册（仍属待裁决缺陷，须持续暴露）。引擎发行版不内置任何实例数据。
    """
    if not wiki_root:
        return set()
    try:
        p = Path(wiki_root).parent / "system" / "state" / "known_multi_page_entities.json"
        return {str(x).strip() for x in json.loads(p.read_text(encoding="utf-8"))
                if str(x).strip()}
    except Exception:
        return set()


def _check_multi_page_entity(md_files: List[Path], wiki_root: Path = None) -> List[str]:
    """**同一 `entity_id` 对应多张实体页** —— 引擎已认定同实体，wiki 却仍是多页。

    为什么单独成维
    --------------
    `entity_id` 是引擎级身份权威锚点；同 id 多页意味着**页面层与身份层脱钩**：
    引用会被分散到多页、backlinks 各记一半、读者看到的是同一个人的几个切片。
    既有 13 维同样无覆盖（`11_entity_fragments` 只在**页名基名**相同才报）。

    与 `11_entity_fragments` 的分工
      · 11 维：**页名基名相同** → 抓"命名分片"（`X` / `X_abc123` / `X（2024-01-01）`）
      · 15 维：**页名完全不同但 id 相同** → 抓"身份脱钩"（`千问(Qwen)` / `阿里千问办公`）
    二者互补，可同时命中。

    豁免：`known_multi_page_entities.json`（仅收录**刻意设计**的族，如 T2 时间分页）。
    """
    known = _load_known_multi_page(wiki_root)
    groups: dict = {}
    for f in md_files:
        rel = f.as_posix()
        if "/Entities/" not in rel:
            continue
        fm = _parse_frontmatter(f)
        eid = str(fm.get("entity_id") or "").strip()
        if not eid or eid in known:
            continue
        groups.setdefault(eid, []).append(f.stem)
    out = []
    for eid, pages in sorted(groups.items()):
        if len(pages) > 1:
            out.append(f"{eid}: {len(pages)} 页 " + ", ".join(sorted(pages)))
    return out


# ============ 维度 13: stale_backlinks (D-32 接线 2026-09-16) ============


def _check_stale_backlinks(wiki_root: Path) -> List[str]:
    """backlinks 裸路径指向不存在页面 —— **`2_dead_links` 的盲区**。

    为什么单独成维
    --------------
    合并/改名时，别的页 frontmatter 里 `backlinks:` 的条目是**裸相对路径**
    （`- Entities/Persons/王老师本人.md`），既不是 `[[双链]]` 也不带显示名，
    因此 `2_dead_links` **一条都抓不到**。实测 D-38/D-40 历轮累积 **311 条**
    僵尸条目，标尺全程显示"零回归"。

    计数的目标是"指向已不存在页面"的条目本身（不是宿主页），便于直接定位修复。
    """
    try:
        from ref_rewrite import stale_backlinks
    except Exception:                                  # 引擎目录未在 path 上
        return []
    return stale_backlinks(wiki_root)


# ============ 维度 11: entity_fragments (P2 T-P2.2) ============

_FRAG_RE = re.compile(r"（\d{4}-\d{2}-\d{2}）$|（\d+）$")


def _load_manual_review(wiki_root: Path) -> set:
    """疑似重名人工审查名单 — 外置为实例数据文件 (v2.2.4, 分叉 #2 清账)。

    读取 <project_root>/system/state/manual_entities.json (字符串数组)。
    引擎发行版不内置任何实例人名; 文件缺失/损坏时返回空集 (全部按规则判分片)。
    与 system/state/known_orphans.json 同套路: 代码同构, 数据分离, 实例自维护。
    """
    try:
        p = Path(wiki_root).parent / "system" / "state" / "manual_entities.json"
        arr = json.loads(p.read_text(encoding="utf-8"))
        return {str(x).strip() for x in arr if str(x).strip()}
    except Exception:
        return set()


def _check_entity_fragments(md_files: List[Path], wiki_root: Path = None) -> List[str]:
    """同一人物/机构应只有一个规范页 (一人一页约定, P2 v1.3)。

    按去掉日期/(n)后缀的基名归组, 组内页数 >1 即分片 (人工审查组除外)。
    """
    MANUAL = _load_manual_review(wiki_root) if wiki_root else set()  # 人工审查名单(实例维护; 命中组不判分片)
    groups = {}
    for f in md_files:
        rel = f.as_posix()
        if ("/Entities/Persons/" not in rel and "/Entities/Organizations/" not in rel
                and "/Knowledge/Concepts/" not in rel):
            continue
        stem = f.stem
        base = stem
        while True:
            nb = _FRAG_RE.sub("", base)
            if nb == base:
                break
            base = nb
        groups.setdefault((f.parent.name, base), []).append(f)
    frags = []
    for (sub, base), ps in sorted(groups.items()):
        if len(ps) > 1 and base not in MANUAL:
            frags.append(f"{sub}/{base}: {len(ps)} 页分片 "
                        + ", ".join(p.name for p in ps))
    return frags


# ============ 维度 1: orphan_pages ============

def _norm_target(link: str) -> str:
    """wikilink target 归一化 → basename (Obsidian 解析规则)

    库中链接多为带路径形式 [[Entities/Persons/主理人|主理人]],
    Obsidian 按 basename 解析到唯一匹配文件, 故比对用 basename。
    (W1-T0.1 校准: 此前用完整路径 vs 纯文件名比对导致 894 假阳性死链)
    """
    return link.strip().rstrip("/").split("/")[-1]


def _check_orphans(md_files: List[Path]) -> List[str]:
    inbound = defaultdict(int)
    for f in md_files:
        try:
            for link in _extract_wikilinks(f.read_text(encoding="utf-8", errors="ignore")):
                inbound[_norm_target(link)] += 1
        except Exception:
            pass
    orphans = []
    for f in md_files:
        name = f.stem
        # 自链不计
        if name in ("index", "log"):
            continue
        # W2-T2.2: Summaries/ 摘要锚点页豁免 —— 设计上从 index 进入的导航枢纽
        # (出链丰富、index 必收录; 内容页回链属 W3 增量更新范畴)
        if "Summaries" in f.parts:
            continue
        # T-P5.3: Queries/ 问答回流页豁免 —— 与 Summaries 同口径 (设计上从 index 进入的
        # 检索出口, citations 出链丰富; 内容页反向引用 Query 页无语义, 强挂属噪声)
        if "Queries" in f.parts:
            continue
        if inbound[name] == 0:
            orphans.append(str(f))
    return orphans


# ============ 维度 12: content_orphans (T-P5.4, 密度缺口) ============

_CONTENT_MIN_LINES = 4  # 正文有效行阈值: 去空行/纯标题/纯分隔线后 <4 行视为密度缺口


def _strip_frontmatter(txt: str) -> str:
    m = re.match(r"^((?:>[^\n]*\n)+(?:\s*\n)*)---\r?\n.*?\r?\n---\r?\n?", txt, re.S)
    if m:
        return txt[m.end():]
    m = re.match(r"^---\r?\n.*?\r?\n---\r?\n?", txt, re.S)
    return txt[m.end():] if m else txt


def _check_content_orphans(md_files: List[Path]) -> List[str]:
    """密度缺口: 页面可遍历 (或由结构豁免) 但正文有效内容过少。

    口径 (D7 消解):
    - graph_orphans (维度1) = 图结构断点 → "链接进不来"
    - content_orphans (维度12) = 内容密度缺口 → "进来了没东西看"
    有效行 = 非空 && 非纯 markdown 标题 && 非纯分隔线 && 非纯 wikilink 导航行。
    豁免: Summaries/ 锚点导航页 (设计如此, 与维度1豁免口径一致)。
    """
    orphans = []
    for f in md_files:
        if "Summaries" in f.parts:
            continue
        try:
            body = _strip_frontmatter(f.read_text(encoding="utf-8", errors="ignore"))
        except Exception:
            continue
        effective = 0
        for ln in body.splitlines():
            s = ln.strip()
            if not s:
                continue
            if s.startswith("#") and len(s.replace("#", "").strip()) == 0:
                continue  # 纯 "#" 分隔
            if set(s) <= {"-", ">", " ", "#", "|", "="}:
                continue  # 分隔线/空表头等符号行
            effective += 1
            if effective >= _CONTENT_MIN_LINES:
                break
        if effective < _CONTENT_MIN_LINES:
            orphans.append(str(f))
    return orphans


# ============ 维度 2: dead_links ============

def _check_dead_links(md_files: List[Path]) -> List[str]:
    stems = {f.stem for f in md_files}
    dead = []
    for f in md_files:
        try:
            text = f.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        for link in _extract_wikilinks(text):
            if _norm_target(link) not in stems:
                dead.append(f"{f.name} -> [[{link}]]")
    return dead


# ============ 维度 3: missing_sources ============

# W1-T0.1 校准: 库中实际字段名含 source_meeting/source_hash (s12 产出),
# 此前仅认 source/source_ref 导致 331 假阳性
# P1/T-P1.1 校准: 增补 source_files (concept_*_merged 页合并来源清单, 复数形式)
_SOURCE_FIELDS = ("source", "source_ref", "source_meeting", "source_hash",
                  "source_file", "source_files")


def _check_missing_sources(md_files: List[Path]) -> List[str]:
    """检查 frontmatter 缺 source(兼容 s12 实际字段名)

    P1 口径豁免: Queries/ 页是 L2 综合问答产出, 引用的是 wiki 内页 (citations),
    不直接编译自 L0 源文件 —— 与 Meetings 页同属设计口径, 不纳入缺来源维度。
    """
    missing = []
    for f in md_files:
        if "Queries" in f.parts:
            continue  # 设计口径豁免 (L2 综合产出)
        fm = _parse_frontmatter(f)
        if fm.get("type") and not any(fm.get(k) for k in _SOURCE_FIELDS):
            missing.append(str(f))
    return missing


# ============ 维度 4: contradiction_pending ============

def _check_contradiction_pending(md_files: List[Path]) -> List[str]:
    pending = []
    for f in md_files:
        try:
            text = f.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        if "Status: Disputed" in text and "<!-- verified_by" not in text:
            pending.append(str(f))
    return pending


# ============ 维度 5: stale_pages ============

def _check_stale_pages(md_files: List[Path], threshold_days: int = 90) -> List[str]:
    """检查 >90 天未更新(兼容 generated_at/updated/created)"""
    today = datetime.date.today()
    stale = []
    for f in md_files:
        fm = _parse_frontmatter(f)
        # 兼容 s12 的 generated_at 和 v7.0 的 updated
        updated_str = fm.get("updated") or fm.get("generated_at") or fm.get("created")
        if not updated_str:
            continue
        try:
            # generated_at 格式 "2026-09-07", updated 可能是 ISO
            updated_str = str(updated_str).split("T")[0].strip()
            updated = datetime.date.fromisoformat(updated_str)
            if (today - updated).days > threshold_days:
                stale.append(str(f))
        except (ValueError, TypeError):
            continue
    return stale


# ============ 维度 6: unindexed ============

def _check_unindexed(md_files: List[Path], wiki_root: Path) -> List[str]:
    index_file = wiki_root / "index.md"
    if not index_file.exists():
        # 没 index.md,全部 unindexed
        return [str(f.relative_to(wiki_root)) for f in md_files]
    try:
        index_text = index_file.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return [str(f.relative_to(wiki_root)) for f in md_files]
    # W1-T0.1 校准: 从 index.md 提取 wikilink target 的 basename 集合
    # (此前用相对路径字符串包含匹配, 与 wikilink 格式不符导致 458 假阳性)
    indexed = {_norm_target(l) for l in _extract_wikilinks(index_text)}
    unindexed = []
    for f in md_files:
        if f.stem not in indexed:
            unindexed.append(str(f.relative_to(wiki_root)))
    return unindexed


# ============ 维度 7: emoji_garbled ============

EMOJI_RE = re.compile(
    "[\U0001F600-\U0001F64F\U0001F300-\U0001F5FF"
    "\U0001F680-\U0001F6FF\U0001F1E0-\U0001F1FF]+",
    flags=re.UNICODE,
)


def _check_emoji_garbled(md_files: List[Path]) -> List[str]:
    garbled = []
    for f in md_files:
        try:
            text = f.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        # 检测 "Status: Disputed" 但有乱码(如 ?Status: Disputed?)
        if "Status: Disputed" in text and "?" in text[:200]:
            garbled.append(str(f))
        # 检测双冒号乱码
        if "::" in text and "Status" in text:
            garbled.append(str(f))
    return garbled


# ============ 维度 8: required_field_violations(v7.0 §8.1) ============

def _check_required_fields(md_files: List[Path]) -> List[str]:
    """v1.1 分型必填字段检查 (T-P1.2)

    - error 级: 分型 schema (s12 实际产出字段; 元组 = any-of)
    - warning 级: v7.0 理想字段, 仅 LINT_STRICT=1 时输出 (默认静默, 386 条假阳性噪声)
    """
    import os
    strict = os.environ.get("LINT_STRICT", "") == "1"
    violations = []
    for f in md_files:
        fm = _parse_frontmatter(f)
        page_type = fm.get("type")
        if not page_type:
            continue
        # error 级: 分型必填 (元组 = any-of)
        required = REQUIRED_FIELDS.get(page_type)
        if required:
            missing = []
            for k in required:
                if isinstance(k, tuple):
                    if not any(fm.get(x) for x in k):
                        missing.append("/".join(k))
                elif not fm.get(k):
                    missing.append(k)
            if missing:
                violations.append(
                    f"ERROR: {f.name} [{page_type}]: missing {missing}")
        # warning 级: v7.0 理想字段 (仅 strict 模式)
        if strict:
            recommended = RECOMMENDED_FIELDS.get(page_type)
            if recommended:
                missing = [k for k in recommended if not fm.get(k)]
                if missing:
                    violations.append(
                        f"WARN:  {f.name} [{page_type}]: missing {missing}")
    return violations


# ============ Helpers ============

def _extract_wikilinks(text: str) -> List[str]:
    """[[link]] 或 [[link|alias]] 提取
    W2-T2.0: 先剥离行内代码 `...` 与代码块 ```...``` ——
    文档中举例说明链接格式（如 concept_*_merged 页的 [[Meetings/...]]）不应算真链接"""
    stripped = re.sub(r"```.*?```", " ", text, flags=re.DOTALL)
    stripped = re.sub(r"`[^`\n]*`", " ", stripped)
    return re.findall(r"\[\[([^\[\]|]+?)(?:\|[^\[\]]+?)?\]\]", stripped)


def _parse_frontmatter(md_file: Path) -> dict:
    """简易 YAML frontmatter 解析(支持嵌套 indent block 如 ldamc)

    v1.1 (T-P1.2) 修复: 块式列表 (- item) 此前被解析为空 dict → source_files /
    backlinks / source_dates 等字段全部失真为 falsy, 造成缺来源/必填字段误报。
    现按 YAML 语义收集为 list。"""
    if not md_file.exists():
        return {}
    try:
        text = md_file.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return {}
    if not text.startswith("---"):
        return {}
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}
    fm = {}
    last_key = None

    for line in parts[1].split("\n"):
        # 跳过空行和注释
        if not line.strip() or line.strip().startswith("#"):
            continue
        # 计算缩进
        stripped = line.lstrip(" ")
        indent = len(line) - len(stripped)

        if indent == 0 and not stripped.startswith("-") and ":" in stripped:
            # 顶层字段
            k, v = stripped.split(":", 1)
            k = k.strip()
            v = _parse_value(v.strip())
            fm[k] = v if v else None  # None = 块起点(dict 或 list, 由子行决定)
            last_key = k
        elif last_key is not None and stripped.startswith("-"):
            # 块式列表项 (v1.1 修复: 此前被静默丢弃; YAML 允许列表项与父键同级零缩进)
            item = stripped[1:].strip().strip("'\"")
            cur = fm.get(last_key)
            if cur is None and item:
                fm[last_key] = [item]
            elif isinstance(cur, list) and item:
                cur.append(item)
        elif last_key is not None and indent > 0 and ":" in stripped:
                # 嵌套 dict 字段 (如 ldamc.lost)
                k2, v2 = stripped.split(":", 1)
                cur = fm.get(last_key)
                if cur is None:
                    cur = {}
                    fm[last_key] = cur
                if isinstance(cur, dict):
                    cur[k2.strip()] = _parse_value(v2.strip())

    return fm


def _parse_value(v: str):
    """解析单值:list / string / number"""
    if not v:
        return ""
    if v.startswith("[") and v.endswith("]"):
        return [x.strip().strip("'\"") for x in v[1:-1].split(",") if x.strip()]
    if (v.startswith("'") and v.endswith("'")) or \
       (v.startswith('"') and v.endswith('"')):
        return v[1:-1]
    return v


# ============ 维度 9/10: W4 三轴标签合规 + 覆盖率 ============

def _load_taxonomy() -> dict:
    """懒加载 taxonomy.yaml（词表单点配置）"""
    tax_path = Path(__file__).parent.parent / "config" / "taxonomy.yaml"
    if not tax_path.exists():
        return {}
    try:
        import yaml
        return yaml.safe_load(tax_path.read_text(encoding="utf-8")) or {}
    except Exception:
        return {}


def _fm_of(text: str) -> str:
    m = re.match(r"^((?:>[^\n]*\n)+(?:\s*\n)*)---\r?\n(.*?)\r?\n---", text, re.S)
    if m:
        return m.group(2)
    m = re.match(r"^---\r?\n(.*?)\r?\n---", text, re.S)
    return m.group(1) if m else ""


def _parse_topics_field(fm: str) -> list:
    """解析 topics 字段, 兼容内联式 [a, b] 与块式（backlink_builder YAML 往返产物）"""
    m = re.search(r"^topics:\s*\[(.*?)\]", fm, re.M)
    if m:
        return [t.strip().strip("'\"") for t in m.group(1).split(",") if t.strip()]
    m = re.search(r"^topics:\s*\n((?:\s+-\s.*\n?)+)", fm, re.M)
    if m:
        return [ln.strip().lstrip("-").strip().strip("'\"")
                for ln in m.group(1).splitlines() if ln.strip()]
    return []


def _check_tag_violations(md_files: List[Path]) -> List[str]:
    """W4: 孤儿标签 — topics/meta_type/stance 值不在词表内报警"""
    tax = _load_taxonomy()
    if not tax:
        return []
    t_vals = set(tax.get("topic", {}).get("values", []))
    m_vals = set(tax.get("meta", {}).get("values", []))
    s_vals = set(tax.get("stance", {}).get("values", [])) | {"unlabeled"}
    violations = []
    for f in md_files:
        try:
            fm = _fm_of(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not fm:
            continue
        topics = _parse_topics_field(fm)
        bad = [t for t in topics if t not in t_vals]
        if bad:
            violations.append(f"{f.name}: topics 词表外值 {bad}")
        m = re.search(r"^meta_type:\s*(\S+)", fm, re.M)
        if m and m.group(1) not in m_vals:
            violations.append(f"{f.name}: meta_type 词表外值 {m.group(1)}")
        m = re.search(r"^stance:\s*(\S+)", fm, re.M)
        if m and m.group(1) not in s_vals:
            violations.append(f"{f.name}: stance 词表外值 {m.group(1)}")
    return violations


def _check_tag_coverage(md_files: List[Path]) -> List[str]:
    """W4: 标签覆盖率 — topics 缺失率 >20% 警告（返回警告列表, 空为健康）"""
    total = missing = 0
    for f in md_files:
        try:
            fm = _fm_of(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not fm:
            continue
        total += 1
        if not _parse_topics_field(fm):
            missing += 1
    if total == 0:
        return []
    rate = missing / total
    if rate > 0.20:
        return [f"topics 缺失率 {rate:.0%} ({missing}/{total}) 超过 20% 阈值"]
    return []


# ============ CLI ============
# (T0 修复: 原位于 L332, 先于 W4 函数定义执行导致 NameError; 纯位置移动, 零逻辑变更)

if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(Path(__file__).parent))
    from core import AppConfig
    cfg = AppConfig()
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else cfg.paths.wiki_base
    report = lint_wiki(target)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    # 7 维加 1 = 8 个 key 全非空(空 list 也算)
    fail = sum(1 for v in report.values() if isinstance(v, list) and len(v) > 0)
    print(f"\n📊 巡检:共 {fail} 类问题", file=sys.stderr)
    sys.exit(1 if fail > 0 else 0)
