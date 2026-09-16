"""
v4.0 backlink_builder.py - 反向链接 (Karpathy LLM Wiki 缺口6)

扫描 wiki/ 所有 .md, 建立双向链接知识网络:
  - 对每个 wiki 文件, 提取其 body 提到的实体名
  - 在被提到实体的 wiki 文件 frontmatter 加 backlinks: [引用方]
  - 实现 "页面之间能点击跳转" 的知识网

设计:
  - 读 entity_registry.json 获取所有实体名 (canonical_name + aliases)
  - 扫描每个 wiki 文件 body, 检查提到哪些实体名
  - 对 person/org wiki 文件, 在 frontmatter 加 backlinks 字段
  - 幂等: 每次重建 backlinks (覆盖)
"""

import sys
import re
import json
from pathlib import Path
from typing import List, Dict, Set, Tuple

sys.path.insert(0, str(Path(__file__).parent))
from core import AppConfig, get_logger

import yaml

log = get_logger()

BACKLINKS_KEY = "backlinks"


def load_entity_names(registry_path: Path) -> Dict[str, List[str]]:
    """从 entity_registry.json 加载实体名 (canonical_name -> [aliases])"""
    if not registry_path.exists():
        return {}
    try:
        data = json.loads(registry_path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    result = {}
    for ent in data.get("entities", []):
        cn = ent.get("canonical_name", "")
        if cn:
            aliases = ent.get("aliases", [])
            result[cn] = aliases
    return result


# T2 时间分页后缀：`张三（2025-05-29）`（全角括号 + ISO 日期）
_T2_SUFFIX_RE = r"（\d{4}-\d{2}-\d{2}）"


def load_entity_types(registry_path: Path) -> Dict[str, str]:
    """从 entity_registry.json 加载 `canonical_name -> entity_type`。

    旧实现对**每个实体**都重新 `json.loads` 整个 registry（513 实体 ⇒ 513 次全量解析），
    这里一次性读入，顺带给 `build_entity_file_map` 提供类型（决定去 Persons 还是
    Organizations 目录找页），避免跨目录误命中。
    """
    if not registry_path.exists():
        return {}
    try:
        data = json.loads(registry_path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    out: Dict[str, str] = {}
    for ent in data.get("entities", []):
        cn = ent.get("canonical_name", "")
        if cn:
            out[cn] = ent.get("entity_type") or ""
    return out


def _entity_dirs(wiki_root: Path, entity_type: str = None) -> List[Path]:
    """按 entity_type 返回要检索的实体页目录（None = 先 Persons 后 Organizations）。"""
    out: List[Path] = []
    if entity_type == "person" or entity_type is None:
        out.append(wiki_root / "Entities" / "Persons")
    if entity_type == "organization" or entity_type is None:
        out.append(wiki_root / "Entities" / "Organizations")
    return out


def _match_specific(files: List[Path], name: str) -> Tuple[List[Path], int]:
    """返回 (命中页, 优先级)：P1 = 0 精确同名；P2 = 1 T2 时间分页族；未命中 = (-1)。

    P1/P2 是**强归属**：一个页只能属于 `stem` 恰好等于其名（或 `名（日期）`）的实体。
    这是 D-52 修复的核心 —— 只有强归属成立，backlinks 才不会写错对象。
    """
    exact, paged = [], []
    pat = re.compile(re.escape(name) + _T2_SUFFIX_RE + r"\Z")
    for f in files:
        s = f.stem
        if s == name:
            exact.append(f)
        elif pat.match(s):
            paged.append(f)
    if exact:
        return exact + paged, 0
    if paged:
        return paged, 1
    return [], -1


def _loose_candidates(files: List[Path], name: str) -> List[Path]:
    """P3 子串兜底候选：按 (文件名长度, 文件名) 升序 —— 越短越贴近实体名。

    为什么必须按长度排序
    --------------------
    实体名 `阿里` 若按目录序取首个命中，会抢到 `A公司.md`
    （因为它在排序上先于别的候选），从而把该页的 backlinks 写成 `阿里` 的引用。
    取最短候选取其「最像自己」的一页，可把误抢压到最低；残余竞争由
    `build_entity_file_map()` 的**特异性优先分配**兜住。
    """
    cand = [f for f in files if name and name in f.stem]
    return sorted(cand, key=lambda f: (len(f.stem), f.stem))


def build_entity_file_map(wiki_root: Path, entity_types: Dict[str, str]) -> Dict[str, List[Path]]:
    """为每个实体解析其 wiki 页，**保证一个文件只归属一个实体**（D-52 修复）。

    为什么必须有它
    --------------
    只做子串匹配时，同一个页会被多个实体同时命中。实测（2026-09-16）有 **20 个页**
    存在多实体争抢，例如：
      · `Entities/Organizations/A公司.md` ← `阿里` / `千问` / `A公司`
      · `Entities/Organizations/B公司.md`     ← `平安` / `B公司`
      · `Entities/Persons/张三代办.md`         ← `张三` / `张三代办`
    后果有二：
      ① **归属错误**：页的 frontmatter `backlinks` 由「最后一个写入的实体」决定，
         `A公司.md` 最终挂的是 `阿里` 的引用（错对象）；
      ② **计数虚高**：每次运行这些页都被重写（后写覆盖前写），
         即使内容已收敛，仍稳定报「41 个文件更新」⇒ 幂等性无法用计数验证。

    分配规则：P1 精确同名 > P2 T2 分页族 > P3 子串兜底；同优先级按实体名排序，
    **先占先得**，后来者跳过被占用的文件（P3 兜底只取一页，不整族吞并）。
    """
    groups: List[Tuple[int, str]] = []          # (优先级, 实体名)
    for name, ent_type in entity_types.items():
        if not name:
            continue
        best = -1
        for d in _entity_dirs(wiki_root, ent_type):
            if not d.exists():
                continue
            files = sorted(d.glob("*.md"))
            _, rank = _match_specific(files, name)
            if rank >= 0:
                best = rank if best < 0 else min(best, rank)
        groups.append((best if best >= 0 else 2, name))

    # 优先级升序；同优先级按实体名排序保证确定性
    groups.sort(key=lambda x: (x[0], x[1]))

    owner: Dict[Path, str] = {}
    result: Dict[str, List[Path]] = {}
    for rank, name in groups:
        ent_type = entity_types.get(name)
        picked: List[Path] = []
        for d in _entity_dirs(wiki_root, ent_type):
            if not d.exists():
                continue
            files = sorted(d.glob("*.md"))
            spec, _ = _match_specific(files, name)
            if spec:                                   # P1/P2：整族收下
                picked.extend(f for f in spec if f not in owner)
            elif rank == 2:                            # P3：只取**一个**未被占用的最短页
                for f in _loose_candidates(files, name):
                    if f not in owner:
                        picked.append(f)
                        break
            if picked:
                break                                  # 命中即停止跨目录回退
        if picked:
            for f in picked:
                owner[f] = name
            result[name] = picked
    return result


def find_all_wiki_files_for_entity(wiki_root: Path, entity_name: str,
                                   entity_type: str = None) -> List[Path]:
    """返回实体对应的**全部** wiki 文件（D-44 正解）。

    为什么需要它
    ------------
    `entity_id` 可对应多页（T2 时间分页 `张三（2023-09-07）` / `张三（2025-05-29）`）。
    原实现 `find_wiki_file_for_entity` 只返回**首个**匹配页 ⇒
      · 首个匹配页的 backlinks 被反复重建；
      · 其余页的 backlinks **永远停留在旧值**（实测 `张三（2025-05-29）.md`
        残留 2 条指向已不存在的 `Meetings/meeting_<date>_<hash>.md`，即 `13_stale_backlinks`）。
    本函数让同族每一页都获得 backlinks，从根上消除该盲区。

    D-52 收紧：P1/P2 命中时**绝不**回落到 P3 子串（否则 `阿里` 会连带吞下
    `A公司.md`）。真需要跨实体去重时请用 `build_entity_file_map()`。
    """
    for d in _entity_dirs(wiki_root, entity_type):
        if not d.exists():
            continue
        spec, _ = _match_specific(sorted(d.glob("*.md")), entity_name)
        if spec:
            return spec
    for d in _entity_dirs(wiki_root, entity_type):
        if not d.exists():
            continue
        cand = _loose_candidates(sorted(d.glob("*.md")), entity_name)
        if cand:
            return cand[:1]
    return []


def find_wiki_file_for_entity(wiki_root: Path, entity_name: str,
                               entity_type: str = None) -> Path:
    """找实体对应的 wiki 文件（精确同名 > T2 分页族 > 子串兜底；禁止拼 glob 模式）"""
    files = find_all_wiki_files_for_entity(wiki_root, entity_name, entity_type)
    if not files:
        return None
    for f in files:
        if f.stem == entity_name:
            return f
    return files[0]


def parse_frontmatter_and_body(content: str) -> Tuple[dict, str]:
    """解析 frontmatter 和 body"""
    if not content.startswith("---"):
        return {}, content
    parts = content.split("---", 2)
    if len(parts) < 3:
        return {}, content
    try:
        fm = yaml.safe_load(parts[1]) or {}
        if not isinstance(fm, dict):
            fm = {}
    except Exception:
        fm = {}
    body = parts[2]
    return fm, body


def find_entities_in_text(text: str, entity_names: Dict[str, List[str]]) -> Set[str]:
    """在文本中查找出现的实体名 (canonical + aliases)"""
    found = set()
    for canonical, aliases in entity_names.items():
        if canonical and canonical in text:
            found.add(canonical)
            continue
        for alias in aliases:
            if alias and alias in text:
                found.add(canonical)
                break
    return found


def build_backlinks(cfg: AppConfig = None) -> dict:
    """主入口: 扫描 wiki 建立反向链接

    Returns:
        {"total_files": N, "backlinks_added": N, "entities_with_backlinks": N,
         "top_entities": [(name, count), ...]}
    """
    if cfg is None:
        cfg = AppConfig()
    wiki_root = cfg.paths.wiki_base
    registry_path = cfg.paths.registry_path

    if not wiki_root.exists():
        log.warning("wiki 目录不存在", step="backlink_builder")
        return {"total_files": 0, "backlinks_added": 0}

    # 1. 加载实体名
    entity_names = load_entity_names(registry_path)
    if not entity_names:
        log.warning("entity_registry 为空", step="backlink_builder")
    log.info(f"加载 {len(entity_names)} 个实体名", step="backlink_builder")

    # 2. 第一遍扫描: 建立实体 → [引用它的文件] 映射
    # entity_backlinks: {entity_name: [{file, rel_path, title}]}
    entity_backlinks: Dict[str, List[dict]] = {name: [] for name in entity_names}

    all_files = sorted(f for f in wiki_root.rglob("*.md")
                       if f.name not in ("index.md", "log.md"))
    for md_file in all_files:
        try:
            content = md_file.read_text(encoding="utf-8")
        except Exception:
            continue
        fm, body = parse_frontmatter_and_body(content)
        # 在 body 中查找实体名
        found = find_entities_in_text(body, entity_names)
        # 排除自身 (person 文件提到自己不算反向链接)
        own_entity = fm.get("canonical_name", "")
        if own_entity in found:
            found.discard(own_entity)
        title = fm.get("title", md_file.stem)
        rel_path = str(md_file.relative_to(wiki_root)).replace("\\", "/")
        for entity_name in found:
            entity_backlinks[entity_name].append({
                "file": rel_path,
                "title": title,
            })

    # 3. 第二遍写入: 对每个实体的 wiki 文件, 在 frontmatter 加 backlinks
    backlinks_added = 0
    entities_with_backlinks = 0
    top_entities = []

    # D-52 修复：**先算归属，再写入**。
    # 旧实现「逐实体现场匹配、边匹配边写」有两个硬伤：
    #   ① 同一页被多个实体命中时，谁最后写谁说了算 ⇒ backlinks 挂错对象；
    #   ② 每次运行都重写这些页 ⇒ 内容已收敛却仍报「N 个文件更新」，幂等性无法验证。
    # `build_entity_file_map` 按特异性（精确 > T2 分页族 > 子串兜底）一次性分配，
    # 一个文件只归属一个实体，写入因此**天然幂等**。
    entity_types = load_entity_types(registry_path)
    file_map = build_entity_file_map(wiki_root, entity_types)

    for entity_name, wiki_files in file_map.items():
        refs = entity_backlinks.get(entity_name, [])
        if not wiki_files:
            continue

        if refs:
            entities_with_backlinks += 1
            top_entities.append((entity_name, len(refs)))

        for wiki_file in wiki_files:
            if not wiki_file.exists():
                continue
            # 读原内容
            try:
                content = wiki_file.read_text(encoding="utf-8")
            except Exception:
                continue
            fm, body = parse_frontmatter_and_body(content)

            # 更新 backlinks 字段
            # **必须排序**：`refs` 由 `rglob` 遍历顺序累积而来，顺序不稳定
            # ⇒ 不排序会让每次重建都产生 261 个"伪变更"（幂等性丧失）。
            fm[BACKLINKS_KEY] = sorted({r["file"] for r in refs})

            # 序列化 frontmatter
            # ⚠ 拼接细节：`parse_frontmatter_and_body` 用 `split("---", 2)`，
            #   故 `body` **自身以 "\n" 开头**（即原文 `---\n\n# H1` 中的第二个 \n）。
            #   `_serialize_frontmatter` 已带尾部 "\n" 且**无前导 "\n"**。
            #   因此正确拼法是 `---\n` + fm + `---` + body（`---` 后**不能**再加 \n）。
            #   原写法 `f"---\n{new_fm}---\n{body}"` 每次重建都会在 body 前
            #   **多累积一个空行** ⇒ 全库每次"伪变更"数百文件、且永不幂等。
            new_fm = _serialize_frontmatter(fm)
            new_content = f"---\n{new_fm}---{body}"

            if new_content != content:
                wiki_file.write_text(new_content, encoding="utf-8", newline="\n")
                backlinks_added += 1

    top_entities.sort(key=lambda x: -x[1])

    log.info(f"backlinks 构建完成: {backlinks_added} 个文件更新, "
             f"{entities_with_backlinks} 个实体有反向链接",
             step="backlink_builder")

    return {
        "total_files": len(all_files),
        "backlinks_added": backlinks_added,
        "entities_with_backlinks": entities_with_backlinks,
        "top_entities": top_entities[:10],
    }


def _serialize_frontmatter(fm: dict) -> str:
    """手动序列化 frontmatter 为可读 YAML"""
    lines = []
    for k, v in fm.items():
        if v is None:
            lines.append(f"{k}:")
        elif isinstance(v, list):
            if v:
                lines.append(f"{k}:")
                for item in v:
                    lines.append(f"  - {item}")
            else:
                lines.append(f"{k}: []")
        elif isinstance(v, (int, float, bool)):
            lines.append(f"{k}: {v}")
        elif isinstance(v, str):
            if any(c in v for c in [":", "#", "'", '"', "\n", "{", "}", "[", "]", ",", "&", "*", "?", "|", "<", ">", "@", "`", "%"]):
                escaped = v.replace("'", "''")
                lines.append(f"{k}: '{escaped}'")
            elif v == "":
                lines.append(f"{k}: ''")
            else:
                lines.append(f"{k}: {v}")
        else:
            lines.append(f"{k}: {v}")
    return "\n".join(lines) + "\n"


# ============ CLI ============

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="PJ-102 反向链接构建器")
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args()

    result = build_backlinks()
    print(f"\n{'=' * 50}")
    print(f"🔗 反向链接构建完成")
    print(f"{'=' * 50}")
    print(f"扫描文件: {result['total_files']}")
    print(f"更新文件: {result['backlinks_added']}")
    print(f"有反向链接的实体: {result['entities_with_backlinks']}")
    if result.get("top_entities"):
        print(f"\n反向链接最多的实体:")
        for name, count in result["top_entities"]:
            print(f"  • {name}: {count} 个引用")
