"""署名规范化引擎（幂等）—— 把转写稿口条噪声从 [判断:...] 署名中剥离。

【成因 · 2026-09-16 定位】
源转写稿的口条形如（43 个源文件共 49 个去重标签）：
    发言人梁超杰 / 发言人本人王老师 / 发言人浙江慧穗科技老板黄国华 / 发言人4
而 s3 提示词占位符又写作 ``[判断:发言人姓名]`` —— 模型遂把「发言人」「本人」
等**转写标签**原样带入署名，产出 ``[判断:发言人本人王老师]``。

【三层处置 · 全部幂等、可单测】
    T1 剥离转写标签前缀：发言人 / 发言人N / 说话人 / 发信人 / speaker / 本人
    T2 多署名拆分与双链归一：'A/B' → 'A、B'；label 内已有 ``[[X|Y]]`` 时只清前缀
    T3 白名单归约：label 含白名单人名的**唯一最长匹配** → 归约为该人名

【纪律】
    * T3 是**保守**的：并列最长（如 '梁超杰梁老师' 同时含 梁超杰/梁老师）时不猜，
      记入 residual，交人工裁决。
    * 纯数字标签（'发言人4'）清洗后为空 → 不猜、不删，保持原样并计入 residual。
    * 全程只做「减前缀 / 归一名」，**不改动 statement 正文**，无内容丢失风险。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import Counter
from pathlib import Path

# ---- T2: 必须支持嵌套双链，否则 '发言人1[[Entities/Persons/孙老师|孙老师]]' 会被截断 ----
_JUDGMENT_RE = re.compile(r"\[判断:((?:\[\[[^\]]*\]\]|[^\[\]])*)\]")

# ---- T1 ----
_TRANS_PREFIX_RE = re.compile(r"^\s*(?:发言人|说话人|发信人|发言人?本人|speaker)\s*\d*\s*", re.I)
_BENREN_PREFIX_RE = re.compile(r"^\s*本人\s*")

# ---- T2 ----
_MULTI_SEP_RE = re.compile(r"[/／、，,]")

# 双链掩码：wikilink 内含 '/'（如 [[Entities/Persons/孙老师|孙老师]]），
# 若直接做多署名拆分会把链接切碎 —— 故先掩码、后处理、末了还原。
_WIKILINK_RE = re.compile(r"\[\[[^\]]*\]\]")
_MASK_FMT = "\x00{}\x00"


def _mask_links(s: str) -> tuple[str, list[str]]:
    links: list[str] = []

    def _rep(m: re.Match) -> str:
        links.append(m.group(0))
        return _MASK_FMT.format(len(links) - 1)

    return _WIKILINK_RE.sub(_rep, s), links


def _unmask(s: str, links: list[str]) -> str:
    if not links:
        return s
    return re.sub(r"\x00(\d+)\x00", lambda m: links[int(m.group(1))], s)

# 转述/引用护栏：命中则**禁止**归约（归错人比不归约更糟）
_RELAY_RE = re.compile(r"转述|转引|转达|提到|引用|据说|听闻|代(?:表|为)")

# 机构/职位残留标记（非人名标签的兜底识别，仅用于打标不用于改写）
_ORGROLE_RE = re.compile(
    r"公司|科技|研究院|学院|集团|银行|平台|网|会|中心|老板|顾问|会长|行长|局长|处长|院长|"
    r"总经理|总裁|总监|经理|主任|董事|博士|老师|律师|医师|团队|工作|人员|同事|同学"
)

# 泛指词 / 非实体（不得进入实体表）
_GENERIC_ENTITY_RE = re.compile(
    r"(几位|各位|多人|某人|一些|若干|相关方|团队|未知|待补|用户\(|不详)"
)

# 实例白名单由 config/speaker_alias.json 提供；引擎侧保持空（主体名无关）
_DEFAULT_CANONICAL: list = []


# --------------------------------------------------------------------------
# 配置
# --------------------------------------------------------------------------
def load_alias_config(path: str | os.PathLike | None = None) -> dict:
    """读取 config/speaker_alias.json；缺失时回退到内置最小白名单。"""
    if path is None:
        root = Path(__file__).resolve().parent.parent
        path = root / "config" / "speaker_alias.json"
    path = Path(path)
    if path.exists():
        try:
            cfg = json.loads(path.read_text(encoding="utf-8-sig"))
        except Exception:
            cfg = {}
    else:
        cfg = {}
    cfg.setdefault("canonical_names", list(_DEFAULT_CANONICAL))
    cfg.setdefault("alias_map", {})
    return cfg


def _longest_canonical(label: str, canonical: list[str]) -> tuple[str | None, int]:
    """返回 (唯一最长匹配的人名 or None, 匹配到的候选数)。"""
    hits = [n for n in canonical if n and n in label]
    if not hits:
        return None, 0
    top = max(len(n) for n in hits)
    best = [n for n in hits if len(n) == top]
    if len(best) == 1:
        return best[0], len(hits)
    return None, len(hits)


# --------------------------------------------------------------------------
# T1
# --------------------------------------------------------------------------
def strip_trans_prefix(label: str) -> tuple[str, bool]:
    """剥离转写标签前缀（循环至稳定，故 '发言人本人王老师' → '王老师'）。"""
    s = label.strip()
    changed = False
    while True:
        n = _TRANS_PREFIX_RE.sub("", s, count=1)
        n = _BENREN_PREFIX_RE.sub("", n, count=1)
        if n == s:
            break
        s, changed = n, True
    return s.strip(), changed


def is_noisy(label: str) -> bool:
    """是否含转写标签噪声（供 lint / 门禁统计）。"""
    return bool(_TRANS_PREFIX_RE.match(label.strip()) or _BENREN_PREFIX_RE.match(label.strip()))


# --------------------------------------------------------------------------
# 单条署名清洗
# --------------------------------------------------------------------------
def clean_label(label: str, cfg: dict | None = None, enable_t3: bool = True) -> tuple[str, str]:
    """清洗单条署名。返回 (cleaned, reason)。

    reason ∈ {'alias','clean','prefix','canonical','multi','residual-tie',
              'residual-empty','residual-relay','residual-orgrole','residual'}
    """
    cfg = cfg or load_alias_config()
    raw = label.strip()
    if not raw:
        return "", "clean"

    # 显式别名表优先（人工裁决过的硬映射）
    alias = cfg.get("alias_map", {})
    if raw in alias:
        return alias[raw].strip(), "alias"

    canonical = cfg.get("canonical_names", [])

    # 掩码保护双链后处理
    masked, links = _mask_links(raw)

    # 多署名拆分（T2）：任一分量清洗失败则退回整体路径，避免误伤
    if _MULTI_SEP_RE.search(masked):
        parts = [p for p in _MULTI_SEP_RE.split(masked) if p.strip()]
        out, reasons = [], []
        for p in parts:
            c, r = clean_label(_unmask(p, links) if links else p, cfg, enable_t3)
            if not c or r.startswith("residual"):
                out, reasons = [], []
                break
            out.append(c)
            reasons.append(r)
        if out:
            joined = "、".join(dict.fromkeys(out))          # 去重且保序
            rs = "clean" if all(r == "clean" for r in reasons) else "multi"
            return (joined, rs) if joined != raw else (raw, "clean")

    # T1
    s_masked, prefixed = strip_trans_prefix(masked)
    s = _unmask(s_masked, links)

    # label 本体就是一个/多个双链 → 只清前缀，交给 entity 链接器
    if re.fullmatch(r"(?:\x00\d+\x00|\s)+", s_masked) and links:
        return (s, "prefix") if prefixed else (raw, "clean")

    if not s.strip():
        return raw, "residual-empty"

    if canonical and s in canonical:
        return (s, "prefix") if prefixed else (s, "clean")

    # T3 白名单归约（保守）—— 仍含双链时不做归约，避免吃掉链接外的文字
    if enable_t3 and canonical and "[[" not in s:
        if _RELAY_RE.search(s):                              # 转述护栏：不归约
            return (s, "prefix") if prefixed else (s, "residual-relay")
        hit, n = _longest_canonical(s, canonical)
        if hit:
            return (hit, "canonical") if hit != s else (s, "clean")
        if n > 1:
            return s, "residual-tie"
        if not prefixed and _ORGROLE_RE.search(s):           # 像机构/职位而非人名
            return s, "residual-orgrole"

    return (s, "prefix") if prefixed else (s, "clean")


# --------------------------------------------------------------------------
# 全文清洗
# --------------------------------------------------------------------------
def clean_text(text: str, cfg: dict | None = None, enable_t3: bool = True) -> tuple[str, dict]:
    """清洗文本中所有 [判断:...]。返回 (新文本, 统计)。幂等。"""
    cfg = cfg or load_alias_config()
    stats: Counter = Counter()

    def _sub(m: re.Match) -> str:
        label = m.group(1)
        cleaned, reason = clean_label(label, cfg, enable_t3)
        stats[reason] += 1
        if cleaned != label:
            stats["changed"] += 1
        return f"[判断:{cleaned}]"

    new = _JUDGMENT_RE.sub(_sub, text)
    return new, dict(stats)


def iter_judgment_labels(text: str):
    """产出文本中所有 [判断:...] 的 label（供 lint 统计）。"""
    for m in _JUDGMENT_RE.finditer(text):
        yield m.group(1)


def count_noise(text: str) -> int:
    return sum(1 for lab in iter_judgment_labels(text) if is_noisy(lab))


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------
def _scan(root: Path, exts=(".md",)) -> list[Path]:
    out = []
    for p in root.rglob("*"):
        if p.is_file() and p.suffix in exts:
            out.append(p)
    return sorted(out)


# --------------------------------------------------------------------------
# 行尾保真读写（关键：Windows 文本模式写回会把 LF 静默改成 CRLF —— 2026-09-16 踩坑）
# --------------------------------------------------------------------------
def read_preserving(path: Path) -> str:
    with open(path, "r", encoding="utf-8", errors="ignore", newline="") as f:
        return f.read()


def write_preserving(path: Path, text: str) -> None:
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(text)


def normalize_newlines_tree(root: Path, exts=(".md",), apply: bool = False) -> dict:
    """把 CRLF 归一为 LF（wiki 正统行尾），二进制保真、不改其它任何字节。

    为什么放管线出口而非逐点改调用点: 全仓 40+ 处 ``write_text`` 未指定 newline,
    Windows 下按平台默认把 ``\\n`` 折成 CRLF → 混合行尾库被单向拉平, 污染
    文件级审计（2026-09-16 实测一次补跑位移 710 文件、内容逐字全等）。
    逐点改风险高, 故在出口做一次确定性归一。
    """
    files = _scan(root, exts)
    changed = []
    for p in files:
        raw = p.read_bytes()
        if b"\r\n" not in raw:
            continue
        changed.append(str(p))
        if apply:
            p.write_bytes(raw.replace(b"\r\n", b"\n"))   # 二进制写, 零折行风险
    return {"files_scanned": len(files), "files_changed": len(changed),
            "changed_files": changed}


def normalize_tree(root: Path, exts=(".md",), alias_cfg: dict | None = None,
                   enable_t3: bool = True, apply: bool = False,
                   normalize_newlines: bool = False) -> dict:
    """wiki 文本规范化 = 署名清洗(T1/T2/T3) + 可选行尾归一。**幂等**。

    这是管线出口的统一兜底: 无论上游哪个模块以何种方式写入, 出口一次校正。

    ⚠ ``normalize_newlines`` **默认关闭** (2026-09-16 校准):
    实测 wiki 长期是混合行尾态 (708 CRLF / 17 LF, 自 pre_speakernorm 快照起未变),
    一次性归一会改写 708 个文件 —— 这属**批量破坏性变更**, 必须显式授权,
    不能由管线默认触发。故此项只在显式开启时才生效。
    """
    files = _scan(root, exts)
    cfg = alias_cfg if alias_cfg is not None else load_alias_config()

    before_total = after_total = 0
    changed_files, residuals = [], []
    agg: Counter = Counter()
    for p in files:
        text = read_preserving(p)
        b = count_noise(text)
        new, st = clean_text(text, cfg, enable_t3=enable_t3)
        a = count_noise(new)
        if b or _JUDGMENT_RE.search(text):
            before_total += b
            after_total += a
            for k, v in st.items():
                agg[k] += v
        if new != text:
            if p.suffix == ".json":                       # JSON 护栏: 必须仍可解析
                try:
                    json.loads(new)
                except Exception as e:                    # noqa: BLE001
                    print(f"[SKIP] {p} 清洗后 JSON 不可解析({e}) → 保持原样",
                          file=sys.stderr)
                    continue
            changed_files.append(str(p))
            if apply:
                write_preserving(p, new)
        for lab in iter_judgment_labels(new):
            _, reason = clean_label(lab, cfg, enable_t3=enable_t3)
            if reason.startswith("residual"):
                residuals.append({"file": str(p), "label": lab, "reason": reason})

    nl = {"files_changed": 0, "changed_files": []}
    if normalize_newlines:
        nl = normalize_newlines_tree(root, exts, apply=apply)

    return {
        "root": str(root),
        "files_scanned": len(files),
        "files_changed": len(changed_files),
        "noise_before": before_total,
        "noise_after": after_total,
        "verdicts": dict(agg),
        "residuals": residuals,
        "newline_files_changed": nl["files_changed"],
        "newline_changed_files": nl["changed_files"],
        "applied": bool(apply),
        "changed_files": changed_files,
    }


def _build_canonical_from_source(src_dir: Path) -> list[str]:
    """从源转写稿的 ``发言人X`` 口条抽取人名词典草稿（供人工确认）。"""
    pat = re.compile(r"^\s*发言人([^\s]{0,24}?)\s{2,}\d{1,2}:\d{2}")
    names: Counter = Counter()
    for f in _scan(src_dir):
        try:
            lines = read_preserving(f).splitlines()
        except OSError:
            continue
        for line in lines:
            m = pat.match(line)
            if not m:
                continue
            s, _ = strip_trans_prefix(m.group(1))
            if not s or s.isdigit():
                continue
            names[s] += 1
    return [n for n, _ in names.most_common()]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="[判断:...] 署名规范化（幂等）")
    ap.add_argument("--root", default="wiki", help="扫描根目录（默认 wiki）")
    ap.add_argument("--ext", default=".md", help="扩展名, 逗号分隔 (默认 .md)")
    ap.add_argument("--apply", action="store_true", help="写回（默认 dry-run）")
    ap.add_argument("--no-t3", action="store_true", help="关闭白名单归约（只做 T1/T2）")
    ap.add_argument("--ledger", default="system/state/speaker_norm_ledger.json")
    ap.add_argument("--build-canonical", metavar="SRC_DIR",
                    help="扫描源目录抽取人名词典草稿并打印（不写文件）")
    ap.add_argument("--config", default=None, help="speaker_alias.json 路径")
    ap.add_argument("--normalize-newlines", action="store_true",
                    help="同时把 CRLF 归一为 LF（**默认关闭**：一次会改写数百文件，需显式授权）")
    args = ap.parse_args(argv)

    if args.build_canonical:
        names = _build_canonical_from_source(Path(args.build_canonical))
        print(json.dumps(names, ensure_ascii=False, indent=1))
        print(f"# 草稿 {len(names)} 条 —— 请人工删噪后写入 config/speaker_alias.json",
              file=sys.stderr)
        return 0

    cfg = load_alias_config(args.config)
    root = Path(args.root)
    exts = tuple(e.strip() for e in args.ext.split(",") if e.strip())
    report = normalize_tree(
        root, exts, alias_cfg=cfg, enable_t3=not args.no_t3,
        apply=args.apply, normalize_newlines=args.normalize_newlines,
    )

    led = Path(args.ledger)
    led.parent.mkdir(parents=True, exist_ok=True)
    led.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")

    print(f"扫描 {report['files_scanned']} 文件 | 署名变更 {report['files_changed']} 文件"
          f" | 行尾归一 {report['newline_files_changed']} 文件")
    print(f"噪声 {report['noise_before']} → {report['noise_after']}"
          f" | 残留 {len(report['residuals'])}")
    print(f"判定分布: {report['verdicts']}")
    print(f"台账: {led}  ({'已写回' if args.apply else 'dry-run，未写回'})")
    for r in report["residuals"][:20]:
        print(f"  残留 {r['label']!r} @ {r['file']}")
    return 0 if report["noise_after"] == 0 else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
