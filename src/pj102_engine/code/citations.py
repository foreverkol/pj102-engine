"""
citations 中间层 - v3.0 升级为 v7.0 extraction_patch (YAML 格式)

7.1 extraction_patch: 每次 ingest 产出一份,记录 diff 与 review 状态
7.2 candidate_entity: 命名实体匹配候选(同 canonical_name 消歧)
7.3 entity_registry: 持久化实体注册表

YAML 优先(优于 JSON):更可读、可注释、与 markdown 生态融合
"""
import sys
from pathlib import Path
from datetime import datetime, timezone
import re

sys.path.insert(0, str(Path(__file__).parent.parent))

try:
    import yaml
    HAS_YAML = True
except ImportError:
    HAS_YAML = False
    yaml = None

# ==================== 7.3 entity_registry ====================

ENTITY_REGISTRY_TEMPLATE = {
    "version": "1.0",
    "schema": "v7.0",
    "last_updated": "",
    "entities": [],
}


def load_entity_registry(path: Path) -> dict:
    """加载 entity_registry.json"""
    if not path.exists():
        return {**ENTITY_REGISTRY_TEMPLATE,
                "last_updated": datetime.now(timezone.utc).isoformat()}
    import json
    return json.loads(path.read_text(encoding="utf-8"))


def save_entity_registry(path: Path, registry: dict):
    import json
    registry["last_updated"] = datetime.now(timezone.utc).isoformat()
    path.write_text(json.dumps(registry, ensure_ascii=False, indent=2),
                    encoding="utf-8")


# ==================== 7.1 extraction_patch 生成 ====================

def build_extraction_patch(
    *,
    ingest_id: str,
    target_page: str,
    operation: str,           # create | update | merge | flag
    confidence: str,          # high | medium | low
    source_ref: str,
    candidate_fields: dict,
    diff_summary: dict = None,
    review_required: bool = False,
    ldamc: dict = None,
    status: str = "pending",
) -> str:
    """构建 v7.0 extraction_patch YAML"""
    patch = {
        "type": "extraction_patch",
        "ingest_id": ingest_id,
        "target_page": target_page,
        "operation": operation,
        "confidence": confidence,
        "source_ref": source_ref,
        "candidate_fields": candidate_fields,
        "diff_summary": diff_summary or {"added": [], "changed": [], "conflicts": []},
        "review_required": review_required,
        "status": status,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    if ldamc is not None:
        patch["ldamc"] = ldamc

    # YAML 输出(若不可用,降级到 dict)
    if HAS_YAML:
        return yaml.safe_dump(patch, allow_unicode=True, sort_keys=False)
    return str(patch)


def write_extraction_patch(citations_dir: Path, patch_yaml: str, ingest_id: str) -> Path:
    """写 citations/{ingest_id}_extraction_patch.yaml"""
    citations_dir.mkdir(parents=True, exist_ok=True)
    fname = f"{ingest_id}_extraction_patch.yaml"
    out = citations_dir / fname
    out.write_text(patch_yaml, encoding="utf-8")
    return out


# ==================== patch → entities_master merge ====================

def merge_patch_into_master(
    patch: dict,
    masters_dir: Path,
    canonical_name_resolver=None,  # v3.0 留接口,future TC-206
) -> list:
    """把 patch 合并到 persons_master.json / orgs_master.json

    append-only 模式(PJ-001 v6.0 §4.2):
    - 已有 entity:append observations(防重)
    - 新 entity:create + append

    Returns: list of (entity_id, action) pairs
    """
    import json

    if not isinstance(patch, dict):
        # YAML 解析失败兼容
        return [("unknown", "skip")]

    fields = patch.get("candidate_fields", {})
    if not fields:
        return []

    target = patch.get("target_page", "")
    # target_page 是 WIKI/Entities/Persons/{name}.md → 解析 name
    m = re.search(r"/(Entities|Knowledge|Meetings|Concepts)/([A-Za-z\u4e00-\u9fff_]+?)(?:/|$|\.md)", target)
    if not m:
        return []

    category = m.group(1)  # Entities / Knowledge / Meetings / Concepts
    name = m.group(2).strip()

    masters_dir.mkdir(parents=True, exist_ok=True)

    results = []
    if "Persons" in target or category == "Entities" and "人物" in fields.get("_category", ""):
        # persons_master.json
        fp = masters_dir / "persons_master.json"
        master = json.loads(fp.read_text()) if fp.exists() else {
            "schema": "v7.0", "last_updated": "", "persons": {}
        }
        if name not in master["persons"]:
            master["persons"][name] = {
                "name": name,
                "primary_role": fields.get("role", "unknown"),
                "primary_org": fields.get("org", "unknown"),
                "aliases": fields.get("aliases", []),
                "observations": [],
            }
            action = "create"
        else:
            action = "update"
            # aliases 合并
            master["persons"][name]["aliases"] = list(set(
                master["persons"][name].get("aliases", []) +
                fields.get("aliases", [])
            ))

        # append-only observation
        new_obs = {
            "meeting_id": patch.get("ingest_id", ""),
            "role": fields.get("role", ""),
            "org": fields.get("org", ""),
            "relation_to_wang": fields.get("relation_to_wang", ""),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "source_ref": patch.get("source_ref", ""),
            "quote_orig": fields.get("quote_orig", ""),
        }
        existing = master["persons"][name]["observations"]
        is_dup = any(
            o["meeting_id"] == new_obs["meeting_id"] and o["role"] == new_obs["role"]
            for o in existing
        )
        if not is_dup:
            existing.append(new_obs)

        master["last_updated"] = datetime.now(timezone.utc).isoformat()
        fp.write_text(json.dumps(master, ensure_ascii=False, indent=2),
                      encoding="utf-8")
        results.append((name, action))

    return results


# ==================== 顶层入口:提取后调用 ====================

def write_citations_intermediate(
    state: dict,
    citations_dir: Path,
    *,
    ldamc: dict = None,
) -> list:
    """s12_wiki 调用:为本次 sample 写 extraction_patch YAML

    Args:
        state: 12 步处理结果(dict)
        citations_dir: 02-知识库/.../citations/
        ldamc: S10 输出的 5 维(可选)

    Returns: list of written Path
    """
    s1 = state.get("s1", {})
    date = s1.get("date", "")
    safe_date = re.sub(r"[^\d-]", "", str(date)) or "unknown"
    ingest_id = f"ING-{safe_date}-{state.get('content_hash', 'unknown')[:8]}"

    written = []
    persons = state.get("s6", {}).get("persons", [])

    # 1. 为每个 person 生成 1 份 extraction_patch(person 级)
    for person in persons:
        if not isinstance(person, dict):
            continue
        name = person.get("name", "").strip()
        if not name:
            continue

        patch_yaml = build_extraction_patch(
            ingest_id=ingest_id,
            target_page=f"WIKI/Entities/Persons/{name}.md",
            operation="create",
            confidence="medium",
            source_ref=f"RAW/transcripts/{state.get('sample', '')}",
            candidate_fields={
                "role": person.get("role", ""),
                "org": person.get("org", ""),
                "relation_to_wang": person.get("relation_to_wang", ""),
                "aliases": person.get("aliases", []),
                "quote_orig": person.get("quote_orig", ""),
            },
            diff_summary={"added": ["role", "org"],
                          "changed": [],
                          "conflicts": []},
            review_required=not person.get("quote_orig"),
            ldamc=ldamc,
            status="pending",
        )
        out = write_extraction_patch(citations_dir, patch_yaml, f"{ingest_id}_person_{name[:20]}")
        written.append(out)

    # 2. judgments_master extraction_patch
    judgments = state.get("s4", {}).get("judgments", [])
    for i, j in enumerate(judgments):
        if not isinstance(j, str):
            continue
        title = j[:30].replace("/", "_").replace(":", "_").replace(" ", "_")
        patch_yaml = build_extraction_patch(
            ingest_id=ingest_id,
            target_page=f"WIKI/Knowledge/Judgments/{safe_date}_{title}.md",
            operation="create",
            confidence="high" if j else "low",
            source_ref=f"RAW/transcripts/{state.get('sample', '')}",
            candidate_fields={
                "judgment": j,
                "topic_key": state.get("s7", {}).get("decisions", [{}])[0].get("topic_key", "")
                              if state.get("s7", {}).get("decisions") else "",
            },
            ldamc=ldamc,
            status="pending",
        )
        out = write_extraction_patch(citations_dir, patch_yaml, f"{ingest_id}_judgment_{i}")
        written.append(out)

    return written
