"""单步 LLM 调用诊断: 只跑 S2(场景识别), 看真实 MiniMax-M3 响应"""
import os, sys, time

# 从 hermes .env 加载 key
# ⚠ 2026-09-16 修: `~` 字面量**不会被 open() 展开**，且原路径写成 `~//.hermes/.env`
#   在 pytest 收集阶段即 FileNotFoundError → 整个 tests/ 无法收集。
#   本文件是**人工诊断脚本**（非自动化测试），已移入 tests/_manual/ 不参与收集。
with open(os.path.join(os.path.expanduser("~"), ".hermes", ".env"),
          encoding="utf-8-sig") as f:
    for line in f:
        line = line.strip()
        if "=" in line and not line.startswith("#"):
            k, _, v = line.partition("=")
            k = k.strip(); v = v.strip().strip('"').strip("'")
            if k and k not in os.environ:
                os.environ[k] = v
os.environ.setdefault("MINIMAX_CN_BASE_URL", "https://api.minimaxi.com")
os.environ["DEBUG_LLM"] = "1"  # 开启 LLM debug

sys.path.insert(0, "F:/workbuddy/项目空间/PJ-102-02项目/03-执行/code")

from llm_client import LLMClient
from steps import s2_scene_recognition
from core import AppConfig

cfg = AppConfig()
cfg.paths.ensure_dirs()

# 读第一个样本
import json
index = json.loads(cfg.paths.data_index.read_text(encoding="utf-8"))
sample = index["samples"][0]
raw_file = cfg.paths.data_raw / sample["filename"]
content = raw_file.read_text(encoding="utf-8")
print(f"样本: {sample['filename']}")
print(f"内容长度: {len(content)} 字符")
print(f"key 前6位: {os.environ.get('MINIMAX_CN_API_KEY','')[:6]}")
print()

llm = LLMClient()
print(f"provider={llm.provider} model={llm.model}")
print("开始调用 S2(场景识别)...")
start = time.time()
try:
    s2 = s2_scene_recognition(content, llm)
    elapsed = time.time() - start
    print(f"\n✅ S2 完成 ({elapsed:.1f}s)")
    print(f"结果: {s2}")
except Exception as e:
    elapsed = time.time() - start
    print(f"\n❌ S2 失败 ({elapsed:.1f}s): {e}")
    import traceback
    traceback.print_exc()
