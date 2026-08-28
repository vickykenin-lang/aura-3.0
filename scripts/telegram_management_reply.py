#!/usr/bin/env python3
"""Send a verified AURA3 transport result to the Telegram management group."""

import json
import os
import sys
import urllib.parse
import urllib.request


def build_reply(result):
    strict = result.get("strict_supervision") or {}
    evidence = strict.get("evidence") or []
    return "\n".join(
        [
            "AURA3 management-group revert",
            f"Status: {strict.get('status') or result.get('execution_status') or 'UNKNOWN'}",
            f"Objective alignment: {strict.get('objective_alignment') or 'UNKNOWN'}",
            f"Solution: {strict.get('solution') or 'NOT_PROVIDED'}",
            f"Next action: {strict.get('next_action') or 'NOT_PROVIDED'}",
            f"Evidence: {', '.join(str(item) for item in evidence[:3]) or 'not provided'}",
            f"Task ID: {result.get('task_id') or 'UNKNOWN'}",
        ]
    )


def main():
    token = (os.environ.get("TELEGRAM_BOT_TOKEN_AURA3") or "").strip()
    chat_id = (os.environ.get("TELEGRAM_MANAGEMENT_CHAT_ID") or "").strip()
    task_id = (os.environ.get("VICTOR_TASK_ID") or "").strip()
    if not token or not chat_id or not task_id:
        print("[aura3-management-reply] BLOCKED: Telegram binding or task ID missing")
        return 2
    with open("integration/results/latest.json", encoding="utf-8") as handle:
        result = json.load(handle)
    if result.get("task_id") != task_id or result.get("sender") != "aura3":
        print("[aura3-management-reply] BLOCKED: unverified AURA3 result envelope")
        return 3
    payload = urllib.parse.urlencode(
        {"chat_id": chat_id, "text": build_reply(result), "disable_web_page_preview": "true"}
    ).encode()
    request = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/sendMessage", data=payload, method="POST"
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        body = json.load(response)
    if not body.get("ok"):
        print("[aura3-management-reply] Telegram API rejected message")
        return 1
    print("[aura3-management-reply] message sent")
    return 0


if __name__ == "__main__":
    sys.exit(main())
