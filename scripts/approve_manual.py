#!/usr/bin/env python3
"""Validate a dual-gate post and mark it approved for manual Instagram publishing."""

from __future__ import annotations

import json
import os
import sys


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
POST_ID = os.environ.get("POST_ID", "").strip()


def load_json(path: str, default):
    try:
        with open(os.path.join(ROOT, path), encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, json.JSONDecodeError):
        return default


def save_json(path: str, data) -> None:
    with open(os.path.join(ROOT, path), "w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2, ensure_ascii=False)
        handle.write("\n")


def fail(message: str) -> int:
    print(f"REFUSED: {message}")
    return 1


def main() -> int:
    if not POST_ID:
        return fail("POST_ID is required")

    control = load_json("data/control.json", {"kill_switch": False})
    if control.get("kill_switch"):
        return fail("KILL SWITCH ON — approval handoff is disabled")

    approvals = load_json("data/approvals.json", {})
    if approvals.get(POST_ID) == "rejected":
        return fail("post was permanently rejected")

    calendar = load_json("content/calendar.json", {"days": []})
    post = next((item for item in calendar.get("days", []) if item.get("id") == POST_ID), None)
    if not post:
        return fail(f"unknown current-calendar post id: {POST_ID}")

    gate = load_json("data/gate_results.json", {"posts": {}}).get("posts", {}).get(POST_ID)
    if not gate:
        return fail("no quality-gate result exists")
    if not gate.get("pass") or int(gate.get("score", 0)) < 7:
        return fail("DeepSeek business gate did not pass at score >= 7")
    if not gate.get("visual_ok"):
        return fail("Gemini visual gate did not pass")

    approvals[POST_ID] = "approved_manual"
    save_json("data/approvals.json", approvals)
    print(f"APPROVED FOR MANUAL PUBLISH: {POST_ID}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
