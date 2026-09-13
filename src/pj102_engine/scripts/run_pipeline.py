"""pj102 engine · pipeline launcher v1.0

从 hermes .env 加载 MiniMax key, 然后跑真实 pipeline
指向本项目 code/(不是 PJ-102), 实现独立运行

用法:
  python scripts/run_pipeline.py --limit 10
  python scripts/run_pipeline.py --limit 10 --resume   # 断点续跑
  python scripts/run_pipeline.py --clear               # 清除已处理状态
  python scripts/run_pipeline.py --no-llm             # mock 模式(无 LLM 调用)
"""
import os
import sys

# 1. 从 hermes .env 加载 key(认 MINIMAX_CN_API_KEY)
HERMES_ENV = os.path.join(os.environ.get("PJ102_PROJECT_ROOT") or os.getcwd(), ".env")
if os.path.exists(HERMES_ENV):
    with open(HERMES_ENV, encoding="utf-8-sig") as f:
        for line in f:
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                k, _, v = line.partition("=")
                k = k.strip()
                v = v.strip().strip('"').strip("'")
                if k and k not in os.environ:
                    os.environ[k] = v

# 2. 确保 base_url 正确(国际版 sk-cp- key)
os.environ.setdefault("MINIMAX_CN_BASE_URL", "https://api.minimaxi.com")

# 3. 加入 PYTHONPATH(本项目 code/)
PROJECT_ROOT = os.environ.get("PJ102_PROJECT_ROOT") or os.getcwd()
CODE_DIR = os.path.join(PROJECT_ROOT, "code")
sys.path.insert(0, CODE_DIR)

# 4. 设置 project_root 环境变量(让 core/config.py 用本项目路径)
# 注: core/config.py 第 22 行已适配为 parents[2], 自动找到本项目根
os.environ.setdefault("PJ102_PROJECT_ROOT", PROJECT_ROOT)

# 4.5 设置 data_raw 指向外部源目录(从 config/project.yaml 读)
import yaml
project_yaml = os.path.join(PROJECT_ROOT, "config", "project.yaml")
if os.path.exists(project_yaml):
    with open(project_yaml, encoding="utf-8") as f:
        proj_cfg = yaml.safe_load(f) or {}
    source_dir = (proj_cfg.get("scope") or {}).get("source_dir")
    if source_dir:
        os.environ.setdefault("PJ102_DATA_RAW", source_dir)
        print(f"[launcher] 源目录: {source_dir}")

key_preview = os.environ.get("MINIMAX_CN_API_KEY", "")[:6]
print(f"[launcher] key 已加载(前6位: {key_preview}...)")
print(f"[launcher] base_url: {os.environ.get('MINIMAX_CN_BASE_URL')}")
print(f"[launcher] PROJECT_ROOT: {PROJECT_ROOT}")
print(f"[launcher] args: {' '.join(sys.argv[1:])}")
print()

# 5. 透传 CLI 给 pipeline.main()
sys.argv = ["pipeline.py"] + sys.argv[1:]
from pipeline import main
sys.exit(main())
