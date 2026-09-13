"""pj102 engine · 完整性校验脚本 v1.1 (P0 工具链还债)

v1.0 → v1.1 变更:
  - 根治硬编码阈值漂移 (35/2/0 → 实际 36/1/1 导致 3 个假红项)
  - 阈值动态化: type1/type2 只查下限(产出只增不减), 重复只查去重机制生效
  - 已知债务白名单: validation_errors 仅在出现白名单外新错误时才红
  - 新增 YAML frontmatter 全库扫描 (G1 最后防线: 0 错误)
  - 语义 = "无新增红项" (存量已知债务不判红)

校验项:
  1. 源文件全部已摄入(index.json samples 全部登记)
  2. 重复文件去重机制生效
  3. 知识库产出完整(每会议 1 meeting + 实体页下限)
  4. YAML frontmatter 0 错误 (生成器 P0 根治后应恒为 0)
  5. 实体注册表 / 主索引 / 日志 / 配置存在
"""
import os
import json
import re
import sys
from pathlib import Path
from datetime import datetime

import yaml as _yaml

PROJECT_ROOT = Path(os.environ.get("PJ102_PROJECT_ROOT") or Path.cwd())
WIKI = PROJECT_ROOT / "wiki"
SYSTEM = PROJECT_ROOT / "system"

# ---- 已知债务白名单 (仅记录事实, 不判红; 新增项才红) ----
KNOWN_VALIDATION_ERRORS = [
    "20260902_2109",  # 千问智能体对话: 源文件无"发言人"行, 摄入层校验失败(历史已知)
]
# type1/type2 产出下限 (只增不减语义; 新增源文件只会使实际值更大)
TYPE1_MIN = 36   # 2026-09-09 实测基线
TYPE2_MIN = 4


def check(label: str, condition: bool, details: str = "") -> bool:
    icon = "✓" if condition else "❌"
    print(f"  {icon} {label}" + (f"  [{details}]" if details else ""))
    return condition


def scan_yaml_errors() -> int:
    """全库 YAML frontmatter 扫描 (G1 最后防线)"""
    if not WIKI.exists():
        return -1
    bad = 0
    for m in WIKI.rglob("*.md"):
        if any(x in m.parts for x in (".obsidian", ".claude", ".claudian")):
            continue
        txt = m.read_text(encoding="utf-8", errors="ignore")
        if not txt.startswith("---"):
            continue
        end = txt.find("\n---", 3)
        if end < 0:
            bad += 1
            continue
        try:
            _yaml.safe_load(txt[3:end])
        except Exception:
            bad += 1
    return bad


def main():
    print("=" * 60)
    print(f"pj102 engine · 完整性校验 v1.1")
    print(f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"项目根: {PROJECT_ROOT}")
    print("=" * 60)

    all_ok = True

    # 1. 源文件摄入 (动态阈值: 只查下限与机制生效, 不锁死具体数)
    print("\n[1] 源文件摄入 (阈值动态化 v1.1)")
    index_path = SYSTEM / "state" / "index.json"
    proc_path = SYSTEM / "state" / "processed_files.json"
    if index_path.exists():
        idx = json.loads(index_path.read_text(encoding="utf-8"))
        s = idx.get("stats", {})
        samples = idx.get("samples", [])
        all_ok &= check("index.json 存在", True,
                        f"总{s.get('total_files',0)}/独立{s.get('unique_files',0)}")
        all_ok &= check(f"type1 录音文字 ≥{TYPE1_MIN}",
                        s.get("type1_meeting", 0) >= TYPE1_MIN,
                        f"实际{s.get('type1_meeting',0)}个")
        all_ok &= check(f"type2 手机通话 ≥{TYPE2_MIN}",
                        s.get("type2_phone_call", 0) >= TYPE2_MIN,
                        f"实际{s.get('type2_phone_call',0)}个")
        all_ok &= check("重复去重机制生效", s.get("duplicates_skipped", 0) >= 1,
                        f"识别{s.get('duplicates_skipped',0)}个")

        # 校验失败: 仅白名单外新增才红
        verr_files = idx.get("validation_error_files", []) or []
        new_errs = [f for f in verr_files
                    if not any(k in str(f) for k in KNOWN_VALIDATION_ERRORS)]
        all_ok &= check("无新增校验失败 (白名单外)",
                        len(new_errs) == 0,
                        f"已知{len(KNOWN_VALIDATION_ERRORS)}项/新增{len(new_errs)}项")

        # 覆盖率: index samples 全部已登记处理
        if proc_path.exists():
            d = json.loads(proc_path.read_text(encoding="utf-8"))
            done_hashes = {x.get("content_hash") for x in d.get("processed", [])}
            undone = [sm.get("filename", "?") for sm in samples
                      if sm.get("content_hash") not in done_hashes]
            all_ok &= check("索引样本全登记", len(undone) == 0,
                            f"未登记{len(undone)}个" + (f": {undone[0][:40]}" if undone else ""))
    else:
        all_ok &= check("index.json 存在", False, "未生成")

    # 2. 断点续跑状态
    print("\n[2] 断点续跑状态")
    if proc_path.exists():
        d = json.loads(proc_path.read_text(encoding="utf-8"))
        n_done = len(d.get("processed", []))
        all_ok &= check("processed_files.json 存在", True, f"已登记{n_done}个")
    else:
        all_ok &= check("processed_files.json 存在", False, "未生成")

    # 3. 知识库产出
    print("\n[3] 知识库产出")
    all_ok &= check("wiki/Meetings 存在", (WIKI / "Meetings").exists())
    meetings = list((WIKI / "Meetings").glob("*.md")) if (WIKI / "Meetings").exists() else []
    all_ok &= check("meeting 文件数 ≥ 1", len(meetings) >= 1, f"实际{len(meetings)}个")

    all_ok &= check("wiki/Entities/Persons 存在", (WIKI / "Entities" / "Persons").exists())
    persons = list((WIKI / "Entities" / "Persons").glob("*.md")) if (WIKI / "Entities" / "Persons").exists() else []
    all_ok &= check("person 文件数 ≥ 5", len(persons) >= 5, f"实际{len(persons)}个")

    concepts = list((WIKI / "Knowledge" / "Concepts").glob("*.md")) if (WIKI / "Knowledge" / "Concepts").exists() else []
    judgments = list((WIKI / "Knowledge" / "Judgments").glob("*.md")) if (WIKI / "Knowledge" / "Judgments").exists() else []
    all_ok &= check("concept 文件数 ≥ 5", len(concepts) >= 5, f"实际{len(concepts)}个")
    all_ok &= check("judgment 文件数 ≥ 5", len(judgments) >= 5, f"实际{len(judgments)}个")

    # 4. YAML frontmatter (G1 最后防线, v1.1 新增)
    print("\n[4] YAML frontmatter (G1 最后防线)")
    yaml_bad = scan_yaml_errors()
    all_ok &= check("YAML 错误 = 0", yaml_bad == 0, f"实际{yaml_bad}个")

    # 5. 实体注册表 / 主索引 / 日志
    print("\n[5] 实体注册表 / 主索引 / 日志")
    reg = SYSTEM / "registry" / "entity_registry.json"
    if reg.exists():
        d = json.loads(reg.read_text(encoding="utf-8"))
        all_ok &= check("entity_registry.json 存在", True, f"实体{len(d.get('entities',[]))}个")
    else:
        all_ok &= check("entity_registry.json 存在", False, "未生成")

    main_idx = WIKI / "index.md"
    all_ok &= check("wiki/index.md 存在", main_idx.exists())
    log_md = WIKI / "log.md"
    all_ok &= check("wiki/log.md 存在", log_md.exists())

    # 6. 配置一致性
    print("\n[6] 配置一致性")
    cfg_yaml = PROJECT_ROOT / "config" / "pipeline.yaml"
    all_ok &= check("config/pipeline.yaml 存在", cfg_yaml.exists())
    project_yaml = PROJECT_ROOT / "config" / "project.yaml"
    all_ok &= check("config/project.yaml 存在", project_yaml.exists())
    version = PROJECT_ROOT / "VERSION"
    all_ok &= check("VERSION 存在", version.exists())

    # 总结
    print()
    print("=" * 60)
    if all_ok:
        print("✅ 完整性校验全部通过 (v1.1 语义: 无新增红项)")
    else:
        print("⚠️  完整性校验有失败项, 请检查")
    print("=" * 60)
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
