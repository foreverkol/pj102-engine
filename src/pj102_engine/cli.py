# -*- coding: utf-8 -*-
"""pj102 CLI — 引擎统一入口 (init/ingest/run/ask/lint/verify/mcp/version)

铁律: 引擎(本包)只读; 一切实例数据都在 PJ102_PROJECT_ROOT 指向的实例目录;
     引擎与实例彻底分离, 升级引擎不动实例数据。
"""
import argparse
import os
import runpy
import shutil
import sys
from datetime import date
from pathlib import Path

ENGINE_VERSION = "2.3.0"
ENGINE_DIR = Path(__file__).resolve().parent
CODE_DIR = ENGINE_DIR / "code"
SCRIPTS_DIR = ENGINE_DIR / "scripts"


def _resolve_instance(explicit):
    root = Path(explicit or os.environ.get("PJ102_PROJECT_ROOT") or os.getcwd()).resolve()
    if not (root / "config").is_dir():
        print("[pj102] 错误: %s 不是实例目录(缺 config/)" % root)
        print("       请先执行: pj102 init <目录名>")
        sys.exit(2)
    os.environ["PJ102_PROJECT_ROOT"] = str(root)
    return root


def _run(target: Path, argv_extra):
    sys.path.insert(0, str(CODE_DIR))
    sys.path.insert(0, str(SCRIPTS_DIR))
    sys.argv = [str(target)] + argv_extra
    runpy.run_path(str(target), run_name="__main__")


def cmd_init(args):
    dest = Path(args.name).resolve()
    if dest.exists() and any(dest.iterdir()):
        print("[pj102] 错误: 目录已存在且非空: %s" % dest)
        sys.exit(2)
    name = dest.name
    subdirs = [
        "config", "source",
        "wiki/Meetings", "wiki/Entities/Persons", "wiki/Entities/Organizations",
        "wiki/Knowledge/Concepts", "wiki/Knowledge/Judgments", "wiki/Knowledge/Scenarios",
        "wiki/Summaries", "wiki/Queries",
        "system/state", "system/logs", "system/registry", "system/citations",
        "logs", "outputs",
    ]
    for d in subdirs:
        (dest / d).mkdir(parents=True, exist_ok=True)
    defaults = ENGINE_DIR / "defaults"
    shutil.copy(defaults / "pipeline.yaml", dest / "config" / "pipeline.yaml")
    shutil.copy(defaults / "taxonomy.yaml", dest / "config" / "taxonomy.yaml")
    tmpl_dir = defaults / "templates"
    if tmpl_dir.is_dir():
        shutil.copytree(tmpl_dir, dest / "config" / "templates", dirs_exist_ok=True)
    proj = (defaults / "project.yaml.example").read_text(encoding="utf-8")
    proj = proj.replace("{{PROJECT_NAME}}", name)
    proj = proj.replace("{{PROJECT_SHORT}}", name[:8])
    proj = proj.replace("{{TODAY}}", date.today().isoformat())
    (dest / "config" / "project.yaml").write_text(proj, encoding="utf-8")
    (dest / ".env").write_text(
        (defaults / "env.example").read_text(encoding="utf-8"), encoding="utf-8")
    (dest / "VERSION").write_text("0.1.0-new-instance\n", encoding="utf-8")
    (dest / ".gitignore").write_text(
        "wiki/\nsystem/\nlogs/\noutputs/\nqueries/\n.env\n__pycache__/\n", encoding="utf-8")
    print("[pj102] 实例已创建: %s" % dest)
    print("  下一步: 1) 编辑 config/project.yaml 填入源目录/人物/关键词")
    print("          2) 在 .env 填入 LLM API key")
    print("          3) 把转写 markdown 放入 source/ 后执行 pj102 ingest")


def cmd_ingest(args):
    _resolve_instance(args.instance)
    _run(SCRIPTS_DIR / "ingest_source.py", args.extra)


def cmd_run(args):
    _resolve_instance(args.instance)
    argv = []
    if args.budget_yuan is not None:
        argv += ["--budget-yuan", str(args.budget_yuan)]
    if args.max_samples is not None:
        argv += ["--max-samples", str(args.max_samples)]
    _run(SCRIPTS_DIR / "run_full.py", argv + args.extra)


def cmd_ask(args):
    _resolve_instance(args.instance)
    argv = [args.question]
    if getattr(args, "stub", False):
        argv.append("--stub")
    _run(SCRIPTS_DIR / "run_query.py", argv + args.extra)


def cmd_lint(args):
    _resolve_instance(args.instance)
    _run(CODE_DIR / "lint_wiki.py", args.extra)


def cmd_stats(args):
    _resolve_instance(args.instance)
    W = Path(os.environ["PJ102_PROJECT_ROOT"]) / "wiki"
    counts = {}
    total = 0
    for p in W.rglob("*.md"):
        if ".obsidian" in p.parts:
            continue
        total += 1
        top = p.relative_to(W).parts[0] if p.relative_to(W).parts else "?"
        counts[top] = counts.get(top, 0) + 1
    print("知识库统计:")
    print("  总页数: %d" % total)
    idx = W / "index.md"
    if idx.exists():
        print("  索引链接: %d" % idx.read_text(encoding="utf-8").count("[["))
    if counts:
        print("  分区:")
        for k, v in sorted(counts.items(), key=lambda x: -x[1]):
            print("    %s: %d" % (k, v))


def cmd_verify(args):
    _resolve_instance(args.instance)
    _run(SCRIPTS_DIR / "verify.py", args.extra)


def cmd_mcp(args):
    _resolve_instance(args.instance)
    _run(CODE_DIR / "kb_mcp_server.py", args.extra)


def cmd_version(args):
    print("pj102-engine %s" % ENGINE_VERSION)
    root = os.environ.get("PJ102_PROJECT_ROOT") or os.getcwd()
    vfile = Path(root) / "VERSION"
    if vfile.exists():
        print("instance: %s (%s)" % (vfile.read_text(encoding="utf-8").strip(), root))


def main(argv=None):
    ap = argparse.ArgumentParser(prog="pj102", description="LLM Wiki 编译引擎 CLI")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("init", help="创建全新空白实例")
    p.add_argument("name", help="实例目录名或路径")
    p.set_defaults(func=cmd_init)

    p = sub.add_parser("ingest", help="扫描 source/ 分型入库(幂等)")
    p.add_argument("--instance", "-i", default=None)
    p.add_argument("extra", nargs="*")
    p.set_defaults(func=cmd_ingest)

    p = sub.add_parser("run", help="运行 13 步全管线(含熔断/批次报告)")
    p.add_argument("--instance", "-i", default=None)
    p.add_argument("--budget-yuan", type=float, default=None)
    p.add_argument("--max-samples", type=int, default=None)
    p.add_argument("extra", nargs="*")
    p.set_defaults(func=cmd_run)

    p = sub.add_parser("ask", help="检索问答 (L1 实体导航 / L2 综合问答)")
    p.add_argument("--instance", "-i", default=None)
    p.add_argument("question")
    p.add_argument("--stub", action="store_true",
                  help="L2 用 stub, 不调 LLM (快速 L1 测试)")
    p.add_argument("extra", nargs="*")
    p.set_defaults(func=cmd_ask)

    p = sub.add_parser("lint", help="15 维质量巡检")
    p.add_argument("--instance", "-i", default=None)
    p.add_argument("extra", nargs="*")
    p.set_defaults(func=cmd_lint)

    p = sub.add_parser("stats", help="知识库规模统计(页数/分区/索引)")
    p.add_argument("--instance", "-i", default=None)
    p.add_argument("extra", nargs="*")
    p.set_defaults(func=cmd_stats)

    p = sub.add_parser("verify", help="一致性核验")
    p.add_argument("--instance", "-i", default=None)
    p.add_argument("extra", nargs="*")
    p.set_defaults(func=cmd_verify)

    p = sub.add_parser("mcp", help="启动 MCP 服务(kb_query/kb_lint/kb_stats)")
    p.add_argument("--instance", "-i", default=None)
    p.add_argument("extra", nargs="*")
    p.set_defaults(func=cmd_mcp)

    p = sub.add_parser("version", help="引擎/实例版本")
    p.set_defaults(func=cmd_version)

    args = ap.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
