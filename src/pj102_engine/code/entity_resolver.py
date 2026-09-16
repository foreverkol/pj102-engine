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

from entity_alias_guard import (
    is_junk_entity_name,
    split_aliases,
    strong_aliases,
    colliding_aliases,
)


class EntityResolver:
    """v7.0 §一 统一实体解析器"""

    def __init__(self, registry_path: Path, asr_alias_path=None):
        self.registry_path = Path(registry_path)
        self.registry = self._load()
        # ASR 音近错听映射表（**实例数据**，见 config/asr_alias.json，D-40/D-41）。
        # 显式传入优先；未传则按项目约定探测 <registry>/../../config/asr_alias.json。
        # 装载失败一律降级为空表 —— 引擎必须能在无该配置的环境（codex/hermes）跑通。
        if asr_alias_path is None:
            _cand = self.registry_path.parent.parent / "config" / "asr_alias.json"
            asr_alias_path = _cand if _cand.exists() else None
        try:
            from asr_alias import load_asr_alias
            self.asr_alias = load_asr_alias(asr_alias_path)
        except Exception:
            self.asr_alias = None

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

        # 1.2 ASR 音近错听 → 规范名（D-40/D-41）
        #     为什么放在 resolver 出口而不是提示词：错字是**源稿的固有属性**，
        #     LLM 无法自纠（它看到的就是错字）。在此映射一次，registry / wiki 页名 /
        #     双链全链路自动收敛，成本极低；改提示词或重跑 s6 都解决不了。
        canonical, _asr_hit = self._apply_asr(canonical, entity_type)
        # 别名同样过一遍映射（变体塌缩到同一规范名）；再剔除与 canonical 重复项，
        # 否则 aliases 里会出现"自己"（实测：海塑胶→海南数据交易平台后 aliases 只剩它自己）
        aliases = [a for a in self._apply_asr_list(aliases) if a and a != canonical]
        if _asr_hit and raw_name.strip() and raw_name.strip() != canonical:
            # 错字原名降为别名保留溯源（否则「海塑胶」这类源稿高频写法会检索不到）
            aliases = list(dict.fromkeys([raw_name.strip()] + aliases))

        # 1.3 别名自污染闸（D-32）：别名 == **另一实体的 canonical_name** → 剔除。
        #     为什么必须在 _find 之前：`王义` 的 aliases 曾含 `王老师`（另一实体的正式名），
        #     阶段 2 一旦命中就会把两个不同的人归成一个 id —— T4a 分裂的入口。
        #     注意 `self_canonical=canonical`：本实体自己的规范名出现在自己别名表属正常。
        _collided = []
        aliases, _collided = colliding_aliases(
            aliases, self._canonicals(), self_canonical=canonical)

        # 1.5 机器标签拦截：源稿口条/占位符**不得成为实体**
        #     实测（2026-09-16）s6 把 `发言人2`..`发言人8` 直接建成实体页
        #     → registry 出现 9 个垃圾 canonical + wiki 出现同名页。
        #     注意：**单字姓不在此拦截**（可能确有其人，只是源稿未给全名）。
        _junk, _why = is_junk_entity_name(canonical)
        if _junk:
            res = self._empty_result(entity_type, raw_name, aliases or [])
            res["junk_reason"] = _why
            return res

        # 2. 查 registry
        existing = self._find(canonical, aliases or [])
        if existing:
            # 已有 → update。**只并入强 alias**。
            # 纪律（2026-09-16 实测教训）：弱标识（梁总/杨总/发言人2/电话号码）
            # 一旦并入别名表，下次遇到持有同一弱标识的**另一个人**时就会误归并
            # → 级联放大成"实体黑洞"。弱标识另存 weak_aliases，仅供展示。
            ex_strong, ex_weak = split_aliases(existing.get("aliases"))
            new_strong, new_weak = split_aliases(aliases or [])
            merged_strong = list(dict.fromkeys(ex_strong + new_strong))
            merged_weak = list(dict.fromkeys(ex_weak + new_weak))
            # 存量别名同样过自污染闸（历史 registry 里已存在跨挂别名，不剪会继续发作）
            merged_strong, _dropped2 = colliding_aliases(
                merged_strong, self._canonicals(),
                self_canonical=existing["canonical_name"])
            existing["aliases"] = merged_strong
            if merged_weak:
                existing["weak_aliases"] = merged_weak
            existing["last_seen_at"] = self._now_iso()
            return {
                "entity_id": existing["entity_id"],
                "canonical_name": existing["canonical_name"],
                "aliases": merged_strong,
                "action": "update",
                "dropped_colliding_aliases": _collided + _dropped2,
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

        strong_new, weak_new = split_aliases(aliases or [])
        new_entity = {
            "entity_id": entity_id,
            "canonical_name": canonical,
            "aliases": strong_new,
            "entity_type": entity_type,
            "status_stage": "compiled",   # FR-v7.0-005
            "source_count": 1,
            "first_seen_at": self._now_iso(),
            "last_seen_at": self._now_iso(),
        }
        if weak_new:
            new_entity["weak_aliases"] = weak_new
        self.registry.setdefault("entities", []).append(new_entity)
        return {
            "entity_id": entity_id,
            "canonical_name": canonical,
            "aliases": strong_new,
            "action": "create",
            "dropped_colliding_aliases": _collided,
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

    def _apply_asr(self, name: str, entity_type: str = ""):
        """ASR 错听 → 规范名。返回 (mapped_name, hit: bool)。

        **类型护栏**：若映射组声明的类型与本次请求类型不符（例如把 person 名
        映射到 organization），则**不映射** —— 这种情形多半是"同一串音既被当成人
        也被当成机构"，交人工裁决比自动归并安全（与实体黑洞的教训同源）。

        **例外（D-40-c）**：该名字若被人工裁决后写入组的 `cross_type_variants`，
        则放行 —— 用于「机构音近错听被 LLM 建成人物页」的错型（如 `韩淑娇`）。
        **默认全拒、显式放行**，不做任何自动推断。
        """
        tbl = getattr(self, "asr_alias", None)
        if not tbl or not name:
            return name, False
        mapped = tbl.map(name)
        if mapped == name:
            return name, False
        gtype = (tbl.group_of(name) or {}).get("type", "")
        if (gtype and entity_type and gtype != entity_type
                and tbl.allows_cross_type(name) is not True):
            return name, False
        return mapped, True

    def _apply_asr_list(self, names):
        """批量映射别名（变体塌缩到 canonical 后自然去重保序）"""
        tbl = getattr(self, "asr_alias", None)
        if not tbl:
            return list(names or [])
        return tbl.map_all(names or [])

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

    def _canonicals(self) -> list:
        """全量 canonical_name（供别名自污染闸判定"这个名字已被别的实体占用"）。"""
        return [e.get("canonical_name") for e in self.registry.get("entities", [])
                if e.get("canonical_name")]

    def _find(self, canonical: str, aliases: list) -> Optional[dict]:
        """两阶段归并查找（确定性）。

        阶段 1 —— canonical 精确匹配**优先**。原实现把 canonical 匹配与 alias 命中
        放在同一个循环里，返回值**取决于 registry 遍历顺序**：`梁超杰` 既是
        `person_3bdbca59` 的 canonical，又出现在 `person_71add69e` 的 aliases 里
        → 谁排前面就归给谁（不确定性 bug，2026-09-16 实测）。

        阶段 2 —— 仅**强 alias** 命中才归并。弱标识（泛化称呼 `梁总`、源稿口条
        `发言人2`、电话号码、单字姓、带注解）不得作为归并依据。
        """
        ents = self.registry.get("entities", [])
        # 阶段 1: canonical 精确
        for e in ents:
            if e.get("canonical_name") == canonical:
                return e
        # 阶段 2: 强 alias 命中
        strong = strong_aliases(aliases)
        if not strong:
            return None
        for e in ents:
            if any(a in strong_aliases(e.get("aliases")) for a in strong):
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
