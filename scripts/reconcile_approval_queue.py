#!/usr/bin/env python3
"""Keep AURA3 calendar/gate state consistent after a partial queue refill."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DISCLOSURE = "Inspiration reference"


def load(path: str, default):
    try:
        return json.loads((ROOT / path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def save(path: str, data) -> None:
    (ROOT / path).write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def main() -> int:
    calendar = load("content/calendar.json", {"days": []})
    approvals = load("data/approvals.json", {})
    published = load("content/published.json", {})
    gates = load("data/gate_results.json", {"posts": {}})
    gate_posts = gates.setdefault("posts", {})

    kept = []
    removed = []
    for post in calendar.get("days", []):
        post_id = str(post.get("id", ""))
        post["disclosure"] = DISCLOSURE
        state = str(approvals.get(post_id, "pending") or "pending").lower()
        is_published = post_id in published
        if post_id and post_id not in gate_posts and state == "pending" and not is_published:
            removed.append(post_id)
            continue
        kept.append(post)
    calendar["days"] = kept
    gates["batch_complete"] = all(str(p.get("id", "")) in gate_posts for p in kept if p.get("id"))

    save("content/calendar.json", calendar)
    save("data/gate_results.json", gates)
    print(json.dumps({"removed_ungated_pending_posts": removed, "batch_complete": gates["batch_complete"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
