"""
S1: 基础信息提取（规则处理，无需 LLM）
"""
import json
import re
from pathlib import Path

_OVERRIDE_CACHE = None


def _date_overrides() -> dict:
    """装载 config/date_authority.json（日期权威覆盖表；部署侧可选数据文件）。

    路径解析用 Path(__file__).resolve().parents[N]，同时兼容部署仓与 src layout。
    """
    global _OVERRIDE_CACHE
    if _OVERRIDE_CACHE is not None:
        return _OVERRIDE_CACHE
    here = Path(__file__).resolve()
    data = {}
    for n in (2, 3, 4):
        try:
            cand = here.parents[n] / "config" / "date_authority.json"
        except IndexError:
            break
        if cand.is_file():
            try:
                data = json.loads(cand.read_text(encoding="utf-8")).get("overrides", {}) or {}
            except (OSError, ValueError):
                data = {}
            break
    _OVERRIDE_CACHE = data
    return data


def s1_basic_info(filename: str, content: str) -> dict:
    """从文件名 + 内容提取基础信息"""
    info = {
        "title": _extract_title(filename),
        "date": _extract_date(filename, content),
        "filename": filename,
        "size_bytes": len(content),
        "char_count": len(content),
        "line_count": content.count("\n") + 1,
    }

    # 提取录音时间
    time_match = re.search(r"录音交流开始时间[:：](\S+ \S+)", content)
    if time_match:
        info["recording_time"] = time_match.group(1)

    # 估计时长
    info["duration_estimate"] = f"约{max(1, info['char_count'] // 250)}分钟"

    return info


def _extract_title(filename: str) -> str:
    # P4 T-P4.8 根因修复: 支持 "-" 分隔符变体 (如 20260902_2109-标题.md),
    # 剥离残留前导分隔符与 .md 后缀, 避免产出 "-标题.md" 畸形页名
    name = re.sub(r"^202\d{5,6}[_\s-]?\d*", "", filename)
    name = name.replace("_原文.md", "").replace("_原文", "")
    name = re.sub(r"\.md$", "", name)
    name = name.replace("_", " ")
    return name.lstrip("-_—- ").strip()


def _extract_date(filename: str, content: str = "") -> str:
    """日期权威判据（D-57 / D-60 交叉验证）。

    背景：源稿**文件名的年月日可能笔误**（D-57：两份 `20250529_*` 的文件头与
    内部标题均声明 2026-05-29，且其孪生副本 `20260529_095729_*` sha256 完全相同）；
    但**文件头也可能被污染**（D-60：`20260729_082946_*` 头部写 08-01 09:42，
    与其内部标题 `20260729_082946` 自相矛盾）。

    因此单一证据源都不可信，改为**分层判据**：
      ⓪ 命中 config/date_authority.json 覆盖表 → 直接采信（人工裁决落点，如 D-57 第二会议）；
      ① 头部「录音交流开始时间」的**年月日** 与 正文内部标题时间戳的**年月日** 一致
         → 采信该日期（可纠正文件名笔误，如 D-57 第一会议）；
      ② 两者不一致或缺失 → 回退文件名（保持历史行为，零回归，如 D-60）；
      ③ 判据只用**年月日**，不比时分 —— 时分在 D-57 中也不一致（09:41 vs 09:57），
         若比时分会导致 D-57 判据失效。
    """
    ov = _date_overrides().get(filename, {}).get("date")
    if ov:
        return ov

    m = re.search(r"(202\d)(\d{2})(\d{2})", filename)
    fname_date = f"{m.group(1)}-{m.group(2)}-{m.group(3)}" if m else "unknown"
    if not content:
        return fname_date

    head = re.search(r"录音交流开始时间[:：]\s*(20\d{2})年(\d{2})月(\d{2})日", content)
    # 内部标题形如：录音交流沟通事件标题：20260529_095729机场接…
    inner = re.search(r"录音交流沟通事件标题[:：]\s*[^\n]{0,40}?(20\d{2})(\d{2})(\d{2})", content)
    if not inner:  # 回退：取正文前 600 字中首个「8位日期+时间戳」形态
        inner = re.search(r"(20\d{2})(\d{2})(\d{2})[_\s]?\d{4,6}", content[:600])
    if head and inner:
        head_date = f"{head.group(1)}-{head.group(2)}-{head.group(3)}"
        inner_date = f"{inner.group(1)}-{inner.group(2)}-{inner.group(3)}"
        if head_date == inner_date:
            return head_date
    return fname_date