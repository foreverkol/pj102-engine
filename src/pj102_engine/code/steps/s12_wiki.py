"""S12: WIKI 写入 v3.0 (v7.0 SCHEMA 驱动 · 分层路径 · 字段对齐 · 动态时间戳)

5 类 WIKI 产出:
  1. meetings     -> Meetings/           会议全量页
  2. persons      -> Entities/Persons/    人物页
  3. concepts     -> Knowledge/Concepts/  概念页
  4. judgments    -> Knowledge/Judgments/ 判断论页
  5. comparisons  -> Knowledge/Comparisons/ 比较页

v3.0 修复:
  - 字段名 bug: approach->method, relationship->relation_to_wang, org role->business_model
  - 分层路径: output_dir/meetings -> cfg.paths.wiki_meetings (v7.0 WIKI_LAYOUT)
  - 动态时间戳: 硬编码 2026-09-04 -> datetime.now()
  - 版本统一: v1.1 -> state['_meta']['version']
  - v7.0 必填字段补全: entity_id, canonical_name, aliases, quote_orig, status_stage, value_grade
  - S3 quantitative_params(9 类金融参数)渲染
  - S13 financial_params 渲染
  - S14 scenarios 渲染(摘要展示, 详情由 scenario_extractor 写入)
  - 签名从 (state, output_dir: Path) -> (state, cfg: AppConfig) 对齐 pipeline
"""
from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List

sys.path.insert(0, str(Path(__file__).parent.parent))
from core import AppConfig

import json as _json

def _yq(s) -> str:
    """YAML 安全双引号字符串 (P0 根治: 内容可能含英文双引号, 同 s15 范式)"""
    return _json.dumps(str(s), ensure_ascii=False)



def _now() -> str:
    """动态时间戳 YYYY-MM-DD"""
    return datetime.now().strftime("%Y-%m-%d")


def _now_iso() -> str:
    """动态 ISO 时间戳"""
    return datetime.now().strftime("%Y-%m-%dT%H:%M:%S+08:00")


def _safe_filename(name: str, max_len: int = 30) -> str:
    """安全文件名: 去空格/斜杠, 截断"""
    return (name.strip()
            .replace(" ", "_")
            .replace("/", "_")
            .replace("\\", "_")
            .replace(":", "_")[:max_len])


# ============================================================
# 1. meetings WIKI
# ============================================================

def s12_write_wiki(state: Dict, cfg: AppConfig) -> str:
    """生成 meeting Markdown(v3.0 分层路径 + v7.0 字段补全)"""
    s1 = state["s1"]
    date = s1["date"]
    title = s1["title"]
    content_hash = state["content_hash"]
    version = state["_meta"]["version"]
    provider = state["_meta"]["llm_provider"]
    model = state["_meta"]["llm_model"]
    now = _now()

    s2 = state.get("s2", {})
    s3 = state.get("s3", {})
    s4 = state.get("s4", {})
    s5 = state.get("s5", {})
    s6 = state.get("s6", {})
    s7 = state.get("s7", {})
    s8 = state.get("s8", {})
    s9 = state.get("s9", {})
    s10 = state.get("s10", {})
    s11 = state.get("s11", {})
    s13 = state.get("s13", {})
    s14 = state.get("s14", [])

    # v7.0 ldamc 5 维自检(从 s10 真实读取)
    ldamc = s10.get("ldamc", {})

    # v7.0 §8.1 必填: status_stage / value_grade
    value_score = s11.get("value_score", 0)
    if value_score >= 0.8:
        value_grade = "A"
    elif value_score >= 0.6:
        value_grade = "B"
    elif value_score >= 0.4:
        value_grade = "C"
    else:
        value_grade = "D"

    md = f"""---
date: {date}
title: {_yq(title)}
type: meeting
file_hash: {content_hash}
content_hash: {content_hash}
source: {state['sample']}
generated_at: {now}
generator: pj102-llm-meetingkb-{version}
llm_provider: {provider}
llm_model: {model}
# === v6.1 P-4 meeting_type 6 类 ===
meeting_type: {s2.get('scene_type', 'other')}
meeting_subtype: {s2.get('scene_subtype', 'N/A')}
is_external_knowledge: {s2.get('is_external_knowledge', False)}
# === v7.0 ldamc 5 维自检 ===
ldamc:
  lost: {_yq(ldamc.get('lost', '暂无'))}
  different: {_yq(ldamc.get('different', '暂无'))}
  added: {_yq(ldamc.get('added', '暂无'))}
  more: {_yq(ldamc.get('more', '暂无'))}
  connected: {ldamc.get('connected', [])}
# === v7.0 §8.1 必填 ===
status_stage: compiled
value_grade: {value_grade}
# === W4 三轴标签（taxonomy.yaml 受控）===
topics: {state.get('s9', {}).get('topics', [])}
meta_type: {state.get('s9', {}).get('meta_type', 'reference')}
---

# {title}

## 📌 基础信息（S1）
- **日期**: {date}
- **录音时间**: {s1.get('recording_time', 'N/A')}
- **原文大小**: {s1['char_count']:,} 字符
- **估计时长**: {s1.get('duration_estimate', 'N/A')}

## 🎬 场景识别（S2）
- **场景类型**: {s2.get('scene_type', 'N/A')}
- **子类型**: {s2.get('scene_subtype', 'N/A')}
- **视角**: {s2.get('perspective', 'N/A')}
- **理由**: {s2.get('scene_reason', 'N/A')}
- **置信度**: {s2.get('confidence', 'N/A')}
- **外部知识**: {s2.get('is_external_knowledge', False)}

## 📋 标准摘要（S3）

### 一句话总结
{s3.get('one_sentence', 'N/A')}

### 背景
{s3.get('background', 'N/A')}

### 问题
{s3.get('problem', 'N/A')}

### 方法
{s3.get('method', 'N/A')}

### 结果
{s3.get('outcome', 'N/A')}

### 主理人洞察
{s3.get('insight', 'N/A')}
"""

    # S3 quantitative_params (v6.1 金融参数 9 类)
    qparams = s3.get("quantitative_params", [])
    if qparams:
        md += "\n### 💰 金融参数（S3 quantitative_params）\n\n"
        md += "| 类型 | 数值 | 发言人 | 置信度 | 原文引用 |\n"
        md += "|------|------|--------|--------|----------|\n"
        for q in qparams:
            if isinstance(q, dict):
                md += (f"| {q.get('type', '')} | {q.get('value', '')} | "
                       f"{q.get('speaker', '')} | {q.get('confidence', '')} | "
                       f"`{q.get('quote', '')}` |\n")
        md += "\n"

    # S4 FJV 三分法
    md += "\n## 🔍 FJV 三分法（S4）\n\n### 事实（Fact）\n"
    for f in s4.get("facts", []):
        md += f"- {f}\n"
    if not s4.get("facts"):
        md += "- （无）\n"

    md += "\n### 判断（Judgment · 主理人本人观点）\n"
    for j in s4.get("judgments", []):
        md += f"- {j}\n"
    if not s4.get("judgments"):
        md += "- （无）\n"

    md += "\n### 价值（Value）\n"
    for v in s4.get("values", []):
        md += f"- {v}\n"
    if not s4.get("values"):
        md += "- （无）\n"

    # S5 隐性知识
    md += "\n## 🧠 隐性知识（S5 · 3 次子调用）\n\n### 体验性\n"
    for e in s5.get("experiential", []):
        md += f"- {e}\n"
    if not s5.get("experiential"):
        md += "- （无）\n"

    md += "\n### 判断性\n"
    for j in s5.get("judgmental", []):
        md += f"- {j}\n"
    if not s5.get("judgmental"):
        md += "- （无）\n"

    md += "\n### 关系性\n"
    for r in s5.get("relational", []):
        md += f"- {r}\n"
    if not s5.get("relational"):
        md += "- （无）\n"

    # S6 5 类实体
    md += "\n## 🏷️ 5 类实体（S6）\n\n### 人物\n"
    for p in s6.get("persons", []):
        if isinstance(p, dict):
            entity_id = p.get("entity_id", "")
            eid_str = f" `#{entity_id}`" if entity_id else ""
            md += (f"- **{p.get('name', '')}**{eid_str} "
                   f"- {p.get('role', '')}"
                   f"{' @ ' + p.get('org', '') if p.get('org') else ''} "
                   f"({p.get('relation_to_wang', '未确认')})\n")
            if p.get("aliases"):
                md += f"  - 别名: {', '.join(p['aliases'])}\n"
            if p.get("quote_orig"):
                md += f"  - 原文: `{p['quote_orig']}`\n"
        else:
            md += f"- {p}\n"
    if not s6.get("persons"):
        md += "- （无）\n"

    md += "\n### 机构\n"
    for o in s6.get("organizations", []):
        if isinstance(o, dict):
            entity_id = o.get("entity_id", "")
            eid_str = f" `#{entity_id}`" if entity_id else ""
            md += (f"- **{o.get('name', '')}**{eid_str} "
                   f"({o.get('type', '')}) "
                   f"- {o.get('business_model', '')} "
                   f"[{o.get('cooperation_status', '')}]\n")
            if o.get("aliases"):
                md += f"  - 别名: {', '.join(o['aliases'])}\n"
            if o.get("quote_orig"):
                md += f"  - 原文: `{o['quote_orig']}`\n"
        else:
            md += f"- {o}\n"
    if not s6.get("organizations"):
        md += "- （无）\n"

    md += "\n### 概念\n"
    for c in s6.get("concepts", []):
        if isinstance(c, dict):
            md += f"- **{c.get('name', '')}** - {c.get('definition', '')}\n"
            if c.get("quote_orig"):
                md += f"  - 原文: `{c['quote_orig']}`\n"
        else:
            md += f"- {c}\n"
    if not s6.get("concepts"):
        md += "- （无）\n"

    md += "\n### 产品\n"
    for p in s6.get("products", []):
        if isinstance(p, dict):
            md += (f"- **{p.get('name', '')}** ({p.get('type', '')}) "
                   f"- {p.get('description', '')}\n")
        else:
            md += f"- {p}\n"
    if not s6.get("products"):
        md += "- （无）\n"

    md += "\n### 项目\n"
    for p in s6.get("projects", []):
        if isinstance(p, dict):
            md += (f"- **{p.get('name', '')}** [{p.get('status', '')}] "
                   f"- {p.get('description', '')}\n")
        else:
            md += f"- {p}\n"
    if not s6.get("projects"):
        md += "- （无）\n"

    # S7 决策和行动项
    md += "\n## ✅ 决策和行动项（S7）\n\n### 关键决策\n"
    for d in s7.get("decisions", []):
        if isinstance(d, dict):
            md += f"- **{d.get('decision', '')}** (决策人: {d.get('owner', 'N/A')})\n"
            if d.get("reason"):
                md += f"  - 理由: {d['reason']}\n"
            if d.get("deadline"):
                md += f"  - 期限: {d['deadline']}\n"
        else:
            md += f"- {d}\n"
    if not s7.get("decisions"):
        md += "- （无）\n"

    md += "\n### 行动项\n"
    for a in s7.get("action_items", []):
        if isinstance(a, dict):
            md += (f"- **{a.get('action', '')}** "
                   f"(负责人: {a.get('owner', 'N/A')}, "
                   f"期限: {a.get('deadline', 'N/A')})\n")
        else:
            md += f"- {a}\n"
    if not s7.get("action_items"):
        md += "- （无）\n"

    # S8 风险与盲区
    md += "\n## ⚠️ 风险与盲区（S8）\n\n### 风险\n"
    for r in s8.get("risks", []):
        if isinstance(r, dict):
            md += f"- **{r.get('risk', '')}** (影响: {r.get('impact', 'N/A')})\n"
        else:
            md += f"- {r}\n"
    if not s8.get("risks"):
        md += "- （无）\n"

    md += "\n### 盲区\n"
    for b in s8.get("blindspots", []):
        if isinstance(b, dict):
            md += f"- {b.get('blindspot', '')}\n"
        else:
            md += f"- {b}\n"
    if not s8.get("blindspots"):
        md += "- （无）\n"

    # S9 知识归类
    md += "\n## 📚 知识归类（S9）\n"
    md += f"- **类型**: {s9.get('knowledge_type', 'N/A')}\n"
    tags = s9.get("tags", [])
    md += f"- **标签**: {', '.join(tags) if tags else '（无）'}\n"
    reuse = s9.get("reuse_scenarios", [])
    md += f"- **复用场景**: {', '.join(reuse) if reuse else '（无）'}\n"

    # S10 认知提炼
    md += "\n## 🧬 认知提炼（S10）\n\n### 认知模式\n"
    for c in s10.get("cognitive_refinement", []):
        md += f"- {c}\n"
    if not s10.get("cognitive_refinement"):
        md += "- （无）\n"

    dhm = s10.get("digital_human_material", {})
    if isinstance(dhm, dict) and dhm:
        md += "\n### 数字人素材\n"
        md += f"- **说话风格**: {dhm.get('speaking_style', 'N/A')}\n"
        words = dhm.get("frequently_used_words", [])
        md += f"- **常用词**: {', '.join(words) if words else '（无）'}\n"
        md += f"- **思考框架**: {dhm.get('thinking_framework', 'N/A')}\n"

    # S13 金融参数(如果 S3 quantitative_params 之外还有额外提取)
    fin_params = s13.get("financial_params", []) if isinstance(s13, dict) else []
    if fin_params:
        md += "\n## 💰 S13 金融参数补充\n\n"
        md += "| 类型 | 数值 | 发言人 | 原文引用 |\n"
        md += "|------|------|--------|----------|\n"
        for fp in fin_params:
            if isinstance(fp, dict):
                md += (f"| {fp.get('type', '')} | {fp.get('value', '')} | "
                       f"{fp.get('speaker', '')} | "
                       f"`{fp.get('quote_orig', '')}` |\n")
        md += "\n"

    # S14 场景(摘要展示, 详情由 scenario_extractor 写入 Knowledge/Scenarios/)
    if s14 and isinstance(s14, list):
        md += "\n## 🎯 场景提取（S14）\n\n"
        for sc in s14:
            if isinstance(sc, dict):
                md += f"### {sc.get('scenario_name', 'N/A')}\n"
                md += f"- **场景类型**: {sc.get('scenario_type', 'N/A')}\n"
                md += f"- **描述**: {sc.get('description', 'N/A')}\n"
                if sc.get("key_entities"):
                    md += f"- **关键实体**: {', '.join(sc['key_entities'])}\n"
                md += "\n"
        if not s14:
            md += "- （无）\n"

    # S11 价值评级
    md += "\n## ⭐ 价值评级（S11）\n"
    md += f"- **相关度**: {s11.get('relevance', 0):.2f}\n"
    md += f"- **可行动性**: {s11.get('actionability', 0):.2f}\n"
    md += f"- **新颖性**: {s11.get('innovation', 0):.2f}\n"
    md += f"- **综合价值**: **{s11.get('value_score', 0):.2f}** ({value_grade}级)\n"
    md += f"- **理由**: {s11.get('value_reason', 'N/A')}\n"

    # 集成结果摘要
    integ = state.get("_integrations", {})
    if integ:
        md += "\n## 🔗 集成结果\n\n"
        if "entity_resolver" in integ:
            md += f"- **实体统一**: {integ['entity_resolver'].get('resolved', 0)} 个实体已编号\n"
        if "citations" in integ:
            md += f"- **引用中间层**: {integ['citations'].get('written', 0)} 条\n"
        if "scenario_extractor" in integ:
            md += f"- **场景写入**: {integ['scenario_extractor'].get('written', 0)} 个\n"
        if "review_queue" in integ:
            md += f"- **审核队列**: {integ['review_queue'].get('enqueued', 0)} 条入队\n"

    # 元信息
    md += f"""
## 📑 元信息
- **LLM Provider**: {provider}
- **LLM Model**: {model}
- **生成时间**: {now}
- **版本**: pj102-llm-meetingkb-{version}
- **项目**: PJ-102-LLM-MeetingKB
"""

    out_file = cfg.paths.wiki_meetings / f"meeting_{date}_{content_hash}.md"
    out_file.parent.mkdir(parents=True, exist_ok=True)
    out_file.write_text(md, encoding="utf-8", newline="\n")
    return str(out_file)


# ============================================================
# 2. persons WIKI
# ============================================================

def s12_write_persons(state: Dict, cfg: AppConfig) -> List[str]:
    """从 S6 人物实体生成 persons WIKI(v7.0 entity_id + canonical_name)"""
    written = []
    s1 = state["s1"]
    date = s1["date"]
    source = state["sample"]
    content_hash = state["content_hash"]
    version = state["_meta"]["version"]
    provider = state["_meta"]["llm_provider"]
    model = state["_meta"]["llm_model"]
    now = _now()

    for person in state.get("s6", {}).get("persons", []):
        if not isinstance(person, dict):
            continue
        name = person.get("name", "").strip()
        if not name:
            continue

        # ⚠ D-40（2026-09-16）：页名与 frontmatter `name` 必须绑定 **canonical_name**。
        # 为什么：polish_pages 以 `name` 判定"是否同一实体"，若仍写 s6 原始名，
        # 同一 entity_id 会因各次称法不同（海塑胶 / 海数交 / 海墅所）而裂成多页
        # —— 这正是 wiki 出现 20 组"同 id 多页"的直接成因。
        canonical_name = person.get("canonical_name") or name
        display = canonical_name
        safe_name = _safe_filename(display)
        entity_id = person.get("entity_id", "")
        aliases = list(person.get("aliases", []) or [])
        if name and name != display and name not in aliases:
            aliases = [name] + aliases        # 本次称法降为别名，保留溯源

        md = f"""---
type: person
name: {_yq(display)}
canonical_name: {_yq(canonical_name)}
entity_id: {_yq(entity_id)}
date: {date}
role: {_yq(person.get('role', ''))}
org: {_yq(person.get('org', ''))}
relation_to_wang: {_yq(person.get('relation_to_wang', '未确认'))}
aliases: {aliases}
source_meeting: {source}
source_hash: {content_hash}
generated_at: {now}
generator: pj102-llm-meetingkb-{version}
llm_provider: {provider}
llm_model: {model}
status_stage: compiled
topics: {state.get('s9', {}).get('topics', [])}
meta_type: reference
---

# {display}

## 👤 人物信息

- **姓名**: {display}
- **规范名**: {canonical_name}
- **本次称法**: {name}
- **实体编号**: {entity_id or '待分配'}
- **角色/职位**: {person.get('role', 'N/A')}
- **所属机构**: {person.get('org', 'N/A')}
- **与主理人关系**: {person.get('relation_to_wang', 'N/A')}
"""

        if aliases:
            md += f"- **别名**: {', '.join(aliases)}\n"

        if person.get("quote_orig"):
            md += f"\n### 原文引用\n> `{person['quote_orig']}`\n"

        if person.get("disambiguation_note"):
            md += f"\n### 消歧说明\n{person['disambiguation_note']}\n"

        md += f"""
## 📅 出现会议

- **{s1.get('title', 'N/A')}** ({date})

## 🎯 在该会议中的活动

### 关联事实
"""
        # S4 中与此人物相关的事实
        found = False
        for fact in state.get("s4", {}).get("facts", []):
            if isinstance(fact, str) and (name in fact or name[:2] in fact):
                md += f"- {fact}\n"
                found = True
        if not found:
            md += "- （无直接关联）\n"

        # S5 关系性
        md += "\n### 关联隐性知识\n"
        found = False
        for rel in state.get("s5", {}).get("relational", []):
            if isinstance(rel, str) and (name in rel or name[:2] in rel):
                md += f"- {rel}\n"
                found = True
            elif isinstance(rel, dict):
                desc = str(rel.get("description", ""))
                if name in desc or name[:2] in desc:
                    md += f"- {rel.get('relation', '')}: {desc}\n"
                    found = True
        if not found:
            md += "- （无直接关联）\n"

        md += f"""
## 📊 价值评估

- **相关度**: {state.get('s11', {}).get('relevance', 0):.2f}
- **综合价值**: {state.get('s11', {}).get('value_score', 0):.2f}

## 📑 元信息

- **生成时间**: {now}
- **来源会议**: {source}
- **LLM**: {provider} / {model}
- **版本**: pj102-llm-meetingkb-{version}
"""

        out_file = cfg.paths.wiki_persons / f"person_{safe_name}_{content_hash[:8]}.md"
        out_file.parent.mkdir(parents=True, exist_ok=True)
        out_file.write_text(md, encoding="utf-8", newline="\n")
        written.append(str(out_file))

    return written


# ============================================================
# 2b. organizations WIKI (v4.0 补遗: 历史版本缺失导致 Organizations 目录为空)
# ============================================================

def s12_write_organizations(state: Dict, cfg: AppConfig) -> List[str]:
    """从 S6 机构实体生成 organizations WIKI"""
    written = []
    s1 = state["s1"]
    date = s1["date"]
    source = state["sample"]
    content_hash = state["content_hash"]
    version = state["_meta"]["version"]
    provider = state["_meta"]["llm_provider"]
    model = state["_meta"]["llm_model"]
    now = _now()

    for org in state.get("s6", {}).get("organizations", []):
        if not isinstance(org, dict):
            continue
        name = org.get("name", "").strip()
        if not name:
            continue

        # ⚠ D-40（2026-09-16）：同 persons —— 页名与 frontmatter `name` 绑定
        # canonical_name，否则 polish_pages 会按 s6 原始名把同一 entity_id 裂成多页。
        canonical_name = org.get("canonical_name") or name
        display = canonical_name
        safe_name = _safe_filename(display)
        entity_id = org.get("entity_id", "")
        eid_suffix = entity_id.split("_")[1][:8] if entity_id else content_hash[:8]
        aliases = list(org.get("aliases", []) or [])
        if name and name != display and name not in aliases:
            aliases = [name] + aliases

        md = f"""---
type: organization
name: {_yq(display)}
canonical_name: {_yq(canonical_name)}
entity_id: {_yq(entity_id)}
date: {date}
org_type: {_yq(org.get('type', ''))}
business_model: {_yq(org.get('business_model', ''))}
cooperation_status: {_yq(org.get('cooperation_status', ''))}
aliases: {aliases}
source_meeting: {source}
source_hash: {content_hash}
generated_at: {now}
generator: pj102-llm-meetingkb-{version}
llm_provider: {provider}
llm_model: {model}
status_stage: compiled
topics: {state.get('s9', {}).get('topics', [])}
meta_type: reference
---

# {display}

## 🏢 机构信息

- **规范名**: {canonical_name}
- **本次称法**: {name}
- **实体编号**: {entity_id or '待分配'}
- **机构类型**: {org.get('type', 'N/A')}
- **业务模式**: {org.get('business_model', 'N/A')}
- **合作状态**: {org.get('cooperation_status', 'N/A')}
"""
        if aliases:
            md += f"- **别名**: {', '.join(aliases)}\n"

        if org.get("quote_orig"):
            md += f"\n### 原文引用\n> `{org['quote_orig']}`\n"

        md += f"""
## 📅 出现会议

- **{s1.get('title', 'N/A')}** ({date})

## 📑 元信息

- **生成时间**: {now}
- **来源会议**: {source}
- **LLM**: {provider} / {model}
- **版本**: pj102-llm-meetingkb-{version}
"""
        out_file = cfg.paths.wiki_organizations / f"org_{safe_name}_{eid_suffix}.md"
        out_file.parent.mkdir(parents=True, exist_ok=True)
        out_file.write_text(md, encoding="utf-8", newline="\n")
        written.append(str(out_file))

    return written


# ============================================================
# 3. concepts WIKI
# ============================================================

def s12_write_concepts(state: Dict, cfg: AppConfig) -> List[str]:
    """从 S6 概念实体生成 concepts WIKI"""
    written = []
    s1 = state["s1"]
    date = s1["date"]
    source = state["sample"]
    content_hash = state["content_hash"]
    version = state["_meta"]["version"]
    provider = state["_meta"]["llm_provider"]
    model = state["_meta"]["llm_model"]
    now = _now()

    for concept in state.get("s6", {}).get("concepts", []):
        if not isinstance(concept, dict):
            continue
        name = concept.get("name", "").strip()
        if not name:
            continue

        safe_name = _safe_filename(name)
        md = f"""---
type: concept
name: {_yq(name)}
date: {date}
definition: {_yq(concept.get('definition', ''))}
source_meeting: {source}
source_hash: {content_hash}
generated_at: {now}
generator: pj102-llm-meetingkb-{version}
llm_provider: {provider}
llm_model: {model}
status_stage: compiled
topics: {state.get('s9', {}).get('topics', [])}
meta_type: reference
---

# {name}

## 📖 概念定义

{concept.get('definition', 'N/A')}
"""

        if concept.get("quote_orig"):
            md += f"\n### 原文引用\n> `{concept['quote_orig']}`\n"

        md += f"""
## 🔗 出现会议

- **{s1.get('title', 'N/A')}** ({date})

## 💡 相关讨论
"""
        # S3 中与此概念相关的内容
        s3 = state.get("s3", {})
        insight = s3.get("insight", "")
        if insight and (name in insight or name[:2] in insight):
            md += f"### 主理人洞察\n{insight}\n"

        method = s3.get("method", "")
        if method and (name in method or name[:2] in method):
            md += f"### 方法中提及\n{method}\n"

        md += f"""
## 📚 知识归类

- **类型**: {state.get('s9', {}).get('knowledge_type', 'N/A')}
- **标签**: {', '.join(state.get('s9', {}).get('tags', [])) or '（无）'}

## 📑 元信息

- **生成时间**: {now}
- **来源会议**: {source}
- **LLM**: {provider} / {model}
- **版本**: pj102-llm-meetingkb-{version}
"""

        out_file = cfg.paths.wiki_concepts / f"concept_{safe_name}_{content_hash[:8]}.md"
        out_file.parent.mkdir(parents=True, exist_ok=True)
        out_file.write_text(md, encoding="utf-8", newline="\n")
        written.append(str(out_file))

    return written


# ============================================================
# 4. judgments WIKI
# ============================================================

def s12_write_judgments(state: Dict, cfg: AppConfig) -> List[str]:
    """从 S4 判断生成 judgments WIKI"""
    written = []
    s1 = state["s1"]
    date = s1["date"]
    source = state["sample"]
    content_hash = state["content_hash"]
    version = state["_meta"]["version"]
    provider = state["_meta"]["llm_provider"]
    model = state["_meta"]["llm_model"]
    now = _now()

    # v7.0 value_grade
    value_score = state.get("s11", {}).get("value_score", 0)
    value_grade = "A" if value_score >= 0.8 else ("B" if value_score >= 0.6 else ("C" if value_score >= 0.4 else "D"))

    judgments = state.get("s4", {}).get("judgments", [])
    # W4: s7 decisions 带 stance/topic_key, 与 s4 判断文本做包含匹配回填页面
    s7_decisions = state.get("s7", {}).get("decisions", [])
    s9 = state.get("s9", {})
    for i, j in enumerate(judgments, 1):
        if not j or not isinstance(j, str):
            continue

        # stance 匹配: s7.decision 与 s4 判断互为包含, 或共同前缀 ≥10 字
        stance, topic_key = "", ""
        for d in s7_decisions:
            if not isinstance(d, dict):
                continue
            dec = d.get("decision", "")
            if (dec and (dec in j or j in dec or (dec[:10] and dec[:10] == j[:10]))):
                stance = d.get("stance", "")
                topic_key = d.get("topic_key", "")
                break

        safe_title = _safe_filename(j[:30])
        md = f"""---
type: judgment
title: {_yq(j[:60])}
date: {date}
author: "主理人本人观点"
source_meeting: {source}
source_hash: {content_hash}
generated_at: {now}
generator: pj102-llm-meetingkb-{version}
llm_provider: {provider}
llm_model: {model}
status_stage: compiled
value_grade: {value_grade}
topic_key: {_yq(topic_key)}
stance: {stance or 'unlabeled'}
# === W4 三轴标签（taxonomy.yaml 受控）===
topics: {s9.get('topics', [])}
meta_type: prediction
---

# 判断 #{i}：{j[:50]}

## 💭 判断内容

{j}

## 🔗 来源会议

- **{s1.get('title', 'N/A')}** ({date})

## 📋 上下文

### 背景
{state.get('s3', {}).get('background', 'N/A')}

### 相关事实
"""
        facts = state.get("s4", {}).get("facts", [])
        for f in facts[:3]:
            md += f"- {f}\n"
        if not facts:
            md += "- （无）\n"

        md += f"""
## ⭐ 价值评估

- **综合价值**: {value_score:.2f} ({value_grade}级)
- **可行动性**: {state.get('s11', {}).get('actionability', 0):.2f}

## 📑 元信息

- **生成时间**: {now}
- **来源会议**: {source}
- **LLM**: {provider} / {model}
- **版本**: pj102-llm-meetingkb-{version}
"""

        out_file = cfg.paths.wiki_judgments / f"judgment_{date}_{content_hash[:8]}_{i}.md"
        out_file.parent.mkdir(parents=True, exist_ok=True)
        out_file.write_text(md, encoding="utf-8", newline="\n")
        written.append(str(out_file))

    return written


# ============================================================
# 5. comparisons WIKI
# ============================================================

def s12_write_comparisons(state: Dict, cfg: AppConfig) -> List[str]:
    """从 S4/S5 中识别比较关系，生成 comparisons WIKI"""
    written = []
    s1 = state["s1"]
    date = s1["date"]
    source = state["sample"]
    content_hash = state["content_hash"]
    version = state["_meta"]["version"]
    provider = state["_meta"]["llm_provider"]
    model = state["_meta"]["llm_model"]
    now = _now()

    # 从 S4 facts 识别比较关系
    facts = state.get("s4", {}).get("facts", [])
    comparisons_found = []
    for fact in facts:
        if isinstance(fact, str):
            if any(kw in fact for kw in [" vs ", "对比", "比较", "不同", "差异", "优劣势"]):
                comparisons_found.append(fact)

    # 从 S5 关系中识别
    s5_rel = state.get("s5", {}).get("relational", [])
    for rel in s5_rel:
        if isinstance(rel, dict):
            desc = rel.get("description", "")
            if any(kw in desc for kw in ["对比", "比较", "差异", " vs "]):
                comparisons_found.append(f"{rel.get('relation', '')}: {desc}")
        elif isinstance(rel, str):
            if any(kw in rel for kw in ["对比", "比较", "差异", " vs "]):
                comparisons_found.append(rel)

    if not comparisons_found:
        return written

    md = f"""---
type: comparison
date: {date}
source_meeting: {source}
source_hash: {content_hash}
comparison_count: {len(comparisons_found)}
generated_at: {now}
generator: pj102-llm-meetingkb-{version}
llm_provider: {provider}
llm_model: {model}
status_stage: compiled
topics: {state.get('s9', {}).get('topics', [])}
meta_type: reference
---

# 比较关系 - {s1.get('title', 'N/A')}

## 📅 来源会议

- **{s1.get('title', 'N/A')}** ({date})

## 🔄 比较内容

"""
    for i, comp in enumerate(comparisons_found, 1):
        md += f"### 比较 #{i}\n{comp}\n\n"

    md += f"""
## 📑 元信息

- **比较数**: {len(comparisons_found)}
- **生成时间**: {now}
- **来源会议**: {source}
- **LLM**: {provider} / {model}
- **版本**: pj102-llm-meetingkb-{version}
"""

    out_file = cfg.paths.wiki_comparisons / f"comparison_{date}_{content_hash[:8]}.md"
    out_file.parent.mkdir(parents=True, exist_ok=True)
    out_file.write_text(md, encoding="utf-8", newline="\n")
    written.append(str(out_file))

    return written


# ============================================================
# 汇总入口
# ============================================================

def s12_write_all_5_types(state: Dict, cfg: AppConfig) -> Dict[str, List[str]]:
    """一次生成全部 5 类 WIKI，返回各类型产出列表

    v3.0: 签名从 (state, output_dir: Path) -> (state, cfg: AppConfig)
          内部用 cfg.paths.wiki_* 分层路径, 与 pipeline.py 对接
    """
    result = {
        "meetings": [s12_write_wiki(state, cfg)],
        "persons": s12_write_persons(state, cfg),
        "organizations": s12_write_organizations(state, cfg),
        "concepts": s12_write_concepts(state, cfg),
        "judgments": s12_write_judgments(state, cfg),
        "comparisons": s12_write_comparisons(state, cfg),
    }
    return result
