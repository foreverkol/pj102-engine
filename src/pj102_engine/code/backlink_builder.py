"""
v4.0 backlink_builder.py - 反向链接 (Karpathy LLM Wiki 缺口6)

扫描 wiki/ 所有 .md, 建立双向链接知识网络:
  - 对每个 wiki 文件, 提取其 body 提到的实体名
  - 在被提到实体的 wiki 文件 frontmatter 加 backlinks: [引用方]
  - 实现 "页面之间能点击跳转" 的知识网

设计:
  - 读 entity_registry.json 获取所有实体名 (canonical_name + aliases)
  - 扫描每个 wiki 文件 body, 检查提到哪些实体名
  - 对 person/org wiki 文件, 在 frontmatter 加 backlinks 字段
  - 幂等: 每次重建 backlinks (覆盖)
"""

import sys
import re
import json
from pathlib import Path
from typing import List, Dict, Set, Tuple

sys.path.insert(0, str(Path(__file__).parent))
from core import AppConfig, get_logger

import yaml

log = get_logger()

BACKLINKS_KEY = "backlinks"


def load_entity_names(registry_path: Path) -> Dict[str, List[str]]:
    """从 entity_registry.json 加载实体名 (canonical_name -> [aliases])"""
    if not registry_path.exists():
        return {}
    try:
        data = json.loads(registry_path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    result = {}
    for ent in data.get("entities", []):
        cn = ent.get("canonical_name", "")
        if cn:
            aliases = ent.get("aliases", [])
            result[cn] = aliases
    return result


def find_wiki_file_for_entity(wiki_root: Path, entity_name: str,
                               entity_type: str = None) -> Path:
    """找实体对应的 wiki 文件"""
    if entity_type == "person" or entity_type is None:
        person_dir = wiki_root / "Entities" / "Persons"
        if person_dir.exists():
            matches = list(person_dir.glob(f"*{entity_name}*.md"))
            if matches:
                return matches[0]
    if entity_type == "organization" or entity_type is None:
        org_dir = wiki_root / "Entities" / "Organizations"
        if org_dir.exists():
            matches = list(org_dir.glob(f"*{entity_name}*.md"))
            if matches:
                return matches[0]
    return None


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
    body = parts[2]
    return fm, body


def find_entities_in_text(text: str, entity_names: Dict[str, List[str]]) -> Set[str]:
    """在文本中查找出现的实体名 (canonical + aliases)"""
    found = set()
    for canonical, aliases in entity_names.items():
        if canonical and canonical in text:
            found.add(canonical)
            continue
        for alias in aliases:
            if alias and alias in text:
                found.add(canonical)
                break
    return found


def build_backlinks(cfg: AppConfig = None) -> dict:
    """主入口: 扫描 wiki 建立反向链接

    Returns:
        {"total_files": N, "backlinks_added": N, "entities_with_backlinks": N,
         "top_entities": [(name, count), ...]}
    """
    if cfg is None:
        cfg = AppConfig()
    wiki_root = cfg.paths.wiki_base
    registry_path = cfg.paths.registry_path

    if not wiki_root.exists():
        log.warning("wiki 目录不存在", step="backlink_builder")
        return {"total_files": 0, "backlinks_added": 0}

    # 1. 加载实体名
    entity_names = load_entity_names(registry_path)
    if not entity_names:
        log.warning("entity_registry 为空", step="backlink_builder")
    log.info(f"加载 {len(entity_names)} 个实体名", step="backlink_builder")

    # 2. 第一遍扫描: 建立实体 → [引用它的文件] 映射
    # entity_backlinks: {entity_name: [{file, rel_path, title}]}
    entity_backlinks: Dict[str, List[dict]] = {name: [] for name in entity_names}

    all_files = [f for f in wiki_root.rglob("*.md")
                 if f.name not in ("index.md", "log.md")]
    for md_file in all_files:
        try:
            content = md_file.read_text(encoding="utf-8")
        except Exception:
            continue
        fm, body = parse_frontmatter_and_body(content)
        # 在 body 中查找实体名
        found = find_entities_in_text(body, entity_names)
        # 排除自身 (person 文件提到自己不算反向链接)
        own_entity = fm.get("canonical_name", "")
        if own_entity in found:
            found.discard(own_entity)
        title = fm.get("title", md_file.stem)
        rel_path = str(md_file.relative_to(wiki_root)).replace("\\", "/")
        for entity_name in found:
            entity_backlinks[entity_name].append({
                "file": rel_path,
                "title": title,
            })

    # 3. 第二遍写入: 对每个实体的 wiki 文件, 在 frontmatter 加 backlinks
    backlinks_added = 0
    entities_with_backlinks = 0
    top_entities = []

    for entity_name, refs in entity_backlinks.items():
        # 找实体对应的 wiki 文件 (person/org)
        # 先确定 entity_type
        ent_type = None
        try:
            reg_data = json.loads(registry_path.read_text(encoding="utf-8"))
            for ent in reg_data.get("entities", []):
                if ent.get("canonical_name") == entity_name:
                    ent_type = ent.get("entity_type")
                    break
        except Exception:
            pass

        wiki_file = find_wiki_file_for_entity(wiki_root, entity_name, ent_type)
        if not wiki_file or not wiki_file.exists():
            continue

        if refs:
            entities_with_backlinks += 1
            top_entities.append((entity_name, len(refs)))

        # 读原内容
        try:
            content = wiki_file.read_text(encoding="utf-8")
        except Exception:
            continue
        fm, body = parse_frontmatter_and_body(content)

        # 更新 backlinks 字段
        fm[BACKLINKS_KEY] = [r["file"] for r in refs]

        # 序列化 frontmatter
        new_fm = _serialize_frontmatter(fm)
        new_content = f"---\n{new_fm}---\n{body}"

        if new_content != content:
            wiki_file.write_text(new_content, encoding="utf-8")
            backlinks_added += 1

    top_entities.sort(key=lambda x: -x[1])

    log.info(f"backlinks 构建完成: {backlinks_added} 个文件更新, "
             f"{entities_with_backlinks} 个实体有反向链接",
             step="backlink_builder")

    return {
        "total_files": len(all_files),
        "backlinks_added": backlinks_added,
        "entities_with_backlinks": entities_with_backlinks,
        "top_entities": top_entities[:10],
    }


def _serialize_frontmatter(fm: dict) -> str:
    """手动序列化 frontmatter 为可读 YAML"""
    lines = []
    for k, v in fm.items():
        if v is None:
            lines.append(f"{k}:")
        elif isinstance(v, list):
            if v:
                lines.append(f"{k}:")
                for item in v:
                    lines.append(f"  - {item}")
            else:
                lines.append(f"{k}: []")
        elif isinstance(v, (int, float, bool)):
            lines.append(f"{k}: {v}")
        elif isinstance(v, str):
            if any(c in v for c in [":", "#", "'", '"', "\n", "{", "}", "[", "]", ",", "&", "*", "?", "|", "<", ">", "@", "`", "%"]):
                escaped = v.replace("'", "''")
                lines.append(f"{k}: '{escaped}'")
            elif v == "":
                lines.append(f"{k}: ''")
            else:
                lines.append(f"{k}: {v}")
        else:
            lines.append(f"{k}: {v}")
    return "\n".join(lines) + "\n"


# ============ CLI ============

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="PJ-102 反向链接构建器")
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args()

    result = build_backlinks()
    print(f"\n{'=' * 50}")
    print(f"🔗 反向链接构建完成")
    print(f"{'=' * 50}")
    print(f"扫描文件: {result['total_files']}")
    print(f"更新文件: {result['backlinks_added']}")
    print(f"有反向链接的实体: {result['entities_with_backlinks']}")
    if result.get("top_entities"):
        print(f"\n反向链接最多的实体:")
        for name, count in result["top_entities"]:
            print(f"  • {name}: {count} 个引用")
