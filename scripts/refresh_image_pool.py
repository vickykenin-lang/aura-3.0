#!/usr/bin/env python3
"""Refill AURA3's fresh visual pool from governed public-domain sources.

Fail-open contract: a source/network failure never blocks the existing AURA3
production path. The script only writes pool state after a successful Commons
query cycle or a local compaction/no-op decision.
"""

from __future__ import annotations

import html
import json
import re
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
IST = timezone(timedelta(hours=5, minutes=30))
CONFIG_PATH = ROOT / "data/image_sources.json"
POOL_PATH = ROOT / "data/image_pool.json"
LOG_PATH = ROOT / "data/image_acquisition_log.json"
CALENDAR_PATH = ROOT / "content/calendar.json"


def load_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def save_json(path: Path, value) -> None:
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


def strip_html(value: str) -> str:
    text = re.sub(r"<[^>]+>", " ", str(value or ""))
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


def meta_value(metadata: dict, key: str) -> str:
    entry = metadata.get(key) or {}
    if isinstance(entry, dict):
        return strip_html(entry.get("value", ""))
    return strip_html(entry)


def license_allowed(license_name: str, prefixes: list[str]) -> bool:
    normalized = re.sub(r"\s+", " ", license_name).strip().upper()
    return any(normalized.startswith(str(prefix).strip().upper()) for prefix in prefixes)


def commons_query(config: dict, search: dict) -> list[dict]:
    endpoint = str(config["endpoint"])
    params = {
        "action": "query",
        "format": "json",
        "formatversion": "2",
        "generator": "search",
        "gsrnamespace": "6",
        "gsrsearch": str(search["query"]),
        "gsrlimit": "25",
        "prop": "imageinfo",
        "iiprop": "url|mime|size|extmetadata",
        "iiurlwidth": "1600",
    }
    request = urllib.request.Request(
        endpoint + "?" + urllib.parse.urlencode(params),
        headers={"User-Agent": str(config.get("user_agent", "AURA3-VisualAcquisition/1.0"))},
    )
    timeout = int(config.get("timeout_seconds", 15))
    with urllib.request.urlopen(request, timeout=timeout) as response:
        payload = json.load(response)
    return list((payload.get("query") or {}).get("pages") or [])


def used_calendar_keys() -> set[str]:
    calendar = load_json(CALENDAR_PATH, {"days": []})
    return {
        image_key(str(post.get("image", "")))
        for post in calendar.get("days", [])
        if image_key(str(post.get("image", "")))
    }


def pool_item_from_page(config: dict, search: dict, page: dict) -> dict | None:
    infos = page.get("imageinfo") or []
    if not infos:
        return None
    info = infos[0]
    mime = str(info.get("mime", "")).lower()
    if mime not in {str(item).lower() for item in config.get("allowed_mime_types", [])}:
        return None

    width = int(info.get("width") or 0)
    height = int(info.get("height") or 0)
    if width < int(config.get("min_width", 900)) or height < int(config.get("min_height", 600)):
        return None

    metadata = info.get("extmetadata") or {}
    license_name = meta_value(metadata, "LicenseShortName") or meta_value(metadata, "UsageTerms")
    if not license_allowed(license_name, list(config.get("allowed_license_prefixes", []))):
        return None

    image_url = str(info.get("thumburl") or info.get("url") or "").strip()
    if not image_url.startswith("https://"):
        return None

    source_page = str(info.get("descriptionurl") or "").strip()
    license_url = meta_value(metadata, "LicenseUrl")
    author = meta_value(metadata, "Artist") or meta_value(metadata, "Credit") or "Wikimedia Commons contributor"
    title = str(page.get("title") or "").removeprefix("File:").strip()

    return {
        "photo_tag": str(search.get("photo_tag") or "commercial").strip(),
        "angle": str(search.get("angle") or search.get("query") or "commercial interior planning").strip(),
        "image": image_url,
        "source": "Wikimedia Commons",
        "source_page": source_page,
        "source_title": title,
        "license": license_name,
        "license_url": license_url,
        "author": author,
        "acquired_at": datetime.now(IST).isoformat(),
    }


def main() -> int:
    config = load_json(CONFIG_PATH, {})
    if not config.get("enabled"):
        print(json.dumps({"status": "VISUAL_ACQUISITION_DISABLED", "pool_changed": False}))
        return 0

    pool = load_json(POOL_PATH, [])
    if not isinstance(pool, list):
        pool = []

    used = used_calendar_keys()
    original_pool = list(pool)
    pool = [item for item in pool if image_key(str(item.get("image", ""))) not in used]

    log = load_json(LOG_PATH, {"schema_version": 1, "department_id": "aura3", "seen_image_keys": []})
    seen = {str(key) for key in log.get("seen_image_keys", []) if str(key)}
    seen.update(used)
    seen.update(image_key(str(item.get("image", ""))) for item in original_pool if image_key(str(item.get("image", ""))))

    target = int(config.get("target_fresh_pool_items", 80))
    max_pool = int(config.get("max_pool_items", 120))
    max_new = int(config.get("max_new_items_per_run", 30))

    if len(pool) >= target:
        if pool != original_pool:
            save_json(POOL_PATH, pool[:max_pool])
            log.update({
                "provider": config.get("provider"),
                "last_status": "POOL_COMPACTED_TARGET_ALREADY_MET",
                "last_acquired_count": 0,
                "fresh_pool_items": min(len(pool), max_pool),
                "observed_at": datetime.now(IST).isoformat(),
                "seen_image_keys": sorted(seen),
            })
            save_json(LOG_PATH, log)
        print(json.dumps({"status": "FRESH_POOL_TARGET_ALREADY_MET", "fresh_pool_items": len(pool)}))
        return 0

    acquired: list[dict] = []
    cycle_seen: set[str] = set()
    try:
        for search in config.get("search_terms", []):
            for page in commons_query(config, search):
                item = pool_item_from_page(config, search, page)
                if not item:
                    continue
                key = image_key(item["image"])
                if not key or key in seen or key in cycle_seen:
                    continue
                cycle_seen.add(key)
                acquired.append(item)
                if len(acquired) >= max_new or len(pool) + len(acquired) >= target:
                    break
            if len(acquired) >= max_new or len(pool) + len(acquired) >= target:
                break
    except Exception as error:
        print(json.dumps({
            "status": "VISUAL_SOURCE_UNAVAILABLE_FAIL_OPEN",
            "error_type": type(error).__name__,
            "existing_fresh_pool_items": len(pool),
            "production_blocked_by_acquisition_layer": False,
        }))
        return 0

    pool.extend(acquired)
    pool = pool[:max_pool]
    seen.update(image_key(item["image"]) for item in acquired)

    changed = pool != original_pool
    if changed:
        save_json(POOL_PATH, pool)
        log.update({
            "provider": config.get("provider"),
            "last_status": "POOL_REFRESHED" if acquired else "POOL_COMPACTED_NO_NEW_ITEMS",
            "last_acquired_count": len(acquired),
            "fresh_pool_items": len(pool),
            "observed_at": datetime.now(IST).isoformat(),
            "seen_image_keys": sorted(seen),
            "last_acquired": [
                {
                    "image": item["image"],
                    "source_page": item.get("source_page"),
                    "license": item.get("license"),
                    "photo_tag": item.get("photo_tag"),
                }
                for item in acquired
            ],
        })
        save_json(LOG_PATH, log)

    print(json.dumps({
        "status": "POOL_REFRESHED" if acquired else "NO_NEW_LICENSED_IMAGES_FOUND",
        "acquired": len(acquired),
        "fresh_pool_items": len(pool),
        "target": target,
        "production_blocked_by_acquisition_layer": False,
    }))
    return 0


if __name__ == "__main__":
    sys.exit(main())
