"""pj102 engine · 数据摄入脚本 v1.1 (P4 T-P4.5)

功能:
  1. 扫描源目录(已治理的录音转写)
  2. 按命名规律分类(类型1: 录音文字 / 类型2: 手机通话)
  3. 计算 content_hash (SHA256[:12]) 用于去重
  4. 与 system/state/processed_files.json 比对, 跳过已处理
  5. 校验: 文件大小>0 / 中文比例>50% / 内容按 file_class 分型校验
  6. 检测重复文件(标记跳过)
  7. 生成 system/state/index.json 和 processed_files.json
  8. [v1.1] file_class 内容分型 (transcript/minutes/article/note/chat, ADR-003 T2)
  9. [v1.1] --batch 输出批次清单 json (供 run_full 批次门消费)

用法:
  python scripts/ingest_source.py [--source SOURCE_DIR] [--dry-run] [-v]
  (非 dry-run 时总是产出批次清单 batch_manifest_*.json, 供 run_full 批次门消费)
"""
from __future__ import annotations
import os

import argparse
import hashlib
import json
import re
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# 路径配置(基于脚本位置)
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = Path(os.environ.get("PJ102_PROJECT_ROOT") or Path.cwd())
sys.path.insert(0, str(PROJECT_ROOT / "code"))

# 类型1: 录音文字(日期数字开头, 形如 20230907_083619xxx_原文.md)
# 接受 8 位日期 + 可选 6 位时间(中间用 _ 分隔)
TYPE1_PATTERN = re.compile(r"^20\d{6,8}(?:[_\s]?\d{4,6})?[\u4e00-\u9fff_].*?_原文\.md$")
# 类型2: 手机通话(人名@手机号_日期_原文.md, 手机号允许空格/下划线分段)
# 电话文件名日期为 14 位数字: 20260829191607 (yyyyMMddHHmmss)
TYPE2_PATTERN = re.compile(r"^[\u4e00-\u9fff]+@[\d\s_]+_20\d{12}.*?_原文\.md$")
# 类型2-宽松: 数字日期开头+人名@描述, 如 "20260903_164036张三通话记录@深圳培训...md"
TYPE2_SOFT_PATTERN = re.compile(r"^20[\d_]+[\u4e00-\u9fff]+@.+?\.md$")


def compute_content_hash(content: str) -> str:
    """SHA256[:12] 作为 content_hash 唯一标识"""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()[:12]


# ---- v1.1 file_class 内容分型 (ADR-003 T2: 校验规则按 class 分型) ----

def classify_file_class(content: str) -> str:
    """从内容信号分型 file_class (ADR-003 §5.4, 旧样本一律视为 transcript)

    v1.2: minutes 结构词行首锚定并提前于 chat —— 纪要中"参会人员: xxx"式
    冒号行可能 >=10 行, 若 chat 先判会误吞 minutes (T5 实测发现)
    """
    if re.search(r"^.{0,12}发言人", content, re.M) or "发言人" in content[:2000]:
        return "transcript"
    # 纪要体: 结构词出现在行首 (会议纪要/议题/决议/参会人员/会议时间/会议地点)
    if re.search(r"^(会议纪要|议题|决议|参会人员|会议时间|会议地点)", content[:3000], re.M):
        return "minutes"
    # 对话体: "张三: 内容" 连续多行
    dialogue_lines = len(re.findall(r"^.{1,12}[:：]\s*\S", content, re.M))
    if dialogue_lines >= 10:
        return "chat"
    # 笔记体: 列表项为主
    lines = [ln for ln in content.splitlines() if ln.strip()]
    if lines and sum(1 for ln in lines if ln.lstrip().startswith(("-", "*", "1."))) / len(lines) > 0.5:
        return "note"
    return "article"


# 校验规则按 file_class 分型 (transcript 必须含发言人; 其类不要求)
_SPEAKER_REQUIRED = ("transcript",)


def classify_file(filename: str) -> str:
    """按命名规律分类: type1=录音文字, type2=手机通话, unknown=其他"""
    if TYPE1_PATTERN.match(filename):
        return "type1_meeting"
    if TYPE2_PATTERN.match(filename):
        return "type2_phone_call"
    if TYPE2_SOFT_PATTERN.match(filename):
        return "type2_phone_call"
    return "unknown"


def parse_date_from_filename(filename: str) -> Optional[str]:
    """从文件名提取日期(支持两类)"""
    # 类型1: 20230907_xxx
    m = re.match(r"^20(\d{2})(\d{2})(\d{2})(?:_(\d{2})(\d{2})(\d{2}))?", filename)
    if m:
        y, mo, d = m.group(1), m.group(2), m.group(3)
        return f"20{y}-{mo}-{d}"
    # 类型2: @日期时间_20260829191607
    m = re.search(r"_20(\d{2})(\d{2})(\d{2})(\d{2})(\d{2})(\d{2})", filename)
    if m:
        y, mo, d, h, mi, s = m.groups()
        return f"20{y}-{mo}-{d} {h}:{mi}:{s}"
    return None


def extract_phone(filename: str) -> Optional[str]:
    """从类型2文件名提取手机号"""
    m = re.match(r"^[\u4e00-\u9fff]+@([\d\s_]+)_20\d{14}", filename)
    if m:
        # 去掉空格和下划线, 拼接手机号
        phone = re.sub(r"[\s_]", "", m.group(1))
        return phone if len(phone) >= 11 else None
    return None


def extract_person_name(filename: str) -> Optional[str]:
    """从类型2文件名提取人名"""
    m = re.match(r"^([\u4e00-\u9fff]+)@", filename)
    return m.group(1) if m else None


def chinese_ratio(content: str) -> float:
    """中文字符占比"""
    if not content:
        return 0.0
    chinese = sum(1 for c in content if "\u4e00" <= c <= "\u9fff")
    return chinese / len(content)


def validate_file(file_path: Path, content: str, file_class: str = "transcript") -> Tuple[bool, List[str]]:
    """校验文件有效性, 返回 (是否通过, 错误列表)

    v1.1: 发言人校验仅对 transcript 类强制 (ADR-003 分型)
    """
    errors = []
    if file_path.stat().st_size == 0:
        errors.append("empty file")
    if chinese_ratio(content) < 0.5:
        errors.append(f"chinese ratio too low: {chinese_ratio(content):.2%}")
    if file_class in _SPEAKER_REQUIRED and "发言人" not in content:
        errors.append("missing '发言人' marker (not a conversation transcript)")
    return (len(errors) == 0, errors)


def load_processed_files(processed_state: Path) -> Dict[str, dict]:
    """加载已处理文件清单 (P4 T-P4.7: 仅 status=="ok" 视为已处理, 墓碑不阻塞复检)"""
    if not processed_state.exists():
        return {}
    try:
        data = json.loads(processed_state.read_text(encoding="utf-8"))
        return {e["content_hash"]: e for e in data.get("processed", [])
                if e.get("status", "ok") == "ok"}
    except Exception:
        return {}


def save_processed_files(processed_state: Path, processed: Dict[str, dict]) -> None:
    """保存已处理文件清单"""
    processed_state.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "version": "1.0",
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "count": len(processed),
        "processed": list(processed.values()),
    }
    processed_state.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def run_ingest(
    source_dir: Path,
    project_root: Path,
    dry_run: bool = False,
    verbose: bool = False,
) -> Dict:
    """主摄入流程"""
    system_dir = project_root / "system"
    index_path = system_dir / "state" / "index.json"
    processed_state = system_dir / "state" / "processed_files.json"
    log_dir = system_dir / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)

    log_lines = []
    def log(msg: str):
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        line = f"[{ts}] {msg}"
        log_lines.append(line)
        if verbose:
            print(line)

    log(f"=== 数据摄入开始 ===")
    log(f"源目录: {source_dir}")
    log(f"项目根: {project_root}")

    if not source_dir.exists():
        log(f"❌ 源目录不存在: {source_dir}")
        return {"error": "source dir not found"}

    # 扫描源文件
    # ⛔ 护栏 (D-27 裁定, 2026-09-15): 严禁把本 glob("*.md") 改为递归 (rglob/**) ——
    # 非递归是"汇总包/子目录不入扫描范围"的隐性保护: 递归会把与顶层源文件
    # 内容重叠的 merged 汇总包卷入, 批量制造重复摄入。若确需子目录, 必须先配
    # content_hash 全局去重并经人工裁决。
    md_files = sorted(source_dir.glob("*.md"))
    log(f"扫描到 {len(md_files)} 个 .md 文件")

    # 分类 + content_hash + 校验
    samples = []
    seen_hashes = set()
    duplicates_skipped = []
    validation_errors = []
    classification = Counter()

    for f in md_files:
        file_type = classify_file(f.name)
        classification[file_type] += 1

        try:
            content = f.read_text(encoding="utf-8")
        except Exception as e:
            validation_errors.append({"file": f.name, "errors": [f"read error: {e}"]})
            continue

        content_hash = compute_content_hash(content)

        # 去重
        if content_hash in seen_hashes:
            duplicates_skipped.append(f.name)
            log(f"  重复(已跳过): {f.name} hash={content_hash}")
            continue
        seen_hashes.add(content_hash)

        # v1.1 file_class 内容分型
        file_class = classify_file_class(content)

        # 校验 (按 class 分型)
        valid, errors = validate_file(f, content, file_class)
        if not valid:
            validation_errors.append({"file": f.name, "errors": errors})
            log(f"  校验失败: {f.name} - {errors}")
            continue

        # 提取元信息
        record = {
            "filename": f.name,
            "filepath": str(f.relative_to(source_dir)),
            "file_type": file_type,
            "file_class": file_class,
            "content_hash": content_hash,
            "size_bytes": f.stat().st_size,
            "date": parse_date_from_filename(f.name),
        }
        if file_type == "type2_phone_call":
            record["person_name"] = extract_person_name(f.name)
            record["phone"] = extract_phone(f.name)

        samples.append(record)
        log(f"  ✓ {f.name} | {file_type}/{file_class} | {record.get('date', '?')} | hash={content_hash}")

    # 对比已处理文件(本项目之前跑过)
    processed = load_processed_files(processed_state)
    new_samples = []
    already_processed = []
    for s in samples:
        if s["content_hash"] in processed:
            already_processed.append(s["filename"])
        else:
            new_samples.append(s)

    log(f"")
    log(f"=== 摄入汇总 ===")
    log(f"总文件: {len(md_files)}")
    log(f"分类: type1_meeting={classification['type1_meeting']} / type2_phone_call={classification['type2_phone_call']} / unknown={classification['unknown']}")
    log(f"独立文件(去重后): {len(samples)}")
    log(f"重复跳过: {len(duplicates_skipped)}")
    log(f"校验失败: {len(validation_errors)}")
    log(f"已处理(本次跳过): {len(already_processed)}")
    log(f"待处理(新文件): {len(new_samples)}")
    log(f"file_class 分布: {dict(Counter(s['file_class'] for s in samples))}")

    # 构建 index.json
    index = {
        "version": "1.0",
        "project": "pj102-instance",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_dir": str(source_dir),
        "stats": {
            "total_files": len(md_files),
            "type1_meeting": classification["type1_meeting"],
            "type2_phone_call": classification["type2_phone_call"],
            "unknown": classification["unknown"],
            "duplicates_skipped": len(duplicates_skipped),
            "validation_errors": len(validation_errors),
            "already_processed": len(already_processed),
            "to_process": len(new_samples),
            "unique_files": len(samples),
        },
        "duplicates": duplicates_skipped,
        "validation_errors": validation_errors,
        "samples": samples,
        "new_samples": [s["filename"] for s in new_samples],
    }

    if not dry_run:
        index_path.parent.mkdir(parents=True, exist_ok=True)
        index_path.write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")
        log(f"✓ index.json 已写入: {index_path}")
        # 注: processed_files.json 由 pipeline 跑完时自动写(mark_processed)
        #     ingest 只写 index.json, 不污染断点续跑状态

        # v1.1 --batch: 批次清单 (防线1 → 防线2 的交接物)
        batch_manifest = {
            "batch_id": f"B{datetime.now().strftime('%Y%m%d_%H%M%S')}",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "to_process": [
                {"filename": s["filename"], "content_hash": s["content_hash"],
                 "file_type": s["file_type"], "file_class": s["file_class"],
                 "date": s.get("date")}
                for s in new_samples
            ],
        }
        batch_path = system_dir / "state" / f"batch_manifest_{batch_manifest['batch_id']}.json"
        batch_path.write_text(json.dumps(batch_manifest, ensure_ascii=False, indent=2),
                              encoding="utf-8")
        log(f"✓ 批次清单已写入: {batch_path}")

    # 写日志
    log_file = log_dir / f"ingest_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
    log_file.write_text("\n".join(log_lines), encoding="utf-8")

    return {
        "total": len(md_files),
        "unique": len(samples),
        "duplicates": len(duplicates_skipped),
        "to_process": len(new_samples),
        "already_processed": len(already_processed),
        "validation_errors": len(validation_errors),
        "type1": classification["type1_meeting"],
        "type2": classification["type2_phone_call"],
        "index_path": str(index_path) if not dry_run else None,
    }


def main():
    parser = argparse.ArgumentParser(description="pj102 engine · 数据摄入")
    parser.add_argument("--source", help="源数据目录(默认从 config/project.yaml 读)")
    parser.add_argument("--project-root", help="项目根目录(默认脚本上一级)")
    parser.add_argument("--dry-run", action="store_true", help="只扫描不写入")
    parser.add_argument("-v", "--verbose", action="store_true", help="详细日志")
    args = parser.parse_args()

    # 读 project.yaml(如果存在) — 从实例根读(PJ102_PROJECT_ROOT), 不随引擎安装位置走
    project_yaml = PROJECT_ROOT / "config" / "project.yaml"
    source_from_yaml = None
    if project_yaml.exists() and not args.source:
        try:
            import yaml
            cfg = yaml.safe_load(project_yaml.read_text(encoding="utf-8"))
            source_from_yaml = cfg.get("scope", {}).get("source_dir")
        except Exception:
            pass

    source_dir = Path(args.source or source_from_yaml or "")
    project_root = Path(args.project_root) if args.project_root else PROJECT_ROOT

    # 占位符守卫: init 生成的 {{...}} 未替换视为未配置, 显式报错而非静默扫 0
    if "{{" in str(source_dir):
        print(f"❌ source_dir 仍是占位符未配置: {source_dir}")
        print(f"   请编辑 config/project.yaml 将 scope.source_dir 替换为你的真实源目录")
        sys.exit(1)

    if not source_dir or not source_dir.exists():
        print(f"❌ 源目录无效: {source_dir}")
        print(f"   请通过 --source 指定, 或在 config/project.yaml 的 scope.source_dir 配置")
        sys.exit(1)

    result = run_ingest(source_dir, project_root, dry_run=args.dry_run, verbose=args.verbose)

    print("")
    print("=" * 50)
    print("摄入完成")
    print("=" * 50)
    for k, v in result.items():
        print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
