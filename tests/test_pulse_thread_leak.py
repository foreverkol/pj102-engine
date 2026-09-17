# -*- coding: utf-8 -*-
"""D-74 回归测试：脉冲线程在任何退出路径（含抛异常）都必须停止。

实证（2026-09-17 E1 复盘）：`_pulse_stop.set()` 原先只在成功路径末尾调用，
抛异常的样本使 daemon 线程**永久泄漏**，以 5s 周期继续写
``  [pulse n] <样本> alive t=NNNNs``。多个泄漏线程叠加后，日志呈现出
「多个样本同时在跑」的假象 —— 复盘时一度据此误判为**并发跑批**
（查证 `run_full` 无任何 Thread/Pool 才排除）。
本测试锁住修复：`finally` 兜底停止。
"""
import sys
import threading
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
# 兼容两种布局：实例仓 <root>/code · 引擎仓 <root>/src/pj102_engine/code
if not (ROOT / "code").exists() and (ROOT / "src" / "pj102_engine" / "code").exists():
    ROOT = ROOT / "src" / "pj102_engine"
sys.path.insert(0, str(ROOT / "code"))

import pipeline as P  # noqa: E402


def _cfg(tmp_path: Path):
    raw = tmp_path / "raw"
    raw.mkdir()
    (raw / "s.md").write_text("正文", encoding="utf-8")
    sysd = tmp_path / "sys"
    (sysd / "cache" / "steps").mkdir(parents=True)
    return types.SimpleNamespace(
        paths=types.SimpleNamespace(data_raw=raw, system_dir=sysd),
        version="test")


def _sample():
    return {"filename": "s.md", "content_hash": "deadbeef0000", "file_type": "transcript"}


def test_pulse_thread_stops_when_step_raises(monkeypatch, tmp_path):
    """★ 关键：s1 抛异常时线程也必须停止（原实现会泄漏）。"""
    base = len(threading.enumerate())

    def boom(*_a, **_k):
        raise RuntimeError("boom")

    monkeypatch.setattr(P, "s1_basic_info", boom)
    with pytest.raises(RuntimeError):
        P.process_one(_sample(), llm=None, cfg=_cfg(tmp_path), integrate=False)

    # 让 finally 有机会执行完
    for t in threading.enumerate():
        if t.daemon:
            t.join(timeout=0.2)
    assert len(threading.enumerate()) <= base, "脉冲线程泄漏（D-74 复发）"


def test_pulse_thread_stops_on_success(monkeypatch, tmp_path):
    """回归保护：成功路径线程同样收敛。"""
    base = len(threading.enumerate())
    monkeypatch.setattr(P, "s1_basic_info", lambda *a, **k: {"ok": 1})
    for name in ("s2_scene_recognition", "s3_standard_summary", "s4_fjv",
                 "s5_implicit_knowledge", "s6_entity_extraction",
                 "s7_action_decision", "s8_risk_blindspot",
                 "s9_knowledge_classify", "s10_cognitive_refine",
                 "s11_value_rating", "s13_financial_params", "s14_scenario"):
        if hasattr(P, name):
            monkeypatch.setattr(P, name, lambda *a, **k: {"stub": True})
    try:
        P.process_one(_sample(), llm=None, cfg=_cfg(tmp_path), integrate=False)
    except Exception:
        pass            # 下游（s15 等）不在本测试范围
    for t in threading.enumerate():
        if t.daemon:
            t.join(timeout=0.2)
    assert len(threading.enumerate()) <= base, "成功路径脉冲线程未收敛"
