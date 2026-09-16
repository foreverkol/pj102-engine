# -*- coding: utf-8 -*-
"""D-52 回归测试：backlink_builder 的**实体名 glob 元字符**修复。

背景
----
`find_wiki_file_for_entity` 原先用 `directory.glob(f"*{entity_name}*.md")`。
glob 模式里 `(` `)` `[` `]` `*` `?` 是元字符：

  `*千问(Qwen)*.md`  → `(Qwen)` 被解析为**字符集**（匹配单个 Q/w/e/n）
                     → 对文件名 `千问(Qwen).md` 永不命中
                     → 该实体页**永远收不到 backlinks**

实测后果（2026-09-16）：`千问(Qwen).md` 单页 backlinks 归零、字节缩水 44.5%；
同类历史 canonical 还有 `难度(原南都)` / `王总(人民王总)` / `用户(文本中未具名,疑姓王)` 等。

本测试锁死修复后的行为：**子串匹配、无元字符风险、目录优先级正确**。
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# 兼容两种布局：实例仓（<root>/code）与引擎仓（<root>/src/pj102_engine/code）
_pkgs = [ROOT / "code"] + sorted((ROOT / "src").glob("*/code"))
for _p in _pkgs:
    if _p.exists() and str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import backlink_builder as BB  # noqa: E402


def _mkwiki(tmp_path: Path):
    (tmp_path / "Entities" / "Persons").mkdir(parents=True)
    (tmp_path / "Entities" / "Organizations").mkdir(parents=True)
    return tmp_path


def test_glob_metachars_paren_are_matched_literally(tmp_path):
    """★ 核心回归：含 `(...)` 的实体名必须能匹配到同名页面。"""
    w = _mkwiki(tmp_path)
    f = w / "Entities" / "Organizations" / "千问(Qwen).md"
    f.write_text("# 千问(Qwen)\n", encoding="utf-8")

    hit = BB.find_wiki_file_for_entity(w, "千问(Qwen)", "organization")
    assert hit is not None, "含括号的实体名不能再被 glob 元字符吞掉"
    assert hit.name == "千问(Qwen).md"


def test_glob_metachars_various(tmp_path):
    """其它元字符同样不得参与模式解释：`()` `[]` 一律按字面。

    ⚠ Windows 文件名禁用 `< > : " / \\ | ? *`，故本测试**不能**使用 `A*B` / `C?D`
    （会直接 `OSError: [Errno 22] Invalid argument`，与待测逻辑无关）。
    这里只取 Windows 合法但 glob 有语义的字符：`(` `)` `[` `]` `+` `{` `}`。
    """
    w = _mkwiki(tmp_path)
    names = ["难度(原南都)", "王总(人民王总)", "用户[未具名]", "数据[2023]年度", "A+B(C)"]
    for n in names:
        (w / "Entities" / "Organizations" / f"{n}.md").write_text("# x\n", encoding="utf-8")
    for n in names:
        hit = BB.find_wiki_file_for_entity(w, n, "organization")
        assert hit is not None, f"{n} 未命中"
        assert hit.stem == n


def test_substring_semantics_preserved(tmp_path):
    """子串语义不变：`得到 APP` 应命中 `得到 APP.md`；`得到APP` 命中不到带空格的页名。"""
    w = _mkwiki(tmp_path)
    (w / "Entities" / "Organizations" / "得到 APP.md").write_text("# 得到 APP\n", encoding="utf-8")
    assert BB.find_wiki_file_for_entity(w, "得到 APP", "organization") is not None
    assert BB.find_wiki_file_for_entity(w, "得到APP", "organization") is None


def test_directory_priority_person_before_org(tmp_path):
    """entity_type 为 None 时先查 Persons 再查 Organizations（保持原优先级）。"""
    w = _mkwiki(tmp_path)
    (w / "Entities" / "Persons" / "同名.md").write_text("# p\n", encoding="utf-8")
    (w / "Entities" / "Organizations" / "同名.md").write_text("# o\n", encoding="utf-8")
    hit = BB.find_wiki_file_for_entity(w, "同名", None)
    assert hit.parent.name == "Persons"


def test_type_scoped_lookup(tmp_path):
    """指定 entity_type 时不应跨目录命中。"""
    w = _mkwiki(tmp_path)
    (w / "Entities" / "Persons" / "张三.md").write_text("# p\n", encoding="utf-8")
    assert BB.find_wiki_file_for_entity(w, "张三", "organization") is None
    assert BB.find_wiki_file_for_entity(w, "张三", "person") is not None


def test_missing_dir_returns_none(tmp_path):
    """目录不存在时安全返回 None（不抛异常）。"""
    assert BB.find_wiki_file_for_entity(tmp_path, "任意", "organization") is None


def test_no_glob_pattern_construction_in_source():
    """源码不得再把实体名拼进 glob 模式（护栏）。"""
    src = Path(BB.__file__).read_text(encoding="utf-8")
    assert 'glob(f"*{entity_name}*.md")' not in src, "禁止把实体名直接拼进 glob 模式"
    assert 'glob(f"*{name}*.md")' not in src


# --------------------------------------------------------------------------
# D-52 归属修复：一个文件只能归属**一个**实体
# --------------------------------------------------------------------------

def test_exact_match_beats_substring_claim(tmp_path):
    """★ 核心回归：`阿里千问办公` 的页不得被 `阿里` / `千问` 抢走。

    实测（2026-09-16）`Entities/Organizations/阿里千问办公.md` 同时被子串命中
    `阿里`、`千问`、`阿里千问办公` 三个实体，页的 backlinks 由**最后写入者**决定
    ⇒ 挂成 `阿里` 的引用（错对象），且每次运行都重写（幂等性丧失）。
    """
    w = _mkwiki(tmp_path)
    (w / "Entities" / "Organizations" / "阿里千问办公.md").write_text("# x\n", encoding="utf-8")
    types = {"阿里": "organization", "千问": "organization", "阿里千问办公": "organization"}

    m = BB.build_entity_file_map(w, types)
    assert [f.stem for f in m.get("阿里千问办公", [])] == ["阿里千问办公"]
    assert not m.get("阿里"), "`阿里` 不得抢走 `阿里千问办公.md`"
    assert not m.get("千问"), "`千问` 不得抢走 `阿里千问办公.md`"


def test_ownership_is_disjoint(tmp_path):
    """不变式：任何页最多归属一个实体（这是幂等的前提）。"""
    w = _mkwiki(tmp_path)
    orgs = w / "Entities" / "Organizations"
    for n in ["平安", "平安银行", "平安商贸", "平安一账通", "海航", "海航合资公司"]:
        (orgs / f"{n}.md").write_text("# x\n", encoding="utf-8")
    types = {n: "organization" for n in
             ["平安", "平安银行", "平安商贸", "平安一账通", "海航", "海航合资公司"]}

    m = BB.build_entity_file_map(w, types)
    seen = {}
    for name, files in m.items():
        for f in files:
            assert f not in seen, f"{f.name} 同时归属 {seen[f]} 与 {name}"
            seen[f] = name
    assert seen.get(orgs / "平安银行.md") == "平安银行"
    assert seen.get(orgs / "海航合资公司.md") == "海航合资公司"


def test_t2_family_claimed_whole(tmp_path):
    """T2 时间分页族由**其所有者**整族收下，不被短名实体抢走。"""
    w = _mkwiki(tmp_path)
    p = w / "Entities" / "Persons"
    for n in ["张志强（2023-09-07）", "张志强（2025-05-29）"]:
        (p / f"{n}.md").write_text("# x\n", encoding="utf-8")
    types = {"张志强": "person", "张": "person"}

    m = BB.build_entity_file_map(w, types)
    assert len(m.get("张志强", [])) == 2, "T2 分页族两页应整族归属 `张志强`"


def test_find_all_no_loose_fallback_when_exact_exists(tmp_path):
    """`find_all_wiki_files_for_entity` 命中精确页后**不得**回落到子串族。"""
    w = _mkwiki(tmp_path)
    orgs = w / "Entities" / "Organizations"
    (orgs / "平安.md").write_text("# x\n", encoding="utf-8")
    (orgs / "平安银行.md").write_text("# x\n", encoding="utf-8")
    got = BB.find_all_wiki_files_for_entity(w, "平安", "organization")
    assert [f.stem for f in got] == ["平安"], "精确同名页命中后不应连带吞下 `平安银行.md`"


def test_loose_fallback_picks_shortest(tmp_path):
    """无精确页时的子串兜底：取**最短**候选（最贴近实体名），而非目录序首个。"""
    w = _mkwiki(tmp_path)
    orgs = w / "Entities" / "Organizations"
    (orgs / "阿里千问办公.md").write_text("# x\n", encoding="utf-8")
    (orgs / "阿里云.md").write_text("# x\n", encoding="utf-8")
    got = BB.find_all_wiki_files_for_entity(w, "阿里", "organization")
    assert len(got) == 1, "子串兜底只取一页，不得整族吞并"
    assert got[0].stem == "阿里云"

