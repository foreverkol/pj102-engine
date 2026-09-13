"""
v3.0 feishu_lint_alert.py - 飞书 webhook 告警

接收 lint_wiki.py 输出,如果有 critical issues 则发飞书通知。
支持 cron 定时调用 + 单次手动触发 + 模拟 dry_run。

飞书消息格式(参考 主理人家庭群消息分发模式):
  三段式:总览 / 详细 / 实用
"""

import json
import os
import sys
import urllib.request
import urllib.error
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional


CRITICAL_DIMENSIONS = {
    "3_missing_sources": "源引用缺失",
    "4_contradiction_pending": "矛盾待验证",
    "8_required_field_violations": "v7.0 §8.1 必填字段缺失",
}


def build_message(report: dict) -> dict:
    """构造飞书消息 payload"""
    summary = []
    detail = []

    for k, label in CRITICAL_DIMENSIONS.items():
        items = report.get(k, [])
        n = len(items) if isinstance(items, list) else 0
        if n > 0:
            summary.append(f"  ⚠️  {label}: {n} 处")

    # 详细列举(前 5 条)
    for k, label in CRITICAL_DIMENSIONS.items():
        items = report.get(k, [])
        if isinstance(items, list) and items:
            detail.append(f"\n【{label}】前 {min(5, len(items))} 条:")
            for item in items[:5]:
                detail.append(f"  - {item}")

    text = (
        "📋 **PJ-102 Wiki Lint 巡检报告**\n"
        f"时间: {datetime.now(timezone.utc).isoformat()}\n"
        f"\n【总览】\n"
        + ("\n".join(summary) if summary else "✅ 全部维度无 critical issues")
        + "\n\n【详细】\n"
        + ("\n".join(detail) if detail else "(无)")
        + "\n\n【实用】\n"
        "  → 自动触发:lady_incremental.sh 跑完后调用\n"
        "  → 手动:python3 feishu_lint_alert.py --test\n"
        "  → 关闭:set MINIMAX_LINT_ALERT=0"
    )
    return {
        "msg_type": "text",
        "content": {"text": text},
    }


def send_feishu(webhook_url: str, payload: dict,
                timeout: int = 10) -> tuple:
    """发飞书 webhook,返回 (success, response_text)"""
    try:
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            webhook_url,
            data=data,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return True, resp.read().decode("utf-8")
    except urllib.error.URLError as e:
        return False, f"URLError: {e}"
    except Exception as e:
        return False, f"Error: {e}"


def get_webhook_url() -> Optional[str]:
    """从环境变量或 secrets.d 拿 webhook URL"""
    # 1. 环境变量
    url = os.environ.get("FEISHU_WEBHOOK_URL", "")
    if url:
        return url
    # 2. secrets.d 文件
    for path in [
        Path.home() / ".pj102" / "secrets.d" / "feishu_webhook.txt",
        Path.home() / ".hermes" / "secrets.d" / "feishu_webhook.txt",
    ]:
        if path.exists():
            try:
                return path.read_text(encoding="utf-8").strip()
            except Exception:
                continue
    return None


def lint_alert(report: dict,
              webhook_url: Optional[str] = None,
              dry_run: bool = False) -> dict:
    """主入口:接收 lint report,决定是否发告警

    Returns: {sent: bool, payload: dict, error?: str}
    """
    payload = build_message(report)

    # 干跑模式
    if dry_run:
        return {"sent": False, "payload": payload, "mode": "dry_run"}

    # 环境变量关闭
    if os.environ.get("MINIMAX_LINT_ALERT") == "0":
        return {"sent": False, "payload": payload, "mode": "disabled"}

    # 无 webhook
    if not webhook_url:
        webhook_url = get_webhook_url()
    if not webhook_url:
        return {"sent": False, "payload": payload,
                "error": "FEISHU_WEBHOOK_URL not set"}

    success, response = send_feishu(webhook_url, payload)
    return {
        "sent": success,
        "payload": payload,
        "response": response if success else None,
        "error": None if success else response,
    }


# ============ CLI ============

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--webhook", help="飞书 webhook URL(否则读 env/secrets.d)")
    parser.add_argument("--dry-run", action="store_true",
                       help="只构造 payload,不实际发送")
    parser.add_argument("--test", action="store_true",
                       help="发一个测试消息(模拟 lint 输出)")
    parser.add_argument("--report", help="读 lint_wiki.py 输出 JSON 文件")
    args = parser.parse_args()

    if args.test:
        report = {
            "1_orphan_pages": ["Meeting/2026-08-02_xxx.md"],
            "3_missing_sources": ["Meeting/2026-08-03_yyy.md"],
            "4_contradiction_pending": [],
            "8_required_field_violations": [
                "meeting_zzz.md [meeting]: missing ['ldamc']",
            ],
        }
    elif args.report:
        report = json.loads(Path(args.report).read_text(encoding="utf-8"))
    else:
        # 默认 dry-run
        report = {"3_missing_sources": [], "8_required_field_violations": []}

    result = lint_alert(
        report,
        webhook_url=args.webhook,
        dry_run=args.dry_run,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
