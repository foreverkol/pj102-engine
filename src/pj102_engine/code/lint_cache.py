# -*- coding: utf-8 -*-
"""lint_cache: 管线缓存/摘要层质量维度 (v2.2.5)

与 lint_wiki 互补: lint_wiki 只看 wiki 产物, 本模块只看**上游缓存层**。
分开的理由: ① 保持 lint_wiki 的 12 维契约稳定 (零回归, 兼容既有消费方);
② 缓存口径依赖实例目录 (system/cache), 属运行时状态而非发布物契约。

维度 (4):
  C1_cache_completeness  断点续跑缓存覆盖 —— 逐样本列出缺步 (NFR-03 口径)
  C2_cache_validity      缓存内容有效性 —— 「文件存在」≠「已缓存」;
                         含**元话语检测** (模型返回思考过程文本, 实测风险 R-1)
  C3_s3_sentinel         s3 空产出哨兵值 —— one_sentence 为占位值时**仍照写盘**,
                         是下游 s15 重放链断裂的直接根因
  C4_summary_dup         摘要页「(N)」副本残留 —— s15 命名判定的回归哨兵

用法:
  from lint_cache import lint_cache
  report = lint_cache(project_root)      # {维度: [问题描述, ...]}

CLI: python code/lint_cache.py [--json out.json]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Dict, List

# 断点续跑步骤全集 (s12 不写缓存, 结构性排除)
STEPS = ["s1", "s2", "s3", "s4", "s5", "s6", "s7", "s8", "s9", "s10",
         "s11", "s13", "s14", "s15"]

PLACEHOLDERS = {"", "未提取", "N/A", "n/a", "null", "None", "无", "未知", "待补充"}

# 各步"至少一个关键字段非空"才视为有效 (且必须存在于该步产物中)
KEY_FIELDS = {
    "s2": ["scene_type", "meeting_subtype"],
    "s3": ["one_sentence"],
    "s4": ["judgments", "facts"],
    "s5": ["implicit_knowledge", "insights", "items"],
    "s6": ["persons", "organizations"],
    "s7": ["decisions", "action_items", "topic_key"],
    "s8": ["risks", "blindspots"],
    "s9": ["classifications", "categories", "tags"],
    "s10": ["ldamc", "refined", "items"],
    "s11": ["value", "rating", "scores"],
    "s13": ["params", "financial_params", "items"],
    "s14": ["scenarios"],
    "s15": ["pages", "entities"],
}

# R-1: 元话语 / 推理腔标记 —— 模型偶尔把"思考过程"当答案返回。
# 一旦这类文本被当作产物落盘, 会出现"缓存填满但填垃圾"(比空缓存更难发现)。
META_DISCOURSE_RE = re.compile(
    r"The user is asking|I should reply|I need to (?:reply|respond|answer)|"
    r"Let me (?:think|respond|answer)|As an AI|思考过程|我需要回复|用户要求我|"
    r"让我(?:想想|回复)|以下是思考|chain of thought",
    re.I,
)

DUP_SUFFIX_RE = re.compile(r"（\d+）\.md$")


def _degenerate(v) -> bool:
    if v is None:
        return True
    if isinstance(v, str):
        return v.strip() in PLACEHOLDERS
    if isinstance(v, (list, dict)):
        return len(v) == 0
    return False


def _meta_discourse(v) -> bool:
    """递归检查字符串值是否含元话语标记"""
    if isinstance(v, str):
        return bool(META_DISCOURSE_RE.search(v))
    if isinstance(v, dict):
        return any(_meta_discourse(x) for x in v.values())
    if isinstance(v, list):
        return any(_meta_discourse(x) for x in v)
    return False


def judge_step(step: str, data) -> tuple:
    """返回 (是否退化, 理由)。保守判据: 只判明确退化。

    注意: s13/s14 合法产物是 list 而非 dict —— 非空 list 视为有效,
    否则大面积误报 (2026-09-16 实测修正)。
    """
    if data is None:
        return True, "null"
    if isinstance(data, list):
        if not data:
            return True, "空 list"
        return (True, "list 全空项") if all(_degenerate(x) for x in data) \
            else (False, "")
    if not isinstance(data, dict):
        return True, f"非预期类型 {type(data).__name__}"
    if not data:
        return True, "空 dict"
    if all(_degenerate(v) for v in data.values()):
        return True, "全字段空/占位"
    keys = KEY_FIELDS.get(step) or []
    have = [k for k in keys if k in data]
    if have and all(_degenerate(data.get(k)) for k in have):
        return True, f"关键字段全空 {have}"
    if _meta_discourse(data):
        return True, "元话语/推理腔泄漏 (R-1)"
    return False, ""


def lint_cache(project_root) -> Dict[str, List[str]]:
    """返回 {维度: [问题描述, ...]}；维度计数 = len(list)"""
    project_root = Path(project_root)
    cache_root = project_root / "system" / "cache" / "steps"
    wiki = project_root / "wiki"

    incomplete: List[str] = []
    invalid: List[str] = []
    sentinel: List[str] = []
    dup: List[str] = []

    if cache_root.exists():
        dirs = sorted(d for d in cache_root.iterdir() if d.is_dir())
        for d in dirs:
            present, deg = [], []
            for f in sorted(d.glob("s*.json")):
                step = f.stem
                if step not in STEPS:
                    continue
                present.append(step)
                try:
                    data = json.loads(f.read_text(encoding="utf-8"))
                except Exception:
                    deg.append((step, "不可解析"))
                    continue
                bad, why = judge_step(step, data)
                if bad:
                    deg.append((step, why))
                    invalid.append(f"{d.name}/{step}: {why}")
                    if step == "s3":
                        sentinel.append(
                            f"{d.name}: s3 为哨兵值/空产出 (one_sentence="
                            f"{str((data or {}).get('one_sentence'))[:12]!r})")
            missing = [s for s in STEPS if s not in present]
            if missing:
                incomplete.append(f"{d.name}: 缺 {len(missing)} 步 {missing}")

    # C4: 摘要页「(N)」副本残留 (s15 命名判定回归哨兵)
    summ = wiki / "Summaries"
    if summ.exists():
        for p in sorted(summ.glob("*.md")):
            if DUP_SUFFIX_RE.search(p.name):
                dup.append(f"Summaries/{p.name}")

    return {
        "C1_cache_completeness": incomplete,
        "C2_cache_validity": invalid,
        "C3_s3_sentinel": sentinel,
        "C4_summary_dup": dup,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default="")
    ap.add_argument("--json", default="")
    args = ap.parse_args()

    root = Path(args.root) if args.root else Path(__file__).resolve().parent.parent
    rep = lint_cache(root)
    for dim, items in rep.items():
        print(f"{dim}: {len(items)}")
        for x in items[:8]:
            print("   -", x)
        if len(items) > 8:
            print(f"   ... 另有 {len(items) - 8} 条")
    if args.json:
        Path(args.json).write_text(
            json.dumps(rep, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n报告: {args.json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
