"""
S1: 基础信息提取（规则处理，无需 LLM）
"""
import re


def s1_basic_info(filename: str, content: str) -> dict:
    """从文件名 + 内容提取基础信息"""
    info = {
        "title": _extract_title(filename),
        "date": _extract_date(filename),
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


def _extract_date(filename: str) -> str:
    m = re.search(r"(202\d)(\d{2})(\d{2})", filename)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    return "unknown"