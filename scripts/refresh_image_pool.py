#!/usr/bin/env python3
"""Refill AURA3's fresh visual pool from governed multi-source public-domain discovery.

Contracts:
- Source/network failure is fail-open for the existing production path.
- Only CC0/Public Domain candidates are admitted.
- Wikimedia Commons is primary; Openverse is a governed fallback discovery source.
- Canonical URL and perceptual-hash dedupe reduce repeated imagery.
- Actual-image DeepSeek/Nova validation remains authoritative for visual suitability.
"""

from __future__ import annotations

import hashlib
import html
import io
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


def search_key(search: dict) -> str:
    return str(search.get("query") or "").strip()


def source_list(config: dict) -> list[dict]:
    sources = list(config.get("sources") or [])
    if not sources:
        sources = [{
            "id": "wikimedia_commons",
            "type": "wikimedia_commons",
            "enabled": True,
            "priority": 1,
            "endpoint": config.get("endpoint", "https://commons.wikimedia.org/w/api.php"),
        }]
    return sorted(
        [item for item in sources if item.get("enabled", True)],
        key=lambda item: (int(item.get("priority", 100)), str(item.get("id", ""))),
    )


def commons_query(config: dict, search: dict, offset: int = 0, source: dict | None = None) -> tuple[list[dict], int, bool]:
    source = source or {}
    endpoint = str(source.get("endpoint") or config.get("endpoint") or "https://commons.wikimedia.org/w/api.php")
    page_size = max(1, min(50, int(source.get("page_size", config.get("search_page_size", 50)))))
    params = {
        "action": "query",
        "format": "json",
        "formatversion": "2",
        "generator": "search",
        "gsrnamespace": "6",
        "gsrsearch": str(search["query"]),
        "gsrlimit": str(page_size),
        "prop": "imageinfo",
        "iiprop": "url|mime|size|extmetadata",
        "iiurlwidth": "1600",
    }
    if offset > 0:
        params["gsroffset"] = str(offset)

    request = urllib.request.Request(
        endpoint + "?" + urllib.parse.urlencode(params),
        headers={"User-Agent": str(config.get("user_agent", "AURA3-VisualAcquisition/1.0"))},
    )
    timeout = int(source.get("timeout_seconds", config.get("timeout_seconds", 15)))
    with urllib.request.urlopen(request, timeout=timeout) as response:
        payload = json.load(response)

    pages = list((payload.get("query") or {}).get("pages") or [])
    continuation = payload.get("continue") or {}
    next_raw = continuation.get("gsroffset")
    if next_raw is not None:
        try:
            next_offset = max(offset + 1, int(next_raw))
            return pages, next_offset, True
        except (TypeError, ValueError):
            pass
    if len(pages) >= page_size:
        return pages, offset + page_size, True
    return pages, offset, False


def openverse_query(config: dict, search: dict, page: int = 1, source: dict | None = None) -> tuple[list[dict], int, bool]:
    source = source or {}
    endpoint = str(source.get("endpoint") or "https://api.openverse.org/v1/images/")
    page_size = max(1, min(80, int(source.get("page_size", config.get("search_page_size", 50)))))
    licenses = list(source.get("license_slugs") or ["cc0", "pdm"])
    params = {
        "q": str(search["query"]),
        "page": str(max(1, page)),
        "page_size": str(page_size),
        "license": ",".join(licenses),
        "mature": "false",
    }
    request = urllib.request.Request(
        endpoint + "?" + urllib.parse.urlencode(params),
        headers={"User-Agent": str(config.get("user_agent", "AURA3-VisualAcquisition/1.0"))},
    )
    timeout = int(source.get("timeout_seconds", config.get("timeout_seconds", 15)))
    with urllib.request.urlopen(request, timeout=timeout) as response:
        payload = json.load(response)
    results = list(payload.get("results") or [])
    current = int(payload.get("page") or page)
    page_count = int(payload.get("page_count") or current)
    return results, current + 1, current < page_count


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
        "dedupe_image": image_url,
        "source": "Wikimedia Commons",
        "source_page": source_page,
        "source_title": title,
        "source_identifier": f"wikimedia:{page.get('pageid') or title}",
        "license": license_name,
        "license_url": license_url,
        "author": author,
        "rights_basis": "SOURCE_METADATA_CC0_OR_PUBLIC_DOMAIN",
        "acquired_at": datetime.now(IST).isoformat(),
    }


def _mime_from_openverse(item: dict) -> str:
    filetype = str(item.get("filetype") or "").lower().strip(".")
    mapping = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png", "webp": "image/webp"}
    if filetype in mapping:
        return mapping[filetype]
    path = urlsplit(str(item.get("url") or "")).path.lower()
    for ext, mime in mapping.items():
        if path.endswith("." + ext):
            return mime
    return ""


def pool_item_from_openverse(config: dict, search: dict, item: dict, source: dict | None = None) -> dict | None:
    source = source or {}
    slug = str(item.get("license") or "").lower().strip()
    allowed_slugs = {str(x).lower() for x in source.get("license_slugs", ["cc0", "pdm"])}
    if slug not in allowed_slugs:
        return None

    mime = _mime_from_openverse(item)
    if mime not in {str(x).lower() for x in config.get("allowed_mime_types", [])}:
        return None

    try:
        width = int(item.get("width") or 0)
        height = int(item.get("height") or 0)
    except (TypeError, ValueError):
        return None
    if width < int(config.get("min_width", 900)) or height < int(config.get("min_height", 600)):
        return None

    image_url = str(item.get("url") or "").strip()
    landing = str(item.get("foreign_landing_url") or "").strip()
    if not image_url.startswith("https://") or not landing.startswith("http"):
        return None

    license_name = "CC0" if slug == "cc0" else "Public Domain"
    license_url = str(item.get("license_url") or "").strip()
    if slug == "cc0" and "creativecommons.org/publicdomain/zero" not in license_url:
        return None
    if slug == "pdm" and "creativecommons.org/publicdomain/mark" not in license_url:
        return None

    title = strip_html(item.get("title") or "")
    provider = str(item.get("provider") or item.get("source") or "Openverse").strip()
    identifier = str(item.get("id") or item.get("foreign_identifier") or "").strip()
    thumbnail = str(item.get("thumbnail") or image_url).strip()

    return {
        "photo_tag": str(search.get("photo_tag") or "commercial").strip(),
        "angle": str(search.get("angle") or search.get("query") or "commercial interior planning").strip(),
        "image": image_url,
        "dedupe_image": thumbnail if thumbnail.startswith("https://") else image_url,
        "source": f"Openverse/{provider}",
        "source_page": landing,
        "source_title": title,
        "source_identifier": f"openverse:{identifier or hashlib.sha256(landing.encode()).hexdigest()[:16]}",
        "license": license_name,
        "license_url": license_url,
        "author": str(item.get("creator") or "Openverse upstream contributor"),
        "rights_basis": "OPENVERSE_CC0_OR_PUBLIC_DOMAIN_METADATA_WITH_LICENSE_URL",
        "acquired_at": datetime.now(IST).isoformat(),
    }


def _dhash_bytes(raw: bytes) -> str | None:
    try:
        from PIL import Image
        with Image.open(io.BytesIO(raw)) as image:
            image = image.convert("L").resize((9, 8))
            pixels = list(image.getdata())
    except Exception:
        return None
    bits = []
    for row in range(8):
        base = row * 9
        for col in range(8):
            bits.append(1 if pixels[base + col] > pixels[base + col + 1] else 0)
    value = 0
    for bit in bits:
        value = (value << 1) | bit
    return f"{value:016x}"


def perceptual_hash_for_url(url: str, timeout: int = 10) -> str | None:
    if not str(url).startswith("https://"):
        return None
    request = urllib.request.Request(url, headers={"User-Agent": "AURA3-PerceptualDedupe/1.0"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read(8 * 1024 * 1024 + 1)
    except Exception:
        return None
    if not raw or len(raw) > 8 * 1024 * 1024:
        return None
    return _dhash_bytes(raw)


def hamming_distance(left: str, right: str) -> int:
    try:
        return (int(left, 16) ^ int(right, 16)).bit_count()
    except (TypeError, ValueError):
        return 999


def near_duplicate(phash: str, existing: set[str], threshold: int) -> bool:
    return any(hamming_distance(phash, prior) <= threshold for prior in existing)


def _progress_key(source_id: str, query: str) -> str:
    return f"{source_id}::{query}"


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

    raw_offsets = log.get("search_offsets") or {}
    search_offsets = {str(key): max(0, int(value or 0)) for key, value in raw_offsets.items() if str(key).strip()}
    original_offsets = dict(search_offsets)

    dedupe_cfg = config.get("perceptual_dedupe") or {}
    phash_enabled = bool(dedupe_cfg.get("enabled", True))
    phash_threshold = max(0, min(16, int(dedupe_cfg.get("max_hamming_distance", 4))))
    phash_download_limit = max(0, int(dedupe_cfg.get("max_hash_downloads_per_run", 50)))
    phash_timeout = max(2, int(dedupe_cfg.get("timeout_seconds", 10)))
    seen_phashes = {str(x) for x in log.get("seen_perceptual_hashes", []) if re.fullmatch(r"[0-9a-fA-F]{16}", str(x))}
    seen_phashes.update(
        str(item.get("perceptual_hash"))
        for item in original_pool
        if re.fullmatch(r"[0-9a-fA-F]{16}", str(item.get("perceptual_hash") or ""))
    )

    target = int(config.get("target_fresh_pool_items", 80))
    max_pool = int(config.get("max_pool_items", 120))
    max_new = int(config.get("max_new_items_per_run", 40))
    global_max_requests = max(1, int(config.get("max_search_requests_per_run", 32)))

    if len(pool) >= target:
        if pool != original_pool:
            save_json(POOL_PATH, pool[:max_pool])
        log.update({
            "provider": "MULTI_SOURCE_GOVERNED",
            "last_status": "POOL_COMPACTED_TARGET_ALREADY_MET" if pool != original_pool else "FRESH_POOL_TARGET_ALREADY_MET",
            "last_acquired_count": 0,
            "fresh_pool_items": min(len(pool), max_pool),
            "observed_at": datetime.now(IST).isoformat(),
            "seen_image_keys": sorted(seen),
            "seen_perceptual_hashes": sorted(seen_phashes),
            "search_offsets": search_offsets,
        })
        save_json(LOG_PATH, log)
        print(json.dumps({"status": "FRESH_POOL_TARGET_ALREADY_MET", "fresh_pool_items": len(pool)}))
        return 0

    acquired: list[dict] = []
    cycle_seen: set[str] = set()
    source_errors: list[dict] = []
    source_stats: dict[str, dict] = {}
    total_requests = 0
    successful_requests = 0
    phash_downloads = 0
    phash_duplicates = 0

    for source in source_list(config):
        if total_requests >= global_max_requests or len(acquired) >= max_new or len(pool) + len(acquired) >= target:
            break
        source_id = str(source.get("id") or source.get("type") or "source")
        source_type = str(source.get("type") or "").lower()
        per_source_max = max(1, int(source.get("max_requests_per_run", global_max_requests)))
        pages_per_search = max(1, int(source.get("max_pages_per_search", config.get("max_pages_per_search", 5))))
        stat = source_stats.setdefault(source_id, {"requests": 0, "successes": 0, "acquired": 0, "errors": 0})

        for search in config.get("search_terms", []):
            if total_requests >= global_max_requests or stat["requests"] >= per_source_max or len(acquired) >= max_new or len(pool) + len(acquired) >= target:
                break
            query = search_key(search)
            if not query:
                continue
            key = _progress_key(source_id, query)
            if source_type == "wikimedia_commons":
                position = int(search_offsets.get(key, search_offsets.get(query, 0)) or 0)
            else:
                position = max(1, int(search_offsets.get(key, 1) or 1))

            for _ in range(pages_per_search):
                if total_requests >= global_max_requests or stat["requests"] >= per_source_max:
                    break
                current = position
                total_requests += 1
                stat["requests"] += 1
                try:
                    if source_type == "wikimedia_commons":
                        rows, nxt, has_more = commons_query(config, search, current, source)
                    elif source_type == "openverse":
                        rows, nxt, has_more = openverse_query(config, search, current, source)
                    else:
                        raise ValueError(f"unsupported source type {source_type}")
                    successful_requests += 1
                    stat["successes"] += 1
                except Exception as error:
                    stat["errors"] += 1
                    source_errors.append({
                        "source": source_id,
                        "query": query,
                        "position": current,
                        "error_type": type(error).__name__,
                    })
                    break

                consumed_entire_page = True
                for row in rows:
                    item = (
                        pool_item_from_page(config, search, row)
                        if source_type == "wikimedia_commons"
                        else pool_item_from_openverse(config, search, row, source)
                    )
                    if not item:
                        continue
                    canonical = image_key(item["image"])
                    if not canonical or canonical in seen or canonical in cycle_seen:
                        continue

                    if phash_enabled and phash_downloads < phash_download_limit:
                        phash_downloads += 1
                        phash = perceptual_hash_for_url(str(item.get("dedupe_image") or item["image"]), phash_timeout)
                        if phash:
                            if near_duplicate(phash, seen_phashes, phash_threshold):
                                phash_duplicates += 1
                                continue
                            item["perceptual_hash"] = phash
                            seen_phashes.add(phash)

                    cycle_seen.add(canonical)
                    acquired.append(item)
                    stat["acquired"] += 1
                    if len(acquired) >= max_new or len(pool) + len(acquired) >= target:
                        consumed_entire_page = False
                        break

                if not consumed_entire_page:
                    search_offsets[key] = current
                    break
                if has_more:
                    position = max(current + 1, int(nxt))
                    search_offsets[key] = position
                else:
                    search_offsets[key] = 0 if source_type == "wikimedia_commons" else 1
                    break

    if successful_requests == 0 and source_errors:
        log.update({
            "provider": "MULTI_SOURCE_GOVERNED",
            "last_status": "ALL_VISUAL_SOURCES_UNAVAILABLE_FAIL_OPEN",
            "last_acquired_count": 0,
            "fresh_pool_items": len(pool),
            "observed_at": datetime.now(IST).isoformat(),
            "source_errors": source_errors,
            "source_stats": source_stats,
        })
        save_json(LOG_PATH, log)
        print(json.dumps({
            "status": "ALL_VISUAL_SOURCES_UNAVAILABLE_FAIL_OPEN",
            "source_requests": total_requests,
            "existing_fresh_pool_items": len(pool),
            "production_blocked_by_acquisition_layer": False,
        }))
        return 0

    pool.extend(acquired)
    pool = pool[:max_pool]
    seen.update(image_key(item["image"]) for item in acquired)

    pool_changed = pool != original_pool
    offsets_changed = search_offsets != original_offsets
    if pool_changed:
        save_json(POOL_PATH, pool)

    status = "POOL_REFRESHED_MULTI_SOURCE" if acquired else "NO_NEW_LICENSED_IMAGES_FOUND"
    if source_errors:
        status += "_WITH_PARTIAL_SOURCE_ERRORS"
    log.update({
        "schema_version": max(2, int(log.get("schema_version", 1) or 1)),
        "department_id": "aura3",
        "provider": "MULTI_SOURCE_GOVERNED",
        "last_status": status,
        "last_acquired_count": len(acquired),
        "fresh_pool_items": len(pool),
        "observed_at": datetime.now(IST).isoformat(),
        "seen_image_keys": sorted(seen),
        "seen_perceptual_hashes": sorted(seen_phashes),
        "search_offsets": search_offsets,
        "source_requests": total_requests,
        "successful_source_requests": successful_requests,
        "source_errors": source_errors,
        "source_stats": source_stats,
        "perceptual_hash_downloads": phash_downloads,
        "perceptual_duplicates_rejected": phash_duplicates,
        "last_acquired": [
            {
                "image": item["image"],
                "source": item.get("source"),
                "source_page": item.get("source_page"),
                "license": item.get("license"),
                "photo_tag": item.get("photo_tag"),
                "perceptual_hash": item.get("perceptual_hash"),
            }
            for item in acquired
        ],
    })
    if pool_changed or offsets_changed or successful_requests > 0:
        save_json(LOG_PATH, log)

    print(json.dumps({
        "status": status,
        "acquired": len(acquired),
        "fresh_pool_items": len(pool),
        "target": target,
        "search_offsets_advanced": offsets_changed,
        "source_requests": total_requests,
        "source_errors": len(source_errors),
        "source_stats": source_stats,
        "perceptual_duplicates_rejected": phash_duplicates,
        "production_blocked_by_acquisition_layer": False,
    }))
    return 0


if __name__ == "__main__":
    sys.exit(main())
