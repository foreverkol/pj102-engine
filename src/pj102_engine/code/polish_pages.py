# -*- coding: utf-8 -*-
"""polish_pages: s12 hash 分片页增量收尾 (W3-T3.2)

角色 1 (存量清理): 清零历史遗留的 *_{hash8}.md 分片页
角色 2 (运行时收尾): run_full 补调 s12 后, 新分片页自动规范化
    - 接线于 run_post_processing 链 concept_merger 之前

处理规则:
  A. 冗余删除: 同 name + 同 source_hash 的规范页已存在 → 分片页是复写,
     转移全库入链后直接删除
  B. 新页收尾: 无对应规范页 →
     - Entities/Persons|Organizations: 命名 {name}（{date}）.md (冲突加（2）)
     - Knowledge/Concepts|Scenarios:   命名 {name}.md (冲突加（2）)
     - 正文实体链接 + 同源互链 + Persons/Organizations 主页 callout
     - 旧 rel 链接全库替换 (index.md 及所有引用页)
  C. v1.4 (F-4, 2026-09-15 D-d): merge_mode 并入规范主页时回并既有 H2 结构
     (_merge_appended), 不再原样带回 H1+骨架 H2 — 修复 23 页重复同名小节;
     存量由 scripts/fix_dup_h2_20260915.py 一次性收口。

幂等: 重复运行零操作。CLI: python code/polish_pages.py [--dry-run] [--wiki PATH]
"""
import re
import sys
import json as _json
import argparse
from pathlib import Path
from typing import Dict, List, Tuple

HASH_RE = re.compile(r"_[0-9a-f]{8,12}(_\d+)?$")   # T1 修复: 兼容 12 位 content_hash 与 hash_N 序号型分片页

# 实体链接的最小名字长度 (防误链短词)
_MIN_LEN = {"person": 3, "org": 4, "concept": 4, "scenario": 5}


# ---- v1.4 (F-4, 2026-09-15 D-d): 回并既有 H2 结构 ----
# 旧实现 add 原样带回被并入页的 H1 + 全套骨架 H2, 多次并入同一规范主页后
# 出现重复同名 H2 (实例实测 23 页: 王老师 5 组×4-6 份骨架)。
# 现改为: 剥离 H1; 骨架小节并入目标页同名 H2 末尾 (计数后缀 (N)/(N 次出现)
# 归一化匹配); 无同名小节才降级为 H3 挂在 "### {date} 补充出现" 标记下。

def _h2_norm(title: str) -> str:
    """H2 标题归一化: 剥离尾部计数后缀 (## 📅 出现会议 (11) ≡ ## 📅 出现会议)"""
    return re.sub(r"\s*\(\d+(?:\s*次出现)?\)$", "", title.strip())


def _split_h2(text: str) -> Tuple[str, List[Tuple[str, str]]]:
    """正文按 H2 切分 → (preamble, [(title, body), ...])。

    注: 与本项目其他就地编辑工具同假设 —— 页面正文 code fence 内
    不出现行首 '## ' 形态 (LLM 生成的结构页满足此约定)。
    """
    parts = re.split(r"(?m)^(?=## (?!#))", text)
    out = []
    for seg in parts[1:]:
        lines = seg.split("\n", 1)
        out.append((lines[0].strip(), lines[1] if len(lines) > 1 else ""))
    return parts[0], out


def _join_h2(pre: str, secs: List[Tuple[str, str]]) -> str:
    out = pre.rstrip() + "\n\n" if pre.strip() else ""
    for t, b in secs:
        out += f"{t}\n{b.rstrip()}\n\n"
    return out.rstrip() + "\n"


def _merge_appended(ct: str, main: str, sec_text: str, mark: str) -> str:
    """把被并入页正文 (main) 与关联网络小节 (sec_text) 回并进目标页正文 ct。

    同名 H2 (归一化匹配) → 追加到该小节末尾;
    无名可回并的残留 → 降级为 H3, 挂在 mark 标记之后 (页面尾)。
    幂等: 由调用方 _mark 守卫保证 (同 source_meeting 只并入一次)。
    """
    stripped = re.sub(r"(?m)^# (?!#)[^\n]*$", "", main.rstrip())  # 剥离 H1 行
    pre, secs = _split_h2(stripped)
    _, sec_secs = _split_h2(sec_text)
    secs = secs + sec_secs

    m = re.match(r"^((?:>.*\n|\n)*)---\r?\n.*?\r?\n---\r?\n", ct, re.S)
    head = ct[:m.end()] if m else ""
    tail = ct[m.end():] if m else ct
    tpre, tsecs = _split_h2(tail)

    leftover = []
    if pre.strip():
        leftover.append(pre.strip())
    for title, body in secs:
        if not title.strip() or not body.strip():
            continue
        tgt = next((i for i, (t, _) in enumerate(tsecs)
                    if _h2_norm(t) == _h2_norm(title)), None)
        if tgt is not None:
            t, tb = tsecs[tgt]
            tsecs[tgt] = (t, tb.rstrip() + "\n\n" + body.strip() + "\n")
        else:
            leftover.append(f"### {title.lstrip('#').strip()}\n\n{body.strip()}")

    if leftover:
        block = "\n\n" + mark + "\n\n" + "\n\n".join(leftover) + "\n"
        return head + _join_h2(tpre, tsecs).rstrip() + "\n" + block
    return head + _join_h2(tpre, tsecs)



def _sanitize(name: str) -> str:
    for a, b in [("\\", "／"), ("/", "·"), (":", "："), ("*", "×"), ("?", "？"),
                 ('"', ""), ("<", "〈"), (">", "〉"), ("|", "｜"),
                 ("[", "（"), ("]", "）"), ("#", ""), ("^", "")]:
        name = name.replace(a, b)
    return name.strip().rstrip(". ").strip()


def split_fm(txt: str) -> Tuple[str, str]:
    """拆 frontmatter; 容忍开头 callout 行 (> 开头) 及其后的空行"""
    m = re.match(r"^((?:>.*\n|\n)*)---\r?\n(.*?)\r?\n---\r?\n", txt, re.S)
    if m:
        return m.group(2), txt[m.end():]
    return "", txt


def fm_get(fm: str, key: str) -> str:
    m = re.search(rf"^{key}:\s*(.*)$", fm, re.M)
    if not m:
        return ""
    return m.group(1).strip().strip('"').strip("'")


# ---- v1.6 (D-75, 2026-09-17): 分片页丢弃必须过「内容承接」门 ----
# 现场事故: E1 批次 13:34 的收尾中, 210 个分片页里有 20 份的**实质内容**
# 未被任何规范页承接即被 unlink, 只留下会议页里的实体描述行 (实体页层缺失)。
# 三条无校验丢弃路径:
#   ① `(type, hash)` 兜底键跨实体错配 (name 不同却命中同类型首个页) → 错删
#   ② 分支 A 冗余删除只认键、不认内容 → 同名不同源(同实体不同次出现)被当复写
#   ③ SKIP-DUP 幂等守卫以「source_meeting 字面已出现」为判据 → 同源重跑的
#      更新内容整份丢弃
# 现统一为一条不变式: **分片页只有在其实质内容已被目标页承接时才可丢弃**;
# 未承接 ⇒ 强制并入目标页 (而非新建 (2) 副本), 保证只增不减。

def _norm_line(s: str) -> str:
    s = re.sub(r"\[\[([^\]|]+)\|([^\]]+)\]\]", r"\2", s)
    s = re.sub(r"\[\[([^\]]+)\]\]", r"\1", s)
    return s.replace("**", "")


def _body_lines(txt: str, cut_sections: bool = True) -> List[str]:
    """正文行集合。cut_sections=True 时裁掉『元信息』『关联网络』段。

    ⚠ 该裁切只可用于**分片侧**。若对**目标页**也裁切, 则被并入的
    `### {date} 补充出现` 块 (位于『关联网络』**之后**) 会被误判为不存在
    ⇒ `_contained` 永远 False ⇒ 每次重跑重复并入, 幂等被破坏 (D-75 附带修正)。
    """
    _, body = split_fm(txt)
    if cut_sections:
        for cut in ("## 📑 元信息", "## 🔗 关联网络"):
            i = body.find(cut)
            if i >= 0:
                body = body[:i]
    out: List[str] = []
    for ln in body.split("\n"):
        s = _norm_line(ln.strip())
        if not s or s.startswith("#"):
            continue
        if s not in out:
            out.append(s)
    return out


def _subst_lines(txt: str) -> List[str]:
    """分片侧实质内容行 (裁节 + 去链接/粗体修饰)。"""
    return _body_lines(txt, True)


def _contained(shard_text: str, target_text: str) -> Tuple[bool, List[str]]:
    """分片实质内容是否全部被目标页承接 → (bool, 未承接行)。

    目标侧用**全文行集**(不裁节), 否则「已并入但在关联网络之后」的内容会被误判。
    """
    tl = set(_body_lines(target_text, False))
    missing = [x for x in _body_lines(shard_text, True) if x not in tl]
    return (not missing), missing


def _parse_page(p: Path) -> dict:
    txt = p.read_text(encoding="utf-8")
    fm, body = split_fm(txt)
    callout = ""
    m = re.match(r"^((?:>[^\n]*\n)+)", txt)
    if m:
        callout = m.group(1)
    return {
        "path": p, "text": txt, "fm": fm, "body": body, "callout": callout,
        "name": fm_get(fm, "name"),
        "source_hash": fm_get(fm, "source_hash") or fm_get(fm, "source_ref_hash"),
        "date": fm_get(fm, "date"),
        "type": fm_get(fm, "type"),
        "source_meeting": fm_get(fm, "source_meeting"),
        "source_ref": fm_get(fm, "source_ref"),
    }


def polish_pages(wiki_root, dry_run: bool = False) -> dict:
    W = Path(wiki_root)
    report = {"scanned": 0, "redundant_deleted": 0, "renamed": 0,
              "links_fixed": 0, "entity_merged": 0, "details": []}

    # ---- 1. 全库索引 ----
    all_pages = {}          # rel_path(无 .md 后缀, 与 wikilink 一致) -> parsed
    norm_keys = {}          # (name, source_hash) -> rel (非分片页)
    norm_scen = {}          # (theme, source_ref) -> rel (场景页专用冗余键)
    hash_idx = {}           # (type, hash) -> rel (非分片页, T1 兜底冗余键: judgment/meeting 无 name 字段)
    for p in sorted(W.rglob("*.md")):
        if ".obsidian" in p.parts or p.name in ("index.md", "log.md",
                                                 "log.legacy.v4.md"):
            continue
        rel = p.relative_to(W).as_posix()[:-3]     # 去 .md, 对齐 wikilink 形态
        info = _parse_page(p)
        info["rel"] = rel
        all_pages[rel] = info
        if not HASH_RE.search(p.stem) and info["source_hash"] and info["name"]:
            norm_keys.setdefault((info["name"], info["source_hash"]), rel)
        # T1: 非分片页的 (type, hash) 索引 — hash 取 source_hash/content_hash/file_hash 三字段兜底
        if not HASH_RE.search(p.stem) and info["type"]:
            for _hk in (info["source_hash"],
                        fm_get(info["fm"], "content_hash"),
                        fm_get(info["fm"], "file_hash")):
                if _hk:
                    hash_idx.setdefault((info["type"], _hk), rel)
        theme = fm_get(info["fm"], "theme")
        if (not HASH_RE.search(p.stem) and theme and info["source_ref"]):
            norm_scen.setdefault((theme, info["source_ref"]), rel)

    # 实体名索引 (用于链接化)
    ent_idx = {}
    for rel, info in all_pages.items():
        if info["type"] in ("person", "organization", "concept") and info["name"]:
            minlen = _MIN_LEN.get({"person": "person",
                                   "organization": "org"}.get(info["type"], "concept"), 3)
            if len(info["name"]) >= minlen:
                ent_idx.setdefault(info["name"], rel)
    sorted_names = sorted(ent_idx, key=len, reverse=True)

    # 会议索引: source_meeting -> Meetings 页
    meeting_idx = {}
    for rel, info in all_pages.items():
        if rel.startswith("Meetings/") and info["source_meeting"]:
            meeting_idx.setdefault(info["source_meeting"], rel)

    # ---- 2. 分片页处理 ----
    shards = [info for rel, info in all_pages.items()
              if HASH_RE.search(info["path"].stem)]
    report["scanned"] = len(shards)

    renames = {}    # old_rel -> new_rel
    for sh in shards:
        rel = sh["rel"]
        # A. 冗余判定: 实体/概念页 (name+source_hash) 或 场景页 (theme+source_ref)
        #    T1 兜底: judgment/meeting 无 name → 按 (type, hash) 判定同类型正页存在即冗余
        #    v1.6 (D-75): 兜底键加 name 守卫; 且「丢弃」前必须过内容承接门
        key = (sh["name"], sh["source_hash"])
        scen_key = (fm_get(sh["fm"], "theme"), sh["source_ref"])
        sh_hash = sh["source_hash"] or fm_get(sh["fm"], "content_hash") \
            or fm_get(sh["fm"], "file_hash")
        target = norm_keys.get(key) or norm_scen.get(scen_key)
        if target is None:
            _fb = hash_idx.get((sh["type"], sh_hash))
            # D-75: 该兜底仅为「无 name 的 judgment/meeting」设计。有 name 的分片
            #   若命中同类型但他名的正页, 属跨实体错配 ⇒ 禁用 (否则静默错删)。
            if _fb and sh["name"]:
                _tn = all_pages.get(_fb, {}).get("name", "")
                if _tn and _tn != sh["name"]:
                    _fb = None
            target = _fb
        if target:
            _tp = W / (target + ".md")
            _tt = _tp.read_text(encoding="utf-8") if _tp.exists() else ""
            _okc, _miss = _contained(sh["text"], _tt)
            if _okc:
                if not dry_run:
                    sh["path"].unlink()
                report["redundant_deleted"] += 1
                report["details"].append(f"DEL  {rel}  ≡ {target}")
                renames[rel] = target          # 入链转移目标
                continue
            # v1.6 (D-75): 键命中但内容未被承接 (同实体的另一次出现: 描述/引用/出现会议)
            #   ⇒ 强制并入目标页, 不新建「（2）」副本 —— 分片页只增不减。
            if not dry_run:
                _b = sh["body"]
                _mp = _b.find("\n## 📑 元信息")
                _main = _b[:_mp] if _mp >= 0 else _b
                _ct = _merge_appended(
                    _tt, _main, "",
                    mark=f"### {sh['date'] or sh['path'].stem} 补充出现")
                _tp.write_text(_ct, encoding="utf-8", newline="\n")
                sh["path"].unlink()
            report["entity_merged"] += 1
            report["details"].append(
                f"MERGE {rel} -> {target}  (键冗余但内容未承接 ⇒ 强制并入)")
            renames[rel] = target
            continue

        # B. 新页收尾: 计算规范名
        sub_dir = sh["path"].parent.relative_to(W).as_posix()
        raw = HASH_RE.sub("", sh["path"].stem)
        raw = re.sub(r"^(person|org|concept|scenario|meeting|judgment)_", "", raw)
        # T1: judgment/meeting 无 name → 优先 title (截断 50 字) 兜底, 避免垃圾名
        _ttl = fm_get(sh["fm"], "title")
        base = _sanitize(sh["name"]) \
            or (_sanitize(_ttl[:50]) if _ttl else "") \
            or _sanitize(raw) or "未命名"
        # v1.5 (D-61-a, 2026-09-16): 会议页补日期前缀 —— 对齐 KB 既有约定。
        #   分片源名本就带日期(`meeting_{date}_{hash}`), 且既有 16/22 会议页为
        #   `{date} {title}`, 摘要页亦为 `摘要_{date}_{title}`。
        #   缺日期前缀会使 Obsidian 文件列表失去时序排序, 且同日会议无法区分。
        if sub_dir.endswith("Meetings") and sh["date"] \
                and not base.startswith(sh["date"]):
            base = f"{sh['date']} {base}"
        # v1.3 (P2 T-P2.2): 实体页不再拼日期 → 一人一页约定;
        # 同名规范主页已存在 → 并入其时间线 (merge_mode), 不新建分片页
        is_ent = sub_dir.endswith(("Persons", "Organizations"))
        canon_rel = f"{sub_dir}/{base}"
        merge_mode = is_ent and (
            canon_rel in renames.values()
            or (canon_rel in all_pages
                and not HASH_RE.search(Path(canon_rel).stem)))
        if merge_mode and canon_rel not in all_pages:
            canon_rel = next(r for r in renames.values() if r == canon_rel)
        used = {r for r in all_pages} | set(renames.values())
        new_stem, i = base, 2
        while f"{sub_dir}/{new_stem}" in used:
            new_stem = f"{base}（{i}）"
            i += 1
        new_rel = canon_rel if merge_mode else f"{sub_dir}/{new_stem}"

        # 正文处理: 实体链接 (跳过 frontmatter/元信息小节)
        body = sh["body"]
        meta_pos = body.find("\n## 📑 元信息")
        main, meta = (body[:meta_pos], body[meta_pos:]) if meta_pos >= 0 \
            else (body, "")
        n_ent = 0
        spans = []
        for name in sorted_names:
            if name == sh["name"]:
                continue
            pos = main.find(name)
            while pos >= 0:
                if not any(s <= pos < e or s < pos + len(name) <= e
                           for s, e, _ in spans):
                    if main[max(0, pos - 2):pos + len(name) + 2].find("[[") < 0:
                        spans.append((pos, pos + len(name), name))
                        n_ent += 1
                    break
                pos = main.find(name, pos + 1)
        for s, e, name in sorted(spans, reverse=True):
            main = main[:s] + f"[[{ent_idx[name]}|{name}]]" + main[e:]

        # 来源会议链接 + 同源互链
        sec = ["\n## 🔗 关联网络\n"]
        mrel = meeting_idx.get(sh["source_meeting"] or "")
        if mrel:
            sec.append(f"- **来源会议**: [[{mrel}]]\n")
        # v1.5 (D-61-b, 2026-09-16): 「同源页面」判据必须要求 source_hash **非空**。
        #   实测：会议页 frontmatter 无 source_hash 字段 ⇒ 20 个会议分片全部取到
        #   None，而 `None == None` 恒真 ⇒ 每页把它们**误判为同一次沟通的产出**
        #   （且因 renames 随循环增长而顺序相关、非对称），凭空产生 190 条虚假双链。
        peers = [r for r in renames
                 if r != rel and sh["source_hash"]           # ← D-61-b: 必须非空
                 and all_pages.get(r, {}).get("source_hash") == sh["source_hash"]
                 and renames[r] != new_rel]
        if peers:
            sec.append("- **同源页面**（同一次沟通中产出）:\n")
            for pr in peers:
                sec.append(f"  - [[{renames[pr]}]]\n")

        # v1.3 (P2 T-P2.2): 并入既有规范主页 (时间线聚合, 防实体分片复发)
        if merge_mode:
            _sm = sh["source_meeting"]
            _mark = str(_sm) if _sm else f"### {sh['date']} 补充出现"
            if not dry_run:
                cp = W / (new_rel + ".md")
                ct = cp.read_text(encoding="utf-8")
                # 幂等守卫: 同一 source_meeting 已并入过则跳过 (防沙箱重试双写)
                # v1.6 (D-75): 守卫必须叠加「内容已承接」校验 —— 同源**重跑**产出的
                #   更新内容会因字面已出现而被整份丢弃 (只增不减被破坏)。
                _dup_ok = bool(_mark) and _mark in ct
                if _dup_ok and not _contained(sh["text"], ct)[0]:
                    _dup_ok = False
                if _dup_ok:
                    sh["path"].unlink()
                    report["details"].append(f"SKIP-DUP {rel} -> {new_rel} (已并入)")
                else:
                    if _sm and str(_sm) not in ct:
                        _smq = _json.dumps(str(_sm), ensure_ascii=False)
                        if "\nsource_meetings:" in ct:
                            ct = ct.replace("\nsource_meetings:",
                                            f"\nsource_meetings:\n  - {_smq}", 1)
                        else:
                            ct = re.sub(r"\n---\n",
                                        f"\nsource_meetings:\n  - {_smq}\n---\n",
                                        ct, count=1)
                    # v1.4 (F-4, D-d): 回并既有 H2 结构 — 不再原样带回
                    # 被并入页的 H1+骨架 H2, 防重复同名小节 (详见 _merge_appended)
                    ct = _merge_appended(
                        ct, main, "".join(sec),
                        mark=f"### {sh['date'] or sh['path'].stem} 补充出现")
                    cp.write_text(ct, encoding="utf-8", newline="\n")
                    sh["path"].unlink()
            report["entity_merged"] += 1
            report["links_fixed"] += n_ent
            report["details"].append(f"MERGE {rel} -> {new_rel}")
            renames[rel] = new_rel
            continue

        # Persons/Organizations 主页 callout (同 name 更早日期的页面)
        callout = ""
        if sub_dir.endswith(("Persons", "Organizations")) and sh["name"]:
            earlier = [r for r, inf in all_pages.items()
                       if inf["name"] == sh["name"] and inf["date"]
                       and sh["date"] and inf["date"] < sh["date"]
                       and not HASH_RE.search(Path(r).stem)]
            if earlier:
                main_page = sorted(earlier)[0]
                callout = (f"> [!info] 同一实体的另一次出现（{sh['date']}），"
                           f"完整时间线见主页 [[{main_page}|{Path(main_page).stem}]]\n\n")

        out_txt = (f"---\n{sh['fm']}\n---\n\n{callout}"
                   + main.rstrip() + "\n" + meta.rstrip() + "\n"
                   + "".join(sec))
        if not dry_run:
            (W / (new_rel + ".md")).write_text(out_txt, encoding="utf-8", newline="\n")
            sh["path"].unlink()
        report["renamed"] += 1
        report["links_fixed"] += n_ent
        report["details"].append(f"MOVE {rel}  ->  {new_rel}  (+{n_ent} 链接)")
        renames[rel] = new_rel

    # ---- 3. 全库旧链接替换 (含 index.md) ----
    if renames and not dry_run:
        for rel, info in list(all_pages.items()):
            if rel in renames:      # 已删的跳过
                continue
            txt = info["text"]
            changed = False
            for old, new in renames.items():
                old_disp = old.split("/")[-1]
                new_disp = new.split("/")[-1]
                if f"[[{old}" in txt or f"|{old_disp}]]" in txt:
                    txt = txt.replace(f"[[{old}", f"[[{new}").replace(
                        f"|{old_disp}]]", f"|{new_disp}]]")
                    changed = True
            if changed:
                info["path"].write_text(txt, encoding="utf-8", newline="\n")
                report["links_fixed"] += 1
        # index.md (不在 all_pages 中, 单独处理)
        ip = W / "index.md"
        if ip.exists():
            it = ip.read_text(encoding="utf-8")
            orig = it
            for old, new in renames.items():
                old_disp = old.split("/")[-1]
                new_disp = new.split("/")[-1]
                it = it.replace(old, new).replace(
                    f"|{old_disp}]]", f"|{new_disp}]]")
            if it != orig:
                ip.write_text(it, encoding="utf-8", newline="\n")

    # ---- 4. 幻觉死链重定向 (T5 新增, v2) ----
    # LLM 生成字段值时可能输出 [[路径_hash8-12|显示名]] 形态链接, 指向从未
    # 存在的 hash 页面 → 死链. 关键: 独立扫盘 + 重建实体索引(含 B 规则
    # rename 后的新 rel), 不依赖 all_pages/renames 旧状态(被 rename 的页
    # 不在 all_pages, 旧 ent_idx 可能指向已删路径).
    report["halluc_links_fixed"] = 0
    if not dry_run:
        _HALT_RE = re.compile(
            r"\[\[([^\]|#]+?)_[0-9a-f]{8,12}(?:_\d+)?\|([^\]]+)\]\]")
        _HALT_PLAIN_RE = re.compile(
            r"\[\[([^\]|#]+?)_[0-9a-f]{8,12}(?:_\d+)?\]\]")

        # 重建当前盘面实体索引 (name -> rename 后规范 rel)
        fresh_ent = {}
        for fp in sorted(W.rglob("*.md")):
            if ".obsidian" in fp.parts or fp.name in (
                    "index.md", "log.md", "log.legacy.v4.md"):
                continue
            _pi = _parse_page(fp)
            if _pi["type"] in ("person", "organization", "concept")                     and _pi["name"]:
                minlen = _MIN_LEN.get({"person": "person", "organization": "org"}
                                      .get(_pi["type"], "concept"), 3)
                if len(_pi["name"]) >= minlen:
                    fresh_ent.setdefault(
                        _pi["name"], fp.relative_to(W).as_posix()[:-3])

        def _redirect(path_part: str, disp: str = "") -> str:
            seg = path_part.split("/")[-1]
            base = HASH_RE.sub("", seg)
            base = re.sub(r"^(person|org|concept|scenario|meeting|judgment)_",
                         "", base)
            target_rel = fresh_ent.get(disp) or fresh_ent.get(base)
            if target_rel:
                return (f"[[{target_rel}|{disp}]]" if disp
                        else f"[[{target_rel}]]")
            return disp or base          # 降级为纯文本, 消灭死链

        fixed = 0
        for fp in sorted(W.rglob("*.md")):
            if ".obsidian" in fp.parts or fp.name in (
                    "index.md", "log.md", "log.legacy.v4.md"):
                continue
            txt = fp.read_text(encoding="utf-8")
            new_txt = _HALT_RE.sub(
                lambda m: _redirect(m.group(1), m.group(2)), txt)
            new_txt = _HALT_PLAIN_RE.sub(
                lambda m: _redirect(m.group(1)), new_txt)
            if new_txt != txt:
                fp.write_text(new_txt, encoding="utf-8", newline="\n")
                fixed += 1
        # index.md 同样处理
        ip = W / "index.md"
        if ip.exists():
            it = ip.read_text(encoding="utf-8")
            new_it = _HALT_RE.sub(
                lambda m: _redirect(m.group(1), m.group(2)), it)
            new_it = _HALT_PLAIN_RE.sub(
                lambda m: _redirect(m.group(1)), new_it)
            if new_it != it:
                ip.write_text(new_it, encoding="utf-8", newline="\n")
                fixed += 1
        report["halluc_links_fixed"] = fixed

    return report


# ============ CLI ============
if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="s12 分片页增量收尾")
    ap.add_argument("--wiki", default="wiki", help="wiki 根目录")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    r = polish_pages(args.wiki, dry_run=args.dry_run)
    print(f"扫描分片页: {r['scanned']} | 冗余删除: {r['redundant_deleted']} "
          f"| 规范化: {r['renamed']} | 链接处理: {r['links_fixed']} "
          f"| 幻觉死链重定向页: {r.get('halluc_links_fixed', 0)}")
    for d in r["details"]:
        print(f"  {d}")
