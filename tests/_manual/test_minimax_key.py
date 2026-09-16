"""MiniMax key + base_url 最小化验证测试
尝试 3 种 base_url 组合，找到能调通 MiniMax-M3 的那个
"""
import json
import os
import sys
import urllib.request
import urllib.error

# 读取 key: 优先环境变量, 其次当前目录/用户主目录的 .env
from pathlib import Path

key = os.environ.get("MINIMAX_CN_API_KEY", "").strip()
if not key:
    for env_file in [Path(".env"), Path.home() / ".hermes" / ".env"]:
        if not env_file.exists():
            continue
        with open(env_file, encoding="utf-8-sig") as f:
            for line in f:
                line = line.strip()
                if line.startswith("MINIMAX_CN_API_KEY="):
                    key = line.split("=", 1)[1].strip().strip('"').strip("'")
                    break
        if key:
            break
if not key:
    print("未找到 MINIMAX_CN_API_KEY (环境变量或 .env)")
    sys.exit(1)

print(f"key 前6位: {key[:6]}... 长度: {len(key)}")

# 3 种候选 base_url
candidates = [
    ("api.minimaxi.com/v1", "https://api.minimaxi.com/v1/text/chatcompletion_v2"),
    ("api.minimax.chat/v1", "https://api.minimax.chat/v1/text/chatcompletion_v2"),
    ("api.minimaxi.com(无v1)", "https://api.minimaxi.com/text/chatcompletion_v2"),
]

payload = {
    "model": "MiniMax-M3",
    "messages": [
        {"role": "system", "content": "你是测试助手"},
        {"role": "user", "content": "回复两个字: 测试成功"}
    ],
    "max_tokens": 100,
    "temperature": 0.3,
}

for name, url in candidates:
    print(f"\n=== 尝试 {name} ===")
    print(f"  URL: {url}")
    try:
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {key}",
            },
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            msg = data.get("choices", [{}])[0].get("message", {})
            content = msg.get("content", "") or msg.get("reasoning_content", "")
            print(f"  ✅ 成功! content={content[:50]!r}")
            print(f"  model={data.get('model')}, usage={data.get('usage', {})}")
            print(f"  >>> 胜出 base_url: {name}")
            break
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")[:300]
        print(f"  ❌ HTTP {e.code}: {body}")
    except Exception as e:
        print(f"  ❌ 异常: {e}")
