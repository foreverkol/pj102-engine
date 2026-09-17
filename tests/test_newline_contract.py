"""行尾契约（newline）回归护栏。

背景（2026-09-16）：全仓 40+ 处 ``Path.write_text`` 未指定 newline，
Windows 文本模式按平台默认把 ``\\n`` 折成 CRLF → 一次补跑把 710 个 wiki
文件的行尾单向拉平，污染文件级审计（逐字校验才发现）。

修复分两层：
  1. 关键写入点补 ``newline="\\n"``（源头确定性）
  2. ``speaker_norm.normalize_newlines_tree`` 在管线出口兜底归一（幂等）

本文件同时锁住两层契约。
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# 兼容两种布局：实例仓 <root>/code · 引擎仓 <root>/src/pj102_engine/code
if not (ROOT / "code").exists() and (ROOT / "src" / "pj102_engine" / "code").exists():
    ROOT = ROOT / "src" / "pj102_engine"
sys.path.insert(0, str(ROOT / "code"))

from speaker_norm import normalize_newlines_tree, normalize_tree  # noqa: E402


# ---------------- 出口归一 ----------------
def test_normalize_newlines_crlf_to_lf(tmp_path):
    p = tmp_path / "a.md"
    p.write_bytes(b"# \xe6\xa0\x87\xe9\xa2\x98\r\n\xe6\xad\xa3\xe6\x96\x87\r\n")
    r = normalize_newlines_tree(tmp_path, (".md",), apply=True)
    assert r["files_changed"] == 1
    assert p.read_bytes() == b"# \xe6\xa0\x87\xe9\xa2\x98\n\xe6\xad\xa3\xe6\x96\x87\n"
    assert b"\r" not in p.read_bytes()


def test_normalize_newlines_is_idempotent(tmp_path):
    p = tmp_path / "a.md"
    p.write_bytes(b"line1\r\nline2\r\n")
    normalize_newlines_tree(tmp_path, (".md",), apply=True)
    first = p.read_bytes()
    r2 = normalize_newlines_tree(tmp_path, (".md",), apply=True)
    assert r2["files_changed"] == 0, "第二次运行仍有变更 → 非幂等"
    assert p.read_bytes() == first


def test_normalize_newlines_does_not_touch_other_bytes(tmp_path):
    """只改 CRLF，不动缩进/末尾无换行/中文等其它字节。"""
    raw = b"no-trailing-newline\r\n  indented\r\n\xe4\xb8\xad\xe6\x96\x87"
    p = tmp_path / "b.md"
    p.write_bytes(raw)
    normalize_newlines_tree(tmp_path, (".md",), apply=True)
    assert p.read_bytes() == raw.replace(b"\r\n", b"\n")
    assert not p.read_bytes().endswith(b"\n")   # 不擅自补末尾换行


def test_normalize_newlines_respects_ext(tmp_path):
    (tmp_path / "a.md").write_bytes(b"x\r\n")
    (tmp_path / "b.json").write_bytes(b"{}\r\n")
    r = normalize_newlines_tree(tmp_path, (".md",), apply=True)
    assert r["files_changed"] == 1
    assert (tmp_path / "b.json").read_bytes() == b"{}\r\n"   # 未列扩展名不动


# ---------------- 联合规范化 ----------------
def test_normalize_tree_combined_and_idempotent(tmp_path):
    cfg = {"alias_map": {}, "canonical_names": ["\u738b\u8001\u5e08"]}
    p = tmp_path / "s.md"
    p.write_bytes(
        "## \u80cc\u666f\r\n[\u5224\u65ad:\u53d1\u8a00\u4eba\u672c\u4eba\u738b\u8001\u5e08]\r\n"
        .encode("utf-8"))
    r1 = normalize_tree(tmp_path, (".md",), alias_cfg=cfg, apply=True,
                        normalize_newlines=True)
    assert r1["noise_before"] == 1 and r1["noise_after"] == 0
    assert r1["newline_files_changed"] == 1
    out = p.read_bytes()
    assert b"\r" not in out and "\u53d1\u8a00\u4eba".encode("utf-8") not in out
    r2 = normalize_tree(tmp_path, (".md",), alias_cfg=cfg, apply=True,
                        normalize_newlines=True)
    assert r2["files_changed"] == 0 and r2["newline_files_changed"] == 0


def test_newline_norm_is_opt_in_by_default(tmp_path):
    """★ 关键契约：行尾归一**默认关闭** —— 它一次会改写数百文件，属批量破坏性变更。

    2026-09-16 校准：wiki 实测 708 CRLF / 17 LF 混合态，自基线快照起从未改变。
    若默认开启，任何一次管线运行都会静默批量改写 —— 必须显式授权。
    """
    p = tmp_path / "a.md"
    p.write_bytes("[\u5224\u65ad:\u53d1\u8a00\u4eba\u738b\u8001\u5e08]\r\n".encode("utf-8"))
    r = normalize_tree(tmp_path, (".md",), alias_cfg={"alias_map": {}, "canonical_names": []},
                       apply=True)          # 未显式开启
    assert r["newline_files_changed"] == 0, "默认竟归一行尾 → 未授权批量改写风险"
    assert b"\r\n" in p.read_bytes()


# ---------------- 源头契约（防未来新增写入点再漏） ----------------
WRITER_FILES = [
    "code/steps/s12_wiki.py",
    "code/steps/s15_summary_page.py",
    "code/index_builder.py",
    "code/polish_pages.py",
    "code/backlink_builder.py",
    "code/concept_merger.py",
    "code/dispute_detector.py",
    "code/scenario_extractor.py",
    "code/file_back.py",
]


def test_wiki_writers_declare_explicit_newline():
    """wiki 正文写入点必须显式 newline='\\n'，不得依赖平台默认折行。"""
    offenders = []
    for rel in WRITER_FILES:
        f = ROOT / rel
        if not f.exists():
            continue
        src = f.read_text(encoding="utf-8")
        for m in re.finditer(r"write_text\(([^;]*?)\)\s*$", src, re.M):
            call = m.group(0)
            if "newline=" in call:
                continue
            offenders.append(f"{rel}: {call.strip()[:90]}")
    assert not offenders, "存在未声明 newline 的 write_text 调用:\n" + "\n".join(offenders)


def test_run_full_normalize_wired():
    """管线必须接线出口归一 —— 否则会后处理链"死于无人调用"。"""
    src = (ROOT / "scripts" / "run_full.py").read_text(encoding="utf-8")
    assert "from speaker_norm import load_alias_config, normalize_tree" in src
    assert 'report["normalize"]' in src
