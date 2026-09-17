# -*- coding: utf-8 -*-
"""D-76 回归测试：LLM **空响应**必须计为重试，不得当作成功返回。

为什么重要（失效链，2026-09-17 实证）：
    SSE 建连成功 → 0 字节结束 → ``call()`` 曾直接 ``return ""`` 视为成功
    → ``safe_json_parse("")`` 走兜底返回**空结构**
    → ``pipeline.fuse_check`` 判 **soft 熔断「不落盘」**
    → 表象只有「lint_cache C1: 某样本缺某步缓存」，
      **没有任何 WARN**，极易被误读为「该样本确无此维度产出」。
    E1 复核：11 处缺口复跑有 6 处立刻返回真实内容 ⇒ 空响应是**瞬时传输退化**
    （与超时同源），必须重试。
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# 兼容两种布局：实例仓 <root>/code · 引擎仓 <root>/src/pj102_engine/code
if not (ROOT / "code").exists() and (ROOT / "src" / "pj102_engine" / "code").exists():
    ROOT = ROOT / "src" / "pj102_engine"
sys.path.insert(0, str(ROOT / "code"))

import llm_client as L  # noqa: E402


def _client(monkeypatch, responses):
    """构造 minimax 客户端，并让底层调用按 responses 顺序返回。"""
    monkeypatch.setattr(L.time, "sleep", lambda *_: None)   # 免等退避
    c = L.LLMClient(provider="minimax")
    seq = iter(responses)
    calls = {"n": 0}

    def fake(*_a, **_k):
        calls["n"] += 1
        return next(seq, "")

    monkeypatch.setattr(c, "_call_minimax", fake)
    return c, calls


def test_empty_response_is_retried(monkeypatch):
    """前两次空 → 第三次有内容 ⇒ 必须重试并返回内容。"""
    c, calls = _client(monkeypatch, ["", "   ", "真实内容"])
    out = c.call("prompt", max_retries=4)
    assert out == "真实内容", "空响应未被重试 → D-76 复发"
    assert calls["n"] == 3


def test_all_empty_gives_up_after_max_retries(monkeypatch):
    """连续空响应 ⇒ 用尽重试后返回空串（不得死循环）。"""
    c, calls = _client(monkeypatch, ["", "", ""])
    out = c.call("prompt", max_retries=3)
    assert out == ""
    assert calls["n"] == 3


def test_nonempty_first_try_returns_immediately(monkeypatch):
    """回归保护：正常响应不得被额外重试（保持幂等与成本可控）。"""
    c, calls = _client(monkeypatch, ["正常内容"])
    out = c.call("prompt", max_retries=4)
    assert out == "正常内容"
    assert calls["n"] == 1


def test_http_error_non_429_still_returns_empty(monkeypatch):
    """回归保护：非 429 的 HTTPError 行为不变（立即失败，不重试）。"""
    import urllib.error
    monkeypatch.setattr(L.time, "sleep", lambda *_: None)
    c = L.LLMClient(provider="minimax")
    calls = {"n": 0}

    def fake(*_a, **_k):
        calls["n"] += 1
        raise urllib.error.HTTPError("u", 401, "unauth", None, None)

    monkeypatch.setattr(c, "_call_minimax", fake)
    assert c.call("prompt", max_retries=4) == ""
    assert calls["n"] == 1
