# -*- coding: utf-8 -*-
"""ASR 音近错听别名装载器（引擎级 · 纯规则 · 零实例数据）

为什么单独成模块
----------------
ASR 会稳定地把「数交」听成「塑胶」、「布比」听成「不比」、「蒋海」听成「江海」。
这些错字**是源稿的固有属性**，LLM 无法自纠（它看到的就是错字）。
把映射放在 resolver 出口（而非提示词里）成本最低、也最可靠。

纪律（与 config/speaker_alias.json 同规）
----------------------------------------
- **本模块只提供"装载 + 查表"能力，不内置任何条目** → 可原样移植到 codex / hermes 环境。
- 条目属**实例数据**，落在 `config/asr_alias.json`，由实例提供、实例负责。
- 装载失败（文件缺失 / JSON 坏）**不抛异常**，降级为空表 —— 保证三环境都能跑。

跨类型授权（D-40-c，王老师 2026-09-16 裁决）
--------------------------------------------
类型护栏默认生效：组声明 organization 时，一个被当成 person 的同名条目**不映射**。
但实测存在「机构名被 LLM 建成人物页」的错型（如 `郑树浇` / `韩淑娇` 被当成"负责人"）。
这类条目须由**人工裁决后逐条授权**，在组里写 `cross_type_variants: [...]`。
**默认拒绝、显式放行** —— 不做任何自动推断。

用法
----
    from asr_alias import load_asr_alias
    tbl = load_asr_alias(cfg.paths.root / "config" / "asr_alias.json")
    tbl.map("海塑胶")        # -> "海南数据交易平台"
    tbl.map("海南数据交易平台")  # -> "海南数据交易平台"（幂等）
    tbl.map("张三")          # -> "张三"（未收录，原样返回）
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Optional


class AsrAliasTable:
    """变体 → 规范名 的只读查表器。构造后不可变，可安全共享。"""

    def __init__(self, groups: Optional[List[dict]] = None,
                 pending: Optional[List[dict]] = None):
        self._index: Dict[str, str] = {}       # variant -> canonical
        self._groups: Dict[str, dict] = {}     # canonical -> group(原样)
        self._type_of: Dict[str, str] = {}     # canonical -> person|organization
        self._cross_type: set = set()          # 被显式授权可跨类型映射的变体名
        self._pending: List[dict] = list(pending or [])

        for g in (groups or []):
            if not isinstance(g, dict):
                continue
            canon = str(g.get("canonical", "")).strip()
            if not canon:
                continue
            # 撞车检测：同一 canonical 出现两次 → 后者不覆盖前者（保守）
            if canon in self._groups:
                continue
            self._groups[canon] = g
            self._type_of[canon] = str(g.get("type", "")).strip()
            # 跨类型授权名单：默认空 → 类型护栏对所有条目生效
            for v in (g.get("cross_type_variants") or []):
                v = str(v).strip()
                if v:
                    self._cross_type.add(v)
            # canonical 自身映射到自己（幂等锚点）
            self._index[canon] = canon
            for v in (g.get("variants") or []):
                v = str(v).strip()
                if not v or v == canon:
                    continue
                # 变体撞车：先到先得，且**不覆盖已有的 canonical 锚点**
                # （防 `X` 既是 A 的变体又是 B 的 canonical 时被改写归属）
                if v in self._index and self._index[v] != v:
                    continue
                if v in self._groups:
                    continue
                self._index[v] = canon

    # ---------- 查询 ----------

    def map(self, name: str) -> str:
        """变体 → 规范名。未收录则原样返回（**不做子串匹配**，避免误伤）。"""
        n = (name or "").strip()
        if not n:
            return n
        return self._index.get(n, n)

    def is_known(self, name: str) -> bool:
        return (name or "").strip() in self._index

    def is_canonical(self, name: str) -> bool:
        return (name or "").strip() in self._groups

    def type_of(self, name: str) -> str:
        """返回 person / organization / ''（未收录）"""
        return self._type_of.get(self.map(name), "")

    def group_of(self, name: str) -> Optional[dict]:
        return self._groups.get(self.map(name))

    def allows_cross_type(self, name: str) -> bool:
        """该名称是否被**显式授权**可跨类型映射（默认全拒）。

        用途：`郑树浇` / `韩淑娇` 这类「机构名被建成人物页」的错型，
        须在 `cross_type_variants` 里逐条放行，才允许 person → organization 归并。
        """
        return (name or "").strip() in self._cross_type

    def cross_type_names(self) -> List[str]:
        return sorted(self._cross_type)

    def canonical_names(self) -> List[str]:
        return list(self._groups.keys())

    def map_all(self, names) -> List[str]:
        """批量映射 + 去重保序（变体塌缩到 canonical 后自然去重）"""
        seen, out = set(), []
        for x in (names or []):
            m = self.map(str(x))
            if m and m not in seen:
                seen.add(m)
                out.append(m)
        return out

    @property
    def pending(self) -> List[dict]:
        """有歧义、刻意**不入表**的条目（供审计/报告展示）"""
        return list(self._pending)

    def __len__(self) -> int:
        return len(self._groups)

    def __bool__(self) -> bool:
        return bool(self._groups)


def load_asr_alias(path) -> AsrAliasTable:
    """从 JSON 装载。文件不存在 / 解析失败 → 返回空表（**不抛异常**）。"""
    if not path:
        return AsrAliasTable()
    p = Path(path)
    if not p.exists():
        return AsrAliasTable()
    try:
        data = json.loads(p.read_text(encoding="utf-8-sig"))
    except Exception:
        return AsrAliasTable()
    if not isinstance(data, dict):
        return AsrAliasTable()
    return AsrAliasTable(groups=data.get("groups"),
                         pending=data.get("pending"))


def default_alias_path(config_dir) -> Path:
    """约定位置：<config_dir>/asr_alias.json"""
    return Path(config_dir) / "asr_alias.json"
