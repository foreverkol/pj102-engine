"""pj102 engine · query launcher v1.0

从 hermes .env 加载 MiniMax key, 然后跑查询
指向本项目 code/, L2 真实读取本项目 wiki/ 内容

用法:
  python scripts/run_query.py --query "本项目进展"
  python scripts/run_query.py --query "黄国华是谁"
  python scripts/run_query.py --query "总结供应链金融" -v
"""
import os
import sys

# 1. 从 hermes .env 加载 key
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

# 2. 确保 base_url 正确
os.environ.setdefault("MINIMAX_CN_BASE_URL", "https://api.minimaxi.com")

# 3. 加入 PYTHONPATH(本项目 code/)
PROJECT_ROOT = os.environ.get("PJ102_PROJECT_ROOT") or os.getcwd()
CODE_DIR = os.path.join(PROJECT_ROOT, "code")
sys.path.insert(0, CODE_DIR)

# 4. 透传 CLI 给 kb_retriever.main()
sys.argv = ["kb_retriever.py"] + sys.argv[1:]
from kb_retriever import main
sys.exit(main())
