"""
v7.0 FR-v7.0-003/004 实体统一编号 + canonical_name + aliases + 消歧

核心方法:
  resolve_or_create(entity_type, raw_name, aliases=[], context=None)
    -> {entity_id, canonical_name, aliases, action, disambiguation_candidates}

entity_id 格式:
  person_{canonical_name_hash8}_{seq4}
  org_{canonical_name_hash8}_{seq4}

registry 持久化:
  pipeline.py 启动时 load,处理中 in-memory 累积,结束时 save。
  系统文件: SYSTEM/registry/entity_registry.json (append-only)
"""

import hashlib
import json
from pathlib import Path
from typing import Optional


class EntityResolver:
    """v7.0 §一 统一实体解析器"""

    def __init__(self, registry_path: Path):
        self.registry_path = Path(registry_path)
        self.registry = self._load()

    # ============ Public API ============

    def resolve_or_create(
        self,
        entity_type: str,        # "person" | "organization"
        raw_name: str,
        aliases: list = None,
        context: dict = None,
    ) -> dict:
        """返回 {entity_id, canonical_name, aliases, action, disambiguation_candidates}"""
        if entity_type not in ("person", "organization"):
            raise ValueError(f"unsupported entity_type: {entity_type}")

        # 1. 规范化
        canonical = self._normalize(raw_name)
        if not canonical:
            return self._empty_result(entity_type, raw_name, aliases or [])

        # 2. 查 registry
        existing = self._find(canonical, aliases or [])
        if existing:
            # 已有 → update (aliases merge)
            new_aliases = list(set(existing.get("aliases", []) + (aliases or [])))
            existing["aliases"] = new_aliases
            existing["last_seen_at"] = self._now_iso()
            return {
                "entity_id": existing["entity_id"],
                "canonical_name": existing["canonical_name"],
                "aliases": new_aliases,
                "action": "update",
                "disambiguation_candidates": [],
            }

        # 3. 新建
        # entity_type 短名映射(§8.3 + 实体编号实践规范)
        type_prefix = {"person": "person", "organization": "org"}.get(
            entity_type, entity_type
        )
        pinyin_prefix = self._to_pinyin_prefix(canonical)
        seq = self._next_seq(type_prefix, pinyin_prefix)
        entity_id = f"{type_prefix}_{pinyin_prefix}_{seq:04d}"

        new_entity = {
            "entity_id": entity_id,
            "canonical_name": canonical,
            "aliases": aliases or [],
            "entity_type": entity_type,
            "status_stage": "compiled",   # FR-v7.0-005
            "source_count": 1,
            "first_seen_at": self._now_iso(),
            "last_seen_at": self._now_iso(),
        }
        self.registry.setdefault("entities", []).append(new_entity)
        return {
            "entity_id": entity_id,
            "canonical_name": canonical,
            "aliases": aliases or [],
            "action": "create",
            "disambiguation_candidates": self._find_similar(canonical),
        }

    def save(self):
        """持久化到 registry.json"""
        self.registry["last_updated"] = self._now_iso()
        self.registry_path.parent.mkdir(parents=True, exist_ok=True)
        self.registry_path.write_text(
            json.dumps(self.registry, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def get_entity(self, entity_id: str) -> Optional[dict]:
        for e in self.registry.get("entities", []):
            if e.get("entity_id") == entity_id:
                return e
        return None

    def list_entities(self, entity_type: str = None) -> list:
        ents = self.registry.get("entities", [])
        if entity_type:
            return [e for e in ents if e.get("entity_type") == entity_type]
        return ents

    # ============ Private ============

    def _load(self) -> dict:
        if not self.registry_path.exists():
            return {
                "version": "1.0",
                "schema": "v7.0",
                "last_updated": "",
                "entities": [],
            }
        return json.loads(self.registry_path.read_text(encoding="utf-8"))

    def _normalize(self, name: str) -> str:
        if not name:
            return ""
        return name.strip().replace(" ", "").replace("\u3000", "")

    def _to_pinyin_prefix(self, name: str) -> str:
        """简化版:用 md5 前 8 字符(生产环境应用 pypinyin 真实拼音)"""
        return hashlib.md5(name.encode("utf-8")).hexdigest()[:8]

    def _next_seq(self, entity_type: str, prefix: str) -> int:
        existing = [
            int(e["entity_id"].split("_")[-1])
            for e in self.registry.get("entities", [])
            if e["entity_id"].startswith(f"{entity_type}_{prefix}")
            and e["entity_id"].split("_")[-1].isdigit()
        ]
        return max(existing, default=0) + 1

    def _find(self, canonical: str, aliases: list) -> Optional[dict]:
        for e in self.registry.get("entities", []):
            if e["canonical_name"] == canonical:
                return e
            # aliases 反查
            existing_aliases = e.get("aliases", [])
            if any(a in existing_aliases for a in aliases if a):
                return e
        return None

    def _find_similar(self, canonical: str) -> list:
        """简易消歧:包含关系"""
        candidates = []
        for e in self.registry.get("entities", []):
            cn = e.get("canonical_name", "")
            if cn and cn != canonical and (canonical in cn or cn in canonical):
                candidates.append({
                    "entity_id": e.get("entity_id"),
                    "canonical_name": cn,
                    "match_score": 0.5,
                    "reason": "包含关系",
                })
        return candidates[:3]

    def _empty_result(self, entity_type, raw_name, aliases):
        return {
            "entity_id": f"{entity_type}_invalid_{hashlib.md5(raw_name.encode()).hexdigest()[:4]}",
            "canonical_name": raw_name,
            "aliases": aliases,
            "action": "skip",
            "disambiguation_candidates": [],
        }

    @staticmethod
    def _now_iso() -> str:
        from datetime import datetime, timezone
        return datetime.now(timezone.utc).isoformat()
