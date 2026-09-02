#!/usr/bin/env python3
"""Normalize AURA3 content disclosure to the Founder-approved exact text."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CALENDAR = ROOT / "content" / "calendar.json"
DISCLOSURE = "Inspiration reference"


def main() -> int:
    data = json.loads(CALENDAR.read_text(encoding="utf-8"))
    changed = 0
    for post in data.get("days", []):
        if post.get("disclosure") != DISCLOSURE:
            post["disclosure"] = DISCLOSURE
            changed += 1
    if changed:
        CALENDAR.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"disclosure": DISCLOSURE, "normalized_posts": changed}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
