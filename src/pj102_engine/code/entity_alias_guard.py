"""实体 alias 弱标识护栏（引擎级，内容无关）。

为什么需要
----------
`entity_resolver._find()` 的归并判据是「新实体的任一 alias 命中既有实体的别名表
即归并」。当 `aliases` 里混入**泛化称呼**（`梁总` / `杨总`）、**源稿口条**
（`发言人2`）、**电话号码**（`梁超杰@136 0260 1921`）、**单字姓**（`梁`）等弱标识时，
归并会**级联放大**——吞进一个实体，其 alias 又并入别名表，再命中下一个。

实测（2026-09-16）
------------------
```
person_71add69e_0001  canonical_name = "万联网梁老师"
aliases = [杨老师, 发言人2, 万联网梁老师, 梁超杰, 发言人梁老师, 蒋总,
           梁超杰@136 0260 1921, 梁总, 梁老师, 杨总, 万联网专家顾问梁老师, 小总]
```
该 entity_id 下至少吞并了 **5 个不同的人**（梁超杰 / 蒋总 / 杨总 / 梁老师 / 小总），
其中 `梁超杰` 另有独立实体 `person_3bdbca59_0001` → 同一人被两处认领，
且 `_find()` 返回值**依赖 registry 遍历顺序**（不确定性）。

另一位受害者：`蒋总` 的页面被写成 `canonical_name: 万联网梁老师`，
而它实际是一位「再生资源(铅酸电池)产业互联网平台主理人」——**信息污染**。

护栏原则
--------
弱标识**可以保留在实体页用于展示**，但**不得作为归并依据**。

纪律
----
本模块只做「这个 alias 够不够强」的通用判定，**不含任何实例数据**
（具体人名白名单属于实例侧 `config/`，不得进引擎，否则破坏 codex/hermes 可移植性）。
"""

from __future__ import annotations

import re

# ---- 弱标识规则（任一命中即弱） ----

# 泛化职位称呼：**单字姓氏** + 职位后缀（梁总 / 王老师 / 黄老板 / 张博士 / 李哥）。
# 刻意限定为 1 个汉字：`梁超杰老师`（有完整姓名）可以定位到具体人，不算泛化；
# `王老师`（仅姓氏）无法区分同姓多人，才是弱标识。
# —— 收紧到这里是因为放行 2–3 字会把「梁超杰老师」误判为弱，造成漏合并。
GENERIC_ROLE_RE = re.compile(
    r"^[\u4e00-\u9fa5]"
    r"(总|老师|老板|教授|博士|主任|经理|总监|先生|女士|哥|姐|叔|姨|师傅)$"
)

# 「小/老」+ 名字 = 昵称式泛称（小张总 / 老李总）
NICKNAME_RE = re.compile(r"^[小老][\u4e00-\u9fa5](总|老师|老板|哥|姐)$")

# 源稿口条前缀：发言人2 / 说话人A / 演讲人3 / speaker 1
TRANSCRIPT_RE = re.compile(r"^(发言人|说话人|说话者|演讲人|speaker)", re.IGNORECASE)

# 转写稿自我指称残留：王老师本人 / 本人张总
# （源稿口条 `发言人本人王老师` 被切出的后半段，无法区分具体人）
SELF_REF_RE = re.compile(r"本人")

# 匿名指代：梁某 / 梁某人 / 张某
ANONYM_RE = re.compile(r"^[\u4e00-\u9fa5]{1,3}某(人|总|老师)?$")

# 含数字 / 邮箱 / @ / 长英文串：电话号码、账号、工号
NUMERIC_RE = re.compile(r"[@\d]|[A-Za-z]{4,}")

# 带注解：梁总(未在文中明示) / 王老师（存疑） / 疑似张某
ANNOT_RE = re.compile(r"[（(].*[）)]|未在文中|未明示|存疑|疑似|不确定|待确认")

# 空/占位/纯符号
JUNK_RE = re.compile(r"^(未知|不详|未提取|无|N/?A|null|None|某|待定|-+|_+|\?+|\.+)$", re.IGNORECASE)

# 纯标点或空白
PUNCT_ONLY_RE = re.compile(r"^[\s\W_]+$", re.UNICODE)


def is_weak_alias(alias: str) -> tuple[bool, str]:
    """判定 alias 是否**弱**（不可作为归并依据）。

    返回 `(is_weak, reason)`。reason 供审计台账使用。
    """
    if alias is None:
        return True, "none"
    a = str(alias).strip()
    if not a:
        return True, "empty"
    if PUNCT_ONLY_RE.match(a):
        return True, "punct_only"
    if JUNK_RE.match(a):
        return True, "junk"
    # 单字（`梁` / `王`）—— 中文单字无法区分同姓多人
    if len(a) == 1:
        return True, "single_char"
    if TRANSCRIPT_RE.match(a):
        return True, "transcript_label"
    if SELF_REF_RE.search(a):
        return True, "self_ref"
    if ANONYM_RE.match(a):
        return True, "anonym"
    if NUMERIC_RE.search(a):
        return True, "numeric_or_id"
    if ANNOT_RE.search(a):
        return True, "annotated"
    if GENERIC_ROLE_RE.match(a):
        return True, "generic_role"
    if NICKNAME_RE.match(a):
        return True, "nickname_generic"
    return False, "strong"


def is_junk_entity_name(name: str) -> tuple[bool, str]:
    """判定该名字**根本不该成为实体**（比"弱 alias"更强的一档）。

    与 `is_weak_alias` 的区别（重要）：
      - `is_weak_alias("梁")` = True（不能作为归并依据）——但 **单字姓不在此拦截**，
        因为可能确有其人、只是源稿未给全名；
      - 本函数只拦**机器标签**：源稿口条（`发言人2`）、占位符（`未提取`）、
        纯数字/纯符号 —— 它们不是人，是转写工具的产物。

    实测（2026-09-16）：s6 把 `发言人2`..`发言人8` 直接建成了实体页，
    污染 registry（9 个垃圾 canonical）。
    """
    if name is None:
        return True, "none"
    n = str(name).strip()
    if not n:
        return True, "empty"
    if PUNCT_ONLY_RE.match(n):
        return True, "punct_only"
    if JUNK_RE.match(n):
        return True, "placeholder"
    if TRANSCRIPT_RE.match(n):
        # `发言人2` / `发言人6(深圳科技公司方)` / `说话人A` / `发言人梁老师`
        # 以"发言人/说话人/演讲人"开头的都不是人名（中文无此姓氏），
        # 故不设长度上限。
        return True, "transcript_label"
    if re.fullmatch(r"[\d\s．.、-]+", n):
        return True, "numeric_only"
    return False, "ok"


def strong_aliases(aliases) -> list[str]:
    """过滤出强 alias（可参与归并）。保持原序、去重。"""
    out, seen = [], set()
    for a in aliases or []:
        if not a:
            continue
        if is_weak_alias(a)[0]:
            continue
        a = str(a).strip()
        if a and a not in seen:
            seen.add(a)
            out.append(a)
    return out


def weak_aliases(aliases) -> list[str]:
    """过滤出弱 alias（仅保留展示，不参与归并）。"""
    out, seen = [], set()
    for a in aliases or []:
        if not a:
            continue
        s = str(a).strip()
        if s and is_weak_alias(s)[0] and s not in seen:
            seen.add(s)
            out.append(s)
    return out


def split_aliases(aliases) -> tuple[list[str], list[str]]:
    """返回 `(strong, weak)`。"""
    return strong_aliases(aliases), weak_aliases(aliases)


def colliding_aliases(aliases, canonicals, self_canonical: str = "") -> tuple[list[str], list[str]]:
    """**别名自污染闸**（D-32）：别名若等于**另一实体的 canonical_name**，一律剔除。

    为什么需要
    ----------
    弱标识闸解决的是「泛称不该当归并键」，但**专称跨挂**是另一条污染通路：
    `王义.md` 的 aliases 曾写作 `['王老师', '王一', '王毅']` —— `王老师` 是**另一个
    实体 `person_933a7dbb_0001` 的 canonical_name**。它一旦进入别名表，就会在
    `_find()` 阶段 2 命中，把两个不同的人归成一个 id（T4a 分裂的入口）。
    时间分页族（D-36）同源：`张志强（2023-09-07）` 的 aliases 含
    `张志强（2025-05-29）` —— 两个分页互认对方为别名。

    判据
    ----
    canonical_name 是**实体的专属标识**，具有"指名性"：一个名字若已被某个实体
    正式占为 canonical，它就不可能是**另一个**实体的合法别名。
    （`self_canonical` 用于放行"本实体自己的 canonical 出现在自己别名表"的情形。）

    纪律：纯规则、零实例数据 → 可原样移植到 codex / hermes。
    返回 `(keep, dropped)`，均保序去重。
    """
    blocked = {str(c).strip() for c in (canonicals or []) if c and str(c).strip()}
    selfc = str(self_canonical or "").strip()
    blocked.discard(selfc)

    keep, dropped, seen = [], [], set()
    for a in aliases or []:
        a = str(a).strip() if a else ""
        if not a:
            continue
        if a in blocked:
            if a not in dropped:
                dropped.append(a)
            continue
        if a not in seen:
            seen.add(a)
            keep.append(a)
    return keep, dropped


def alias_quality(aliases) -> dict:
    """给审计脚本用的质量画像。"""
    s, w = split_aliases(aliases)
    detail = {}
    for a in aliases or []:
        if not a:
            continue
        isw, why = is_weak_alias(a)
        if isw:
            detail.setdefault(why, []).append(str(a))
    return {
        "total": len([a for a in (aliases or []) if a]),
        "strong": len(s),
        "weak": len(w),
        "weak_detail": detail,
    }
