# -*- coding: utf-8 -*-
"""D-78 回归测试：服务端错误不得被**静默降级为空响应**。

三条独立缺陷（同族：服务端退化 → 空串 → 上层误判）：
  1. MiniMax 业务级错误走 **HTTP 200 + SSE**，`choices` 为 null，原因在
     `base_resp.status_code`（实测 1026 / "input new_sensitive"）。
     原实现 `if not choices: continue` ⇒ 完全静默 ⇒ 只看到「返回 0 字」。
  2. `e.code == 429 and e.code >= 500` **恒假** ⇒ 429/5xx 从不触发重试。
  3. 与 D-76（空响应不重试）叠加后，「服务端拒绝」与「瞬时抖动」在日志上
     完全无法区分 —— 这正是 E1 缓存缺口无法定位的根因。
"""
import sys
import urllib.error
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
# 兼容两种布局：实例仓 <root>/code · 引擎仓 <root>/src/pj102_engine/code
if not (ROOT / "code").exists() and (ROOT / "src" / "pj102_engine" / "code").exists():
    ROOT = ROOT / "src" / "pj102_engine"
sys.path.insert(0, str(ROOT / "code"))

import llm_client as L  # noqa: E402


class FakeResp:
    def __init__(self, lines):
        self._lines = [ln if isinstance(ln, bytes) else ln.encode("utf-8")
                       for ln in lines]

    def __iter__(self):
        return iter(self._lines)

    def close(self):
        pass


# 实测原始报文（2026-09-17 抓自 api.minimaxi.com）
REFUSAL = ('data: {"id":"06fabc44","choices":null,"model":"MiniMax-M3",'
           '"usage":{"total_tokens":0},"input_sensitive":true,'
           '"input_sensitive_type":1,"base_resp":'
           '{"status_code":1026,"status_msg":"input new_sensitive"}}')


def _client(monkeypatch, resp):
    monkeypatch.setattr(L.time, "sleep", lambda *_: None)
    monkeypatch.setattr(L.urllib.request, "urlopen",
                        lambda *a, **k: resp)
    c = L.LLMClient(provider="minimax")
    c.minimax_key = "test-key"
    return c


def test_base_resp_refusal_is_raised(monkeypatch):
    """★ 关键：服务端拒绝必须抛出并携带 status_code/msg，不得静默返回空串。"""
    c = _client(monkeypatch, FakeResp([REFUSAL, ""]))
    with pytest.raises(RuntimeError) as ei:
        c._call_minimax("p", "", 1024)
    m = str(ei.value)
    assert "1026" in m, "未透出 MiniMax 业务错误码"
    assert "input new_sensitive" in m, "未透出 status_msg"
    assert "input_sensitive=True" in m


def test_refusal_surfaces_through_call(monkeypatch):
    """经 call() 包装后：仍以空串交付（保持既有契约），但**日志必须可见**。"""
    lines = [REFUSAL, ""]
    monkeypatch.setattr(L.time, "sleep", lambda *_: None)
    monkeypatch.setattr(L.urllib.request, "urlopen", lambda *a, **k: FakeResp(lines))
    c = L.LLMClient(provider="minimax")
    c.minimax_key = "k"
    out = c.call("p", max_retries=2)
    assert out == ""            # 契约不变
    assert c.provider == "minimax"


def test_server_5xx_triggers_retry(monkeypatch):
    """5xx 必须向上抛出（触发重试），不得吞成空串。"""
    c = _client(monkeypatch, None)

    def boom(*a, **k):
        raise urllib.error.HTTPError("u", 503, "unavailable", None, None)

    monkeypatch.setattr(L.urllib.request, "urlopen", boom)
    with pytest.raises(urllib.error.HTTPError):
        c._call_minimax("p", "", 1024)


def test_rate_limit_429_triggers_retry(monkeypatch):
    """429 限流同样必须抛出（旧条件恒假，曾被吞掉）。"""
    c = _client(monkeypatch, None)

    def boom(*a, **k):
        raise urllib.error.HTTPError("u", 429, "too many", None, None)

    monkeypatch.setattr(L.urllib.request, "urlopen", boom)
    with pytest.raises(urllib.error.HTTPError):
        c._call_minimax("p", "", 1024)


def test_auth_error_401_still_returns_empty(monkeypatch):
    """回归保护：4xx 非限流仍立即失败返回空串（不重试、不抛）。"""
    c = _client(monkeypatch, None)

    def boom(*a, **k):
        raise urllib.error.HTTPError("u", 401, "unauth", None, None)

    monkeypatch.setattr(L.urllib.request, "urlopen", boom)
    assert c._call_minimax("p", "", 1024) == ""


def test_normal_stream_unaffected(monkeypatch):
    """回归保护：正常 SSE 流仍然正确拼出内容。"""
    good = ['data: {"choices":[{"delta":{"content":"你好"}}]}',
            'data: {"choices":[{"delta":{"content":"世界"}}]}',
            "data: [DONE]"]
    c = _client(monkeypatch, FakeResp(good))
    assert c._call_minimax("p", "", 1024) == "你好世界"
