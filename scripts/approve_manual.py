#!/usr/bin/env python3
"""Validate a dual-gate post and mark it approved for Instagram publishing."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from datetime import datetime, timezone

sys.path.insert(0, str(Path(__file__).resolve().parent))
import release_guard


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

    control = load_json("data/control.json", {"kill_switch": True})
    if control.get("kill_switch"):
        return fail("KILL SWITCH ON — approval handoff is disabled")
    try:
        if release_guard.load(ROOT, "state/control.json").get("kill_switch") is not False:
            return fail("canonical kill switch blocks approval handoff")
    except release_guard.ReleaseRefused:
        return fail("canonical control record is missing")

    approvals = load_json("data/approvals.json", {})
    if approvals.get(POST_ID) == "rejected":
        return fail("post was permanently rejected")

    calendar = load_json("content/calendar.json", {"days": []})
    post = next((item for item in calendar.get("days", []) if item.get("id") == POST_ID), None)
    if not post:
        return fail(f"unknown current-calendar post id: {POST_ID}")

    gate_results = load_json("data/gate_results.json", {"posts": {}})
    if not gate_results.get("batch_complete"):
        return fail("latest dual-gate batch is incomplete")

    gate = gate_results.get("posts", {}).get(POST_ID)
    if not gate:
        return fail("no quality-gate result exists")
    if not gate.get("pass") or int(gate.get("score", 0)) < 7:
        return fail("DeepSeek business gate did not pass at score >= 7")
    if not gate.get("visual_ok"):
        return fail("independent visual gate did not pass")

    try:
        manifest = release_guard.qualified_manifest(post, gate_results, ROOT)
        digest = release_guard.sha(manifest)
        if os.environ.get("APPROVED_MANIFEST_SHA256", "").strip() != digest:
            return fail("Founder approval must identify the exact dashboard content manifest")
        release_guard.verify_source(manifest)
    except (release_guard.ReleaseRefused, TypeError, ValueError):
        return fail("content-bound QA or source-image verification refused")
    records = load_json("data/approval_manifests.json", {})
    records[POST_ID] = {"manifest": manifest, "manifest_sha256": digest, "approved_at": datetime.now(timezone.utc).isoformat(), "founder_actor": os.environ.get("GITHUB_ACTOR", ""), "approval_run_id": os.environ.get("GITHUB_RUN_ID", "")}
    save_json("data/approval_manifests.json", records)

    approvals[POST_ID] = "approved_manual"
    save_json("data/approvals.json", approvals)
    print(f"APPROVED FOR INSTAGRAM PUBLISH: {POST_ID}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
