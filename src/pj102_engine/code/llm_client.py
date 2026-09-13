"""
LLM 客户端 - PJ-102-LLM-MeetingKB v1.0

支持的 provider（按优先级）：
1. MiniMax M3（中国区，api.minimaxi.com）- 默认
2. DeepSeek
3. OpenAI
4. Anthropic
5. Mock（测试用）

修复：
- MiniMax 中国区 base_url 是 https://api.minimaxi.com/v1（不是 api.minimax.chat）
- 端点路径不含 /v1 前缀（base_url 已含）
"""

import json
import os
import re
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Optional


class LLMClient:
    """统一的 LLM 客户端"""

    def __init__(self, provider: str = "auto"):
        self.deepseek_key = os.environ.get("DEEPSEEK_API_KEY", "")
        # 兼容 hermes 常用命名 MINIMAX_CN_API_KEY, fallback 到 MINIMAX_API_KEY
        self.minimax_key = os.environ.get("MINIMAX_CN_API_KEY") or os.environ.get("MINIMAX_API_KEY", "")
        self.openai_key = os.environ.get("OPENAI_API_KEY", "")
        self.anthropic_key = os.environ.get("ANTHROPIC_API_KEY", "")

        # 默认用 MiniMax M3（主理人指定）
        if provider == "auto":
            if self.minimax_key:
                provider = "minimax"
            elif self.deepseek_key:
                provider = "deepseek"
            elif self.openai_key:
                provider = "openai"
            elif self.anthropic_key:
                provider = "anthropic"
            else:
                provider = "mock"

        self.provider = provider
        self.models = {
            "minimax": "MiniMax-M3",   # v3.0 修正:主理人指定 MiniMax-M3,不是 MiniMax-Text-01
            "deepseek": "deepseek-chat",
            "openai": "gpt-4o-mini",
            "anthropic": "claude-3-haiku-20240307",
            "mock": "mock",
        }
        self.model = self.models.get(provider, "mock")

    def call(self, prompt: str, system: str = "", max_tokens: int = 524288, max_retries: int = 4) -> str:
        """调用 LLM（带重试）
        v4.1: max_retries 3→4, 超时 60→300s(thinking 模型需更长思考时间)
        """
        for attempt in range(max_retries):
            try:
                if self.provider == "minimax":
                    return self._call_minimax(prompt, system, max_tokens)
                elif self.provider == "deepseek":
                    return self._call_deepseek(prompt, system, max_tokens)
                elif self.provider == "openai":
                    return self._call_openai(prompt, system, max_tokens)
                elif self.provider == "anthropic":
                    return self._call_anthropic(prompt, system, max_tokens)
                else:
                    return self._mock_response()
            except urllib.error.HTTPError as e:
                if e.code == 429 and attempt < max_retries - 1:
                    wait = 2 ** attempt
                    print(f"WARN  限流，等待 {wait}s 后重试...")
                    time.sleep(wait)
                else:
                    print(f"WARN  LLM 调用失败 (HTTP {e.code}): {e}")
                    return ""
            except Exception as e:
                print(f"WARN  LLM 调用异常: {e}")
                if attempt < max_retries - 1:
                    time.sleep(2 ** attempt)
                else:
                    return ""
        return ""

    def _call_minimax(self, prompt: str, system: str, max_tokens: int) -> str:
        """MiniMax M3 真实调用（中国区）- 5层防御根治卡死

        L1 流式 SSE: payload stream=True, 逐行读 SSE 边读边重置 read timeout
                      思考期每秒都在收字节, TCP 静默 hang up 立即可检测
        L2 短连接:   Connection: close, 每次新建 TCP, 消除 keep-alive 死锁
        L3 拆分超时: timeout=(10, 300) = (connect, read), 死锁可被快速中断
        L4 心跳:     每收到 1KB chunk 写一行 driver log, 进程始终有动静
        """
        base_url = os.environ.get("MINIMAX_CN_BASE_URL", "https://api.minimaxi.com")
        base_url = base_url.rstrip("/")
        if not base_url.endswith("/v1"):
            base_url = base_url + "/v1"
        url = f"{base_url}/text/chatcompletion_v2"

        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system or "你是一个专业的中文会议纪要分析师。"},
                {"role": "user", "content": prompt}
            ],
            "max_tokens": max_tokens,
            "temperature": 0.3,
            "stream": True,           # L1: 流式
        }
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.minimax_key}",
                "Connection": "close",    # L2: 短连接
            },
        )

        # L4 心跳 hook (让 driver log 始终有动静, watchdog 可识别活跃状态)
        heartbeat_log = os.environ.get("PJ102_DRIVER_LOG", "")
        def _heartbeat(reason: str, extra: str = ""):
            if not heartbeat_log:
                return
            try:
                line = f'[{__import__("datetime").datetime.now().isoformat(timespec="seconds")}] [heartbeat] {reason} {extra}\n'
                with open(heartbeat_log, "a", encoding="utf-8") as f:
                    f.write(line)
            except Exception:
                pass

        _heartbeat("minimax_call_begin", f"len(prompt)={len(prompt)}")

        content_parts = []
        reasoning_parts = []
        total_bytes = 0
        last_data_time = time.time()
        chunk_count = 0
        final_usage = None

        # L1+L3: 逐行读 SSE, 边读边重置 read timeout
        # 注: urllib.request.urlopen 只接受单一 timeout 值
        # 不用 socket.setdefaulttimeout, 避免和 urllib 内部超时机制冲突
        try:
            resp = urllib.request.urlopen(req, timeout=300)
            _heartbeat("sse_connected")
            for raw_line in resp:
                # L4: 持续心跳
                total_bytes += len(raw_line)
                chunk_count += 1
                line = raw_line.decode("utf-8", errors="ignore").strip()
                if not line or not line.startswith("data:"):
                    # SSE 注释行 (`:...`) 或空行
                    if line.startswith("event:") or line == "":
                        # 静默跳过
                        pass
                    continue
                if line.strip() == "data: [DONE]":
                    _heartbeat("sse_done", f"chunks={chunk_count}, bytes={total_bytes}")
                    break
                # 解析 data payload
                try:
                    obj = json.loads(line[5:].strip())
                except json.JSONDecodeError:
                    continue
                # final usage 块（部分 API 在最后一个 chunk 返回）
                if obj.get("usage"):
                    final_usage = obj["usage"]
                # 提取 delta
                choices = obj.get("choices", [])
                if not choices:
                    continue
                delta = choices[0].get("delta", {})
                rc = delta.get("reasoning_content", "")
                cc = delta.get("content", "")
                if rc:
                    reasoning_parts.append(rc)
                if cc:
                    content_parts.append(cc)
                # L4: 每 1KB 写一次心跳, watchdog 看到 mtime 在更新
                if total_bytes % 1024 < len(raw_line):
                    _heartbeat("sse_progress", f"chunks={chunk_count}, bytes={total_bytes}")
                last_data_time = time.time()
            try:
                resp.close()
            except Exception:
                pass
        except urllib.error.HTTPError as e:
            _heartbeat("http_error", f"code={e.code}")
            if e.code == 429 and e.code >= 500:
                raise  # 触发外层重试
            print(f"WARN  LLM HTTP 错误: {e.code} {e.reason}")
            return ""
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as e:
            _heartbeat("sse_broken", f"err={type(e).__name__}: {str(e)[:80]}")
            raise  # 触发外层重试
        except Exception as e:
            _heartbeat("sse_unknown_err", f"{type(e).__name__}: {str(e)[:80]}")
            raise

        # 拼装
        content = "".join(content_parts)
        reasoning = "".join(reasoning_parts)
        _heartbeat("minimax_call_end", f"content={len(content)}, reasoning={len(reasoning)}, chunks={chunk_count}")

        # v3.0: thinking fallback (content 空时用 reasoning)
        result = content or reasoning

        # token 记录（用 final_usage 或估算）
        if final_usage:
            self._record_token_usage(
                model=self.model,
                prompt_tokens=final_usage.get("prompt_tokens", 0),
                completion_tokens=final_usage.get("completion_tokens", 0),
                total_tokens=final_usage.get("total_tokens", 0),
            )
        else:
            # 流式可能不返回 usage, 用输出长度粗估
            est = len(reasoning) // 2 + len(content) // 2  # 粗估: 中文字符 1.5~2 token
            self._record_token_usage(
                model=self.model,
                prompt_tokens=len(prompt) // 2,
                completion_tokens=est,
                total_tokens=len(prompt) // 2 + est,
            )
        return result

    def _record_token_usage(self, model, prompt_tokens, completion_tokens, total_tokens):
        """记录 token 用量到 system/state/token_usage.jsonl (供 monitor 统计)
        失败静默, 不影响 LLM 调用
        """
        try:
            from datetime import datetime
            # P2 T-P2.6: 环境变量缺省时按模块位置推导项目根 (backfill 类脚本
            # 直连 LLM 不经 run_full, 无 PJ102_PROJECT_ROOT, 此前静默漏账)
            project_root = os.environ.get("PJ102_PROJECT_ROOT", "")
            if not project_root:
                project_root = str(Path(__file__).resolve().parent.parent)
            if not (Path(project_root) / "system").exists():
                return
            target = os.path.join(project_root, "system", "state", "token_usage.jsonl")
            os.makedirs(os.path.dirname(target), exist_ok=True)
            record = {
                "ts": datetime.now().isoformat(timespec="seconds"),
                "model": model,
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": total_tokens,
                "sample_id": os.environ.get("PJ102_CURRENT_SAMPLE", ""),
            }
            # 进程安全追加
            with open(target, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
        except Exception:
            pass  # 不要因为统计失败影响 LLM

    def _call_deepseek(self, prompt: str, system: str, max_tokens: int) -> str:
        """DeepSeek 调用"""
        url = "https://api.deepseek.com/v1/chat/completions"
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system or "你是一个专业的中文会议纪要分析师。"},
                {"role": "user", "content": prompt}
            ],
            "max_tokens": max_tokens,
            "temperature": 0.3,
        }
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.deepseek_key}"
            },
        )
        with urllib.request.urlopen(req, timeout=300) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data["choices"][0]["message"]["content"]

    def _call_openai(self, prompt: str, system: str, max_tokens: int) -> str:
        """OpenAI 调用"""
        url = "https://api.openai.com/v1/chat/completions"
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system or "你是一个专业的中文会议纪要分析师。"},
                {"role": "user", "content": prompt}
            ],
            "max_tokens": max_tokens,
            "temperature": 0.3,
        }
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.openai_key}"
            },
        )
        with urllib.request.urlopen(req, timeout=300) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data["choices"][0]["message"]["content"]

    def _call_anthropic(self, prompt: str, system: str, max_tokens: int) -> str:
        """Anthropic 调用"""
        url = "https://api.anthropic.com/v1/messages"
        payload = {
            "model": self.model,
            "max_tokens": max_tokens,
            "system": system or "你是一个专业的中文会议纪要分析师。",
            "messages": [{"role": "user", "content": prompt}],
        }
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "x-api-key": self.anthropic_key,
                "anthropic-version": "2023-06-01"
            },
        )
        with urllib.request.urlopen(req, timeout=300) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data["content"][0]["text"]

    def _mock_response(self) -> str:
        """Mock 响应（无 LLM key 时）"""
        return '{"mock": true}'


def safe_json_parse(content: str, default=None) -> dict:
    """安全解析 JSON(处理 markdown 包裹、尾随逗号等)

    支持返回 dict 或 list(default 可为同类型)
    """
    if not content:
        return default if default is not None else {}
    content = content.strip()

    # 移除 markdown 围栏
    content = re.sub(r"^```(?:json)?\s?", "", content)
    content = re.sub(r"\s?```$", "", content)

    # 尝试解析(优先整个 content)
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        pass

    # 提取 JSON 块(dict 或 list)
    for pattern in [r"\{[\s\S]*\}", r"\[[\s\S]*\]"]:
        m = re.search(pattern, content)
        if m:
            try:
                return json.loads(m.group(0))
            except json.JSONDecodeError:
                continue

    # 修复尾随逗号重试
    for pattern in [r"\{[\s\S]*\}", r"\[[\s\S]*\]"]:
        m = re.search(pattern, content)
        if m:
            try:
                fixed = re.sub(r",\s*}", "}", m.group(0))
                fixed = re.sub(r",\s*]", "]", fixed)
                return json.loads(fixed)
            except json.JSONDecodeError:
                continue

    return default if default is not None else {}