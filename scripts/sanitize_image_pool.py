#!/usr/bin/env python3
"""Sanitize AURA3 visual pool before expensive model validation.

This is a metadata prefilter only. It removes obvious non-interior/historical junk,
blacklisted URLs and duplicates. It never replaces the strict model-based image gate.
"""
from __future__ import annotations

import json
import re
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
POOL_PATH = ROOT / "data/image_pool.json"
CONFIG_PATH = ROOT / "data/image_sources.json"
BLACKLIST_PATH = ROOT / "data/dead_image_blacklist.json"
HEALTH_PATH = ROOT / "data/image_pool_health.json"
IST = timezone(timedelta(hours=5, minutes=30))

DEFAULT_POSITIVE = [
    "office", "workspace", "workplace", "cowork", "conference", "meeting",
    "boardroom", "training room", "reception", "lobby", "hotel", "retail",
    "store", "commercial", "interior", "desk", "furniture", "room"
]
DEFAULT_NEGATIVE = [
    "department of the interior", "general land office", "territory of", "state of",
    "map", "atlas", "painting", "engraving", "illustration", "poster", "manuscript",
    "archive", "archival", "historic", "historical", "heritage", "museum object",
    "floor plan", "blueprint", "drawing", "plan of", "postcard", "lithograph"
]


def load(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def save(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def image_key(value: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    try:
        parsed = urlsplit(raw)
        host = (parsed.hostname or "").lower()
        path = parsed.path.rstrip("/")
        if host and path:
            return f"{host}{path}".lower()
    except ValueError:
        pass
    return raw.split("?", 1)[0].rstrip("/").lower()


def metadata_text(item: dict) -> str:
    values = [
        item.get("source_title", ""), item.get("source_page", ""), item.get("photo_tag", ""),
        item.get("angle", ""), item.get("author", "")
    ]
    return " ".join(str(v or "") for v in values).lower()


def reject_reason(item: dict, positive: list[str], negative: list[str]) -> str | None:
    text = metadata_text(item)
    for phrase in negative:
        if phrase and phrase.lower() in text:
            return "METADATA_NEGATIVE_SIGNAL"

    title = str(item.get("source_title", "")).lower()
    # Old dates are only a hard metadata reject when the title also reads like a document/artifact.
    if re.search(r"\b(?:18\d{2}|19[0-4]\d)\b", title) and any(
        word in title for word in ("map", "office", "room", "building", "interior", "reception", "post office", "government")
    ):
        return "OBVIOUS_HISTORICAL_TITLE"

    if not any(token.lower() in text for token in positive if token):
        return "NO_INTERIOR_SEMANTIC_SIGNAL"
    return None


def main() -> int:
    pool = load(POOL_PATH, [])
    if not isinstance(pool, list):
        pool = []
    config = load(CONFIG_PATH, {})
    rules = config.get("metadata_prefilter") or {}
    positive = list(rules.get("positive_tokens") or DEFAULT_POSITIVE)
    negative = list(rules.get("negative_tokens") or DEFAULT_NEGATIVE)
    blacklist = load(BLACKLIST_PATH, {"images": {}})
    blocked = set((blacklist.get("images") or {}).keys())

    kept = []
    seen = set()
    reasons = Counter()
    examples = []

    for item in pool:
        if not isinstance(item, dict):
            reasons["INVALID_POOL_ITEM"] += 1
            continue
        key = image_key(item.get("image", ""))
        if not key:
            reasons["MISSING_IMAGE_URL"] += 1
            continue
        if key in seen:
            reasons["DUPLICATE_IMAGE"] += 1
            continue
        seen.add(key)
        if key in blocked:
            reasons["PERSISTENT_BLACKLIST"] += 1
            continue
        reason = reject_reason(item, positive, negative)
        if reason:
            reasons[reason] += 1
            if len(examples) < 12:
                examples.append({"reason": reason, "title": item.get("source_title", ""), "image": item.get("image", "")})
            continue
        kept.append(item)

    max_pool = max(20, int(config.get("max_pool_items", 120)))
    kept = kept[:max_pool]
    save(POOL_PATH, kept)
    health = {
        "schema_version": 1,
        "department_id": "aura3",
        "status": "HEALTHY" if len(kept) >= 25 else "LOW_ELIGIBLE_POOL",
        "before": len(pool),
        "eligible_after": len(kept),
        "removed": max(0, len(pool) - len(kept)),
        "removed_by_reason": dict(sorted(reasons.items())),
        "sample_rejections": examples,
        "minimum_desired_eligible": 25,
        "observed_at": datetime.now(IST).isoformat(),
        "truth_note": "Metadata prefilter reduces obvious junk only. Every retained image still requires strict actual-image AI validation before Founder approval."
    }
    save(HEALTH_PATH, health)
    print(json.dumps(health, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
