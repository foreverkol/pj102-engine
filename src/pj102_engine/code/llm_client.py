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
import sys
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

    # D-51: 单次 read 超时 / 单次 call 总时限（可由环境变量覆盖）
    REQ_TIMEOUT = int(os.environ.get("PJ102_LLM_TIMEOUT", "180"))
    TOTAL_TIMEOUT = int(os.environ.get("PJ102_LLM_TOTAL_TIMEOUT", "600"))

    def call(self, prompt: str, system: str = "", max_tokens: int = 524288, max_retries: int = 4) -> str:
        """调用 LLM（带重试）

        v4.1: max_retries 3→4, 超时 60→300s(thinking 模型需更长思考时间)
        D-51: 重试**全程可观测**。原实现在 `urlopen` 内阻塞期间**没有任何输出**，
          叠加 300s 单次超时 → 最长 20 分钟**静默黑洞**（补跑三轮均表现为
          "停在 s7、无 traceback、无 FAIL"；实测进程累计 CPU 仅 0.09s
          ⇒ 阻塞在 socket 等待而非计算，由此定性）。现在：
            · 每轮**开始前**写一行（attempt / prompt 长度 / 单次超时）
            · 每轮**结束**写一行（耗时 / 返回长度或异常类型）
            · `TOTAL_TIMEOUT` 兜底，超出立即放弃
        """
        t_all = time.time()
        for attempt in range(max_retries):
            t0 = time.time()
            print("[llm] attempt %d/%d provider=%s prompt=%d字 timeout=%ds 已用%.0fs"
                  % (attempt + 1, max_retries, self.provider, len(prompt),
                     self.REQ_TIMEOUT, time.time() - t_all), flush=True)
            if time.time() - t_all > self.TOTAL_TIMEOUT:
                print("[llm] 总时限 %ds 已到，放弃（已用 %.0fs）"
                      % (self.TOTAL_TIMEOUT, time.time() - t_all), flush=True)
                return ""
            try:
                if self.provider == "minimax":
                    r = self._call_minimax(prompt, system, max_tokens)
                elif self.provider == "deepseek":
                    r = self._call_deepseek(prompt, system, max_tokens)
                elif self.provider == "openai":
                    r = self._call_openai(prompt, system, max_tokens)
                elif self.provider == "anthropic":
                    r = self._call_anthropic(prompt, system, max_tokens)
                else:
                    r = self._mock_response()
                print("[llm] attempt %d 完成：返回 %d 字，耗时 %.0fs"
                      % (attempt + 1, len(r or ""), time.time() - t0), flush=True)
                # D-76 (2026-09-17): **空响应必须计为重试**。
                #   现象：SSE 建连成功、随即 0 字节结束 → 此处曾直接 return ""，
                #         被当作「成功」⇒ 不再重试。
                #   后果链：safe_json_parse("") 走兜底分支返回空结构 ⇒ 步骤产出
                #         「全字段空」⇒ pipeline.fuse_check 判 **soft 熔断拒落盘**
                #         ⇒ 表现为 lint_cache C1「某样本缺某步缓存」，同时页面缺该
                #         维度，且**全程只有一行无 WARN 的日志**，极易被误读为
                #         「该样本确无此维度产出」。
                #   实证（E1 10 样本 / 11 步缺口复核）：复跑 11 步有 **6 步**立刻
                #         返回真实内容（含 s7 决策链、s4 事实判断）⇒ 空响应是
                #         **传输层瞬时退化**，与超时同源，必须重试而非吞掉。
                if not (r or "").strip():
                    print("[llm] attempt %d 空响应(0 字) —— 计为重试，不返回"
                          % (attempt + 1), flush=True)
                    if attempt < max_retries - 1:
                        time.sleep(2 ** attempt)
                        continue
                    print("WARN  连续 %d 次空响应，放弃该调用（返回空串）"
                          % max_retries, flush=True)
                    return ""
                return r
            except urllib.error.HTTPError as e:
                print("[llm] attempt %d HTTPError %s（耗时 %.0fs）"
                      % (attempt + 1, e.code, time.time() - t0), flush=True)
                if e.code == 429 and attempt < max_retries - 1:
                    wait = 2 ** attempt
                    print(f"WARN  限流，等待 {wait}s 后重试...", flush=True)
                    time.sleep(wait)
                else:
                    print(f"WARN  LLM 调用失败 (HTTP {e.code}): {e}", flush=True)
                    return ""
            except Exception as e:
                print("[llm] attempt %d 异常 %s: %s（耗时 %.0fs）"
                      % (attempt + 1, type(e).__name__, e, time.time() - t0), flush=True)
                print(f"WARN  LLM 调用异常: {e}", flush=True)
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
            print("[llm] → POST %s（单值超时 %ds）"
                  % (getattr(req, "full_url", "?").split("?")[0], self.REQ_TIMEOUT), flush=True)
            resp = urllib.request.urlopen(req, timeout=self.REQ_TIMEOUT)
            _heartbeat("sse_connected")
            print("[llm] ← 已建连，开始读 SSE", flush=True)
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
                    # D-78 (2026-09-17): MiniMax 的**业务级错误以 HTTP 200 + SSE 返回**,
                    #   `choices` 为 null, 真实原因藏在 `base_resp` 里。实测原始报文:
                    #     {"choices":null,"input_sensitive":true,"input_sensitive_type":1,
                    #      "base_resp":{"status_code":1026,"status_msg":"input new_sensitive"}}
                    #   原实现此处直接 `continue` ⇒ **错误被静默吞掉**: 上层只看到
                    #   「返回 0 字」, 与真正的网络抖动无法区分 ⇒ 复核时误判为
                    #   「瞬时中断, 重跑即可」, 该样本的缺口从而长期无法定位。
                    #   现在显式抛出带 payload 的错误, 交给外层既有的重试/日志链路。
                    br = obj.get("base_resp") or {}
                    if br.get("status_code") not in (None, 0):
                        raise RuntimeError(
                            "LLM 服务端拒绝: base_resp.status_code=%s status_msg=%r "
                            "input_sensitive=%s output_sensitive=%s"
                            % (br.get("status_code"), br.get("status_msg"),
                               obj.get("input_sensitive"), obj.get("output_sensitive")))
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
            # D-78 附带修正: 原条件 `e.code == 429 and e.code >= 500` **恒假**
            #   (同一状态码不可能既是 429 又 ≥500) ⇒ 429 限流与 5xx 服务端错误
            #   从未触发外层重试, 一律被降级为「返回空串」, 与「模型返回空」
            #   混为一谈。改为 `or` 后行为与函数开头 docstring 声明一致。
            if e.code == 429 or e.code >= 500:
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
        with urllib.request.urlopen(req, timeout=self.REQ_TIMEOUT) as resp:
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
        with urllib.request.urlopen(req, timeout=self.REQ_TIMEOUT) as resp:
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
        with urllib.request.urlopen(req, timeout=self.REQ_TIMEOUT) as resp:
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

    # ★ 原先静默兜底 ⇒ 把「解析失败」伪装成「确无产出」：
    #   下游 fuse_check 见到「全字段空/占位」就软熔断不落盘，
    #   体检里表现为 C1/C2 永不清零（2026-09-16 实测 s7 返回 8180 字
    #   却全字段空）。必须让失败可见，否则永远查不到真因。
    sys.stderr.write(
        "[WARN] JSON 解析失败：len=%d，首段=%.160r —— 已返回兜底值；"
        "若该步随后被软熔断，应视为**解析失败**而非无产出\n"
        % (len(content), content[:160]))
    sys.stderr.flush()
    return default if default is not None else {}


def as_dict(parsed, default=None) -> dict:
    """把 `safe_json_parse` 的返回**归一为 dict**（按键访问前的前置动作）。

    背景（D-70，2026-09-16 实测）：`safe_json_parse` 在模型用**数组包裹**输出时会
    返回 `list`（其 docstring 明确「支持返回 dict 或 list」），而 s3/s6/s7/s9/s10
    随后按**键**写入（如 `parsed["quantitative_params"] = []`）⇒
    `TypeError: list indices must be integers or slices, not str`。
    实测仅在**最长样本**（41,148 字，全库最大）触发 —— 输出越长，模型越易退化成
    「数组包裹对象」形态。此缺陷会把一个纯解析/形态问题伪装成「该步异常」。

    归一规则：dict 原样 · list ⇒ 首个 dict 元素 · 其它 ⇒ default（dict）或 {}。

    ⚠ `s13`/`s14` **刻意不用本函数** —— 它们的设计就是「模型给裸数组 ⇒ 直接当
      items/scenarios 用」，归一为 dict 会抹掉该分支（见 s13 内注释）。
    """
    if isinstance(parsed, dict):
        return parsed
    if isinstance(parsed, list):
        for x in parsed:
            if isinstance(x, dict):
                return x
    return dict(default) if isinstance(default, dict) else {}


def safe_json_dict(content: str, default=None) -> dict:
    """`as_dict(safe_json_parse(...))` 的组合形式：解析 + 强制 dict 归一。

    步骤代码请用本函数取代裸 `safe_json_parse` —— **一处归一，五步受益**。
    """
    return as_dict(safe_json_parse(content, default), default)