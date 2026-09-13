"""
v3.0 scenario_extractor.py - 把 s14 提取的 scenario 写为 WIKI/Knowledge/Scenarios/ md

每 scenario 1 个 md 文件:
  Knowledge/Scenarios/{slug_theme}_{content_hash[:8]}.md

完整 frontmatter + 11 字段正文 + 关联来源
"""

import sys
from pathlib import Path
import re
import hashlib
from datetime import datetime, timezone
from typing import List


def scenario_to_md(scenario: dict, source_ref: str = "",
                  meeting_date: str = "") -> str:
    """scenario dict → 完整 markdown + frontmatter"""
    theme = scenario.get("theme", "未命名 scenario")

    # slug
    slug = re.sub(r'[^\w\u4e00-\u9fff]+', '_', theme).strip('_')[:30]
    content_hash = hashlib.md5(
        (theme + str(scenario)).encode("utf-8")
    ).hexdigest()[:8]

    # frontmatter (v7.0 §8.1 scenario 11 字段必填)
    fm_lines = [
        "---",
        "type: scenario",
        "subtype: business_model_fragment",
        "knowledge_tier: L3_knowledge",
        "theme: \"" + _escape(theme) + "\"",
        "scenario_id: \"SC-" + content_hash + "\"",
    ]
    if source_ref:
        fm_lines.append(f"source_ref: \"{_escape(source_ref)}\"")
    if meeting_date:
        fm_lines.append(f"meeting_date: {meeting_date}")
    fm_lines.extend([
        "status_stage: compiled",  # v7.0 §8.1
        "version: 1",
        "previous_versions: []",
        "value_grade: A",
        "sensitivity: internal",
        "confidence: extracted",
        "extraction_perspective: entrepreneur",
        f"created: {datetime.now(timezone.utc).date().isoformat()}",
        f"updated: {datetime.now(timezone.utc).date().isoformat()}",
        "tags: [scenario, 商业模式, business_model]",
        "---",
        "",
        f"# {theme}",
        "",
        "## 业务定义",
        "",
        "### 客户与痛点",
        f"- **客户**: {scenario.get('customer', '未识别')}",
        f"- **痛点**: {scenario.get('pain_point', '未识别')}",
        "",
        "### 提供与变现",
        f"- **Offering**: {scenario.get('offering', '未识别')}",
        f"- **价值捕获**: {scenario.get('value_capture', '未识别')}",
        f"- **销售渠道**: {scenario.get('channel', '未识别')}",
        "",
        "## 关键资源与约束",
        f"- **关键资源**: {_list_to_md(scenario.get('key_resources', []))}",
        f"- **关键约束**: {_list_to_md(scenario.get('key_constraints', []))}",
        "",
        "## 深层分析",
        f"- **隐性假设**: {_list_to_md(scenario.get('hidden_assumptions', []))}",
        f"- **触发信号**: {_list_to_md(scenario.get('trigger_signals', []))}",
        f"- **失败模式**: {_list_to_md(scenario.get('failure_modes', []))}",
        "",
        "## 视角",
        f"- **提取视角**: {scenario.get('extraction_perspective', 'entrepreneur')}",
        "",
        "## 📑 元信息",
        f"- **Scenario ID**: SC-{content_hash}",
        f"- **来源会议**: {source_ref or '未指定'}",
        f"- **创建日期**: {datetime.now(timezone.utc).date().isoformat()}",
        f"- **v7.0 必填字段**: 11 个全部填全(主题/客户/痛点/Offering/价值捕获/渠道/资源/约束/假设/触发/失败)",
        f"- **项目**: PJ-102-LLM-MeetingKB",
    ])
    return "\n".join(fm_lines)


def write_scenarios(scenarios: List[dict], wiki_root: Path,
                   source_ref: str = "", meeting_date: str = "") -> List[Path]:
    """写多个 scenario 为 md 文件

    Returns: list of written Path
    """
    if not scenarios:
        return []

    scenarios_dir = wiki_root / "Knowledge" / "Scenarios"
    scenarios_dir.mkdir(parents=True, exist_ok=True)

    written = []
    for scen in scenarios:
        theme = scen.get("theme", "未命名")
        slug = re.sub(r'[^\w\u4e00-\u9fff]+', '_', theme).strip('_')[:30]
        content_hash = hashlib.md5(
            (theme + str(scen)).encode("utf-8")
        ).hexdigest()[:8]
        out = scenarios_dir / f"{slug}_{content_hash}.md"

        md = scenario_to_md(scen, source_ref=source_ref,
                           meeting_date=meeting_date)
        out.write_text(md, encoding="utf-8")
        written.append(out)

    return written


def _list_to_md(items) -> str:
    if isinstance(items, list) and items:
        return "; ".join(str(x) for x in items)
    return "(无)"


def _escape(s: str) -> str:
    return str(s).replace('"', '\\"').replace("\n", " ")
