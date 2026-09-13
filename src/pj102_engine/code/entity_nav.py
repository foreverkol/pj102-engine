"""
v3.0 entity_nav.py - L1 实体导航(借鉴 PJ-001 v6.0 §7)

无 LLM 调用,纯规则匹配,毫秒级响应。

输入: 主理人的查询(如 "我与浙商银行上次聊到什么程度")
输出:
  {
    "matches": [
      {"type": "organization", "canonical_name": "浙商银行",
       "entity_id": "org_xxx_0001", "match_score": 1.0,
       "occurrences": 5, "last_seen_at": "..."},
      {"type": "person", "canonical_name": "陈凌昌", ...}
    ],
    "fallback_to_llm": False
  }

fallback 到 kb_retriever.L2 语义综合 当且仅当:
  - matches 为空
  - 用户问题明显是综合查询(多实体、跨主题)
"""

import json
import re
import sys
from pathlib import Path
from datetime import datetime, timezone


class EntityNav:
    """L1 实体导航器"""

    def __init__(self, registry_path: Path, persons_master_path: Path):
        self.registry = self._load_json(registry_path)
        self.persons_master = self._load_json(persons_master_path)

    def nav(self, query: str) -> dict:
        """主入口"""
        # 1. 提取 query 中的实体名(中文姓名 / 机构名)
        candidates = self._extract_candidates(query)
        if not candidates:
            return {"matches": [], "fallback_to_llm": True}

        # 2. 查 registry 匹配(按 entity_id 去重)
        seen = set()
        matches = []
        for cand in candidates:
            entity = self._find_entity(cand)
            if entity and entity["entity_id"] not in seen:
                seen.add(entity["entity_id"])
                matches.append(self._enrich(entity))

        # 3. 决定 fallback
        fallback = self._should_fallback(query, matches)
        return {"matches": matches, "fallback_to_llm": fallback}

    def _extract_candidates(self, query: str) -> list:
        """从 query 中提取候选实体名
        简化版:中文 2-6 字 + 部分已知关键字(银行/科技/合作)"""
        # 模式 1:明确提到的"银行/科技/公司"前后
        result = []

        # 模式 1a:"浙商银行"、"微众银行"、"星辰科技"等
        org_keywords = ["银行", "科技", "公司", "集团", "证券", "保险",
                       "保理", "信托", "金服"]
        for kw in org_keywords:
            m = re.search(r"([\u4e00-\u9fff]{2,6}" + kw + ")", query)
            if m:
                result.append(m.group(1))

        # 模式 1b:中文姓名 2-4 字
        # 简单启发:query 中"X总"、"X行长" 等
        title_keywords = ["总", "行长", "经理", "教授", "主任"]
        for kw in title_keywords:
            m = re.search(r"([\u4e00-\u9fff]{2,3})" + kw, query)
            if m:
                result.append(m.group(1))

        # 模式 1c:已知 entity 名直接匹配(如果 query 含完整 entity 名)
        for ent in self.registry.get("entities", []):
            if ent.get("canonical_name", "") in query:
                result.append(ent["canonical_name"])
            # 包含 aliases
            for alias in ent.get("aliases", []):
                if alias in query:
                    result.append(ent["canonical_name"])

        return list(set(result))

    def _find_entity(self, name: str) -> dict:
        """在 registry 中查找实体"""
        for ent in self.registry.get("entities", []):
            if ent.get("canonical_name") == name:
                return ent
            if name in ent.get("aliases", []):
                return ent
        # 模糊匹配:包含关系
        for ent in self.registry.get("entities", []):
            cn = ent.get("canonical_name", "")
            if cn and (name in cn or cn in name):
                return ent
        return None

    def _enrich(self, entity: dict) -> dict:
        """补充 master 中的 occurrences 和 last_seen"""
        entity_type = entity.get("entity_type")
        canonical = entity.get("canonical_name")
        master_key = "persons" if entity_type == "person" else "organizations"
        master_data = self.persons_master.get(master_key, {}).get(canonical, {})
        observations = master_data.get("observations", [])
        return {
            "type": entity_type,
            "canonical_name": canonical,
            "entity_id": entity["entity_id"],
            "aliases": entity.get("aliases", []),
            "match_score": 1.0,
            "occurrences": len(observations),
            "last_seen_at": entity.get("last_seen_at", ""),
            "first_seen_at": entity.get("first_seen_at", ""),
            "status_stage": entity.get("status_stage", "compiled"),
        }

    def _should_fallback(self, query: str, matches: list) -> bool:
        """决定 fallback 到 L2"""
        if not matches:
            return True
        # 综合类查询关键词
        complex_keywords = ["综合", "总结", "演化", "对比", "全部",
                            "所有", "跨", "总览", "整体"]
        if any(kw in query for kw in complex_keywords):
            return True
        return False

    @staticmethod
    def _load_json(path: Path) -> dict:
        path = Path(path)
        if not path.exists():
            return {}
        return json.loads(path.read_text(encoding="utf-8"))


# ============ CLI ============

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--query", required=True)
    parser.add_argument("--registry", required=True)
    parser.add_argument("--persons-master", required=True)
    parser.add_argument("--bench", action="store_true",
                       help="用 benchmark 模式(快速 smoke test)")
    args = parser.parse_args()

    nav = EntityNav(Path(args.registry), Path(args.persons_master))
    result = nav.nav(args.query)
    print(json.dumps(result, ensure_ascii=False, indent=2))
