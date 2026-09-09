#!/usr/bin/env python3
"""AURA3 governed stock-image acquisition.

Active sources are Pexels, Pixabay and Unsplash only. This layer discovers legal
stock candidates and preserves source/license metadata. It does not approve or
publish content; canonical/perceptual dedupe plus actual-image DeepSeek/Nova
validation remain mandatory downstream gates.
"""
from __future__ import annotations

import importlib.util
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

_CORE_PATH = Path(__file__).with_name("refresh_image_pool_core.py")
_SPEC = importlib.util.spec_from_file_location("refresh_image_pool_core", _CORE_PATH)
if _SPEC is None or _SPEC.loader is None:
    raise ImportError(f"Unable to load acquisition core from {_CORE_PATH}")
core = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(core)
for _name in dir(core):
    if not _name.startswith("__"):
        globals().setdefault(_name, getattr(core, _name))

RETRYABLE_HTTP = {408, 425, 429, 500, 502, 503, 504}
ACTIVE_SOURCE_NAMES = {"Pexels", "Pixabay", "Unsplash"}


def _credential(source: dict) -> str:
    return str(os.getenv(str(source.get("credential_env") or "")) or "").strip()


def _retry_delay(error: urllib.error.HTTPError, attempt: int) -> float:
    raw = ""
    try:
        raw = str(error.headers.get("Retry-After") or "").strip()
    except Exception:
        pass
    try:
        retry_after = float(raw)
    except (TypeError, ValueError):
        retry_after = 0.0
    return min(8.0, max(retry_after, 0.75 * (2 ** attempt)))


def _json_request(url: str, headers: dict[str, str], timeout: int, *, source: str, attempts: int = 3) -> dict:
    last: Exception | None = None
    for attempt in range(max(1, attempts)):
        request = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return json.load(response)
        except urllib.error.HTTPError as error:
            last = error
            code = int(getattr(error, "code", 0) or 0)
            print(json.dumps({"image_source_http_warning": source, "http_status": code, "attempt": attempt + 1, "retryable": code in RETRYABLE_HTTP}))
            if code not in RETRYABLE_HTTP or attempt + 1 >= attempts:
                raise
            time.sleep(_retry_delay(error, attempt))
        except (TimeoutError, urllib.error.URLError) as error:
            last = error
            if attempt + 1 >= attempts:
                raise
            time.sleep(min(6.0, 0.75 * (2 ** attempt)))
    raise last or RuntimeError("stock source request exhausted retries")


def _base_headers(config: dict) -> dict[str, str]:
    return {
        "User-Agent": str(config.get("user_agent", "AURA3-VisualAcquisition/9.0")),
        "Accept": "application/json",
        "Accept-Encoding": "identity",
    }


def _query_source(config: dict, source: dict, search: dict, page: int) -> tuple[list[dict], bool]:
    source_id = str(source.get("id") or "").lower()
    key = _credential(source)
    if not key:
        raise RuntimeError("SOURCE_CREDENTIAL_MISSING")
    endpoint = str(source.get("endpoint") or "")
    per_page = max(1, min(80, int(source.get("page_size", 30))))
    timeout = int(source.get("timeout_seconds", config.get("timeout_seconds", 15)))
    attempts = max(1, int(source.get("http_retry_attempts", 3)))
    headers = _base_headers(config)

    if source_id == "pexels":
        headers["Authorization"] = key
        params = {"query": str(search["query"]), "page": str(page), "per_page": str(min(per_page, 80)), "orientation": "landscape"}
        payload = _json_request(endpoint + "?" + urllib.parse.urlencode(params), headers, timeout, source=source_id, attempts=attempts)
        rows = list(payload.get("photos") or [])
        return rows, bool(payload.get("next_page"))

    if source_id == "pixabay":
        params = {
            "key": key,
            "q": str(search["query"]),
            "page": str(page),
            "per_page": str(min(max(3, per_page), 200)),
            "image_type": "photo",
            "orientation": "horizontal",
            "safesearch": "true",
            "order": "popular",
        }
        payload = _json_request(endpoint + "?" + urllib.parse.urlencode(params), headers, timeout, source=source_id, attempts=attempts)
        rows = list(payload.get("hits") or [])
        total = int(payload.get("totalHits") or 0)
        return rows, page * int(params["per_page"]) < total

    if source_id == "unsplash":
        headers["Authorization"] = f"Client-ID {key}"
        params = {"query": str(search["query"]), "page": str(page), "per_page": str(min(per_page, 30)), "orientation": "landscape", "content_filter": "high"}
        payload = _json_request(endpoint + "?" + urllib.parse.urlencode(params), headers, timeout, source=source_id, attempts=attempts)
        rows = list(payload.get("results") or [])
        return rows, page < int(payload.get("total_pages") or page)

    raise ValueError(f"unsupported stock source: {source_id}")


def _metadata_relevant(config: dict, text: str) -> bool:
    rules = config.get("metadata_prefilter") or {}
    value = str(text or "").lower()
    negatives = [str(x).lower() for x in rules.get("negative_tokens", []) if str(x).strip()]
    positives = [str(x).lower() for x in rules.get("positive_tokens", []) if str(x).strip()]
    if any(token in value for token in negatives):
        return False
    return not positives or any(token in value for token in positives)


def _dimensions_ok(config: dict, width, height) -> bool:
    try:
        return int(width or 0) >= int(config.get("min_width", 1200)) and int(height or 0) >= int(config.get("min_height", 800))
    except (TypeError, ValueError):
        return False


def _stock_item(config: dict, source: dict, search: dict, row: dict) -> dict | None:
    source_id = str(source.get("id") or "").lower()
    license_name = str(source.get("license") or "").strip()
    license_url = str(source.get("license_url") or "").strip()
    allowed = {str(x) for x in config.get("allowed_source_licenses", [])}
    if not license_name or license_name not in allowed or not license_url.startswith("https://"):
        return None

    if source_id == "pexels":
        if not _dimensions_ok(config, row.get("width"), row.get("height")):
            return None
        src = row.get("src") or {}
        image = str(src.get("large2x") or src.get("large") or src.get("original") or "").strip()
        dedupe = str(src.get("medium") or image).strip()
        landing = str(row.get("url") or "").strip()
        title = str(row.get("alt") or search.get("query") or "").strip()
        author = str(row.get("photographer") or "Pexels contributor").strip()
        identifier = str(row.get("id") or "").strip()
        metadata = " ".join([title, str(search.get("query") or ""), str(search.get("photo_tag") or "")])
        source_name = "Pexels"

    elif source_id == "pixabay":
        if not _dimensions_ok(config, row.get("imageWidth"), row.get("imageHeight")):
            return None
        image = str(row.get("largeImageURL") or row.get("webformatURL") or "").strip()
        dedupe = str(row.get("previewURL") or row.get("webformatURL") or image).strip()
        landing = str(row.get("pageURL") or "").strip()
        title = str(row.get("tags") or search.get("query") or "").strip()
        author = str(row.get("user") or "Pixabay contributor").strip()
        identifier = str(row.get("id") or "").strip()
        metadata = " ".join([title, str(search.get("query") or ""), str(search.get("photo_tag") or "")])
        source_name = "Pixabay"

    elif source_id == "unsplash":
        if not _dimensions_ok(config, row.get("width"), row.get("height")):
            return None
        urls = row.get("urls") or {}
        raw = str(urls.get("raw") or urls.get("full") or urls.get("regular") or "").strip()
        if raw.startswith("https://") and "images.unsplash.com" in raw:
            separator = "&" if "?" in raw else "?"
            image = raw + separator + "w=1600&fit=max&q=85&fm=jpg"
        else:
            image = raw
        dedupe = str(urls.get("small") or urls.get("thumb") or image).strip()
        landing = str((row.get("links") or {}).get("html") or "").strip()
        title = str(row.get("alt_description") or row.get("description") or search.get("query") or "").strip()
        user = row.get("user") or {}
        author = str(user.get("name") or user.get("username") or "Unsplash contributor").strip()
        identifier = str(row.get("id") or "").strip()
        metadata = " ".join([title, str(search.get("query") or ""), str(search.get("photo_tag") or "")])
        source_name = "Unsplash"

    else:
        return None

    if not image.startswith("https://") or not landing.startswith("https://"):
        return None
    if not _metadata_relevant(config, metadata):
        return None

    return {
        "photo_tag": str(search.get("photo_tag") or "commercial").strip(),
        "angle": str(search.get("angle") or search.get("query") or "commercial interior planning").strip(),
        "image": image,
        "dedupe_image": dedupe if dedupe.startswith("https://") else image,
        "source": source_name,
        "source_page": landing,
        "source_title": title,
        "source_identifier": f"{source_id}:{identifier or core.image_key(landing)}",
        "license": license_name,
        "license_url": license_url,
        "author": author,
        "rights_basis": f"{source_id.upper()}_SOURCE_LICENSE_COMMERCIAL_USE",
        "acquired_at": datetime.now(core.IST).isoformat(),
    }


def main() -> int:
    config = core.load_json(core.CONFIG_PATH, {})
    if not config.get("enabled"):
        print(json.dumps({"status": "VISUAL_ACQUISITION_DISABLED", "pool_changed": False}))
        return 0

    sources = sorted(
        [s for s in config.get("sources", []) if s.get("enabled", True) and str(s.get("id") or "").lower() in {"pexels", "pixabay", "unsplash"}],
        key=lambda s: int(s.get("priority", 100)),
    )
    pool = core.load_json(core.POOL_PATH, [])
    if not isinstance(pool, list):
        pool = []
    used = core.used_calendar_keys()
    # Hard cutover: keep only current approved stock sources and unused images.
    pool = [x for x in pool if isinstance(x, dict) and str(x.get("source") or "") in ACTIVE_SOURCE_NAMES and core.image_key(str(x.get("image") or "")) not in used]

    log = core.load_json(core.LOG_PATH, {"schema_version": 1, "department_id": "aura3", "seen_image_keys": []})
    seen = {str(x) for x in log.get("seen_image_keys", []) if str(x)} | used
    seen.update(core.image_key(str(x.get("image") or "")) for x in pool if core.image_key(str(x.get("image") or "")))
    phashes = {str(x) for x in log.get("seen_perceptual_hashes", []) if re.fullmatch(r"[0-9a-fA-F]{16}", str(x))}
    for existing in pool:
        value = str(existing.get("perceptual_hash") or "")
        if re.fullmatch(r"[0-9a-fA-F]{16}", value):
            phashes.add(value)

    pages = {str(k): max(1, int(v or 1)) for k, v in (log.get("stock_source_pages") or {}).items()}
    target = int(config.get("target_fresh_pool_items", 80))
    max_new = int(config.get("max_new_items_per_run", 40))
    max_requests = int(config.get("max_search_requests_per_run", 24))
    dedupe_cfg = config.get("perceptual_dedupe") or {}
    threshold = int(dedupe_cfg.get("max_hamming_distance", 4))
    hash_timeout = int(dedupe_cfg.get("timeout_seconds", 10))
    hash_limit = int(dedupe_cfg.get("max_hash_downloads_per_run", 50))

    acquired: list[dict] = []
    requests = 0
    hash_attempts = 0
    stats = {str(s.get("id")): {"requests": 0, "acquired": 0, "errors": 0, "credential_present": bool(_credential(s))} for s in sources}

    for source in sources:
        sid = str(source.get("id"))
        if not _credential(source):
            continue
        per_source_limit = max(1, int(source.get("max_requests_per_run", 8)))
        source_requests = 0
        for search in config.get("search_terms", []):
            if len(pool) + len(acquired) >= target or len(acquired) >= max_new or requests >= max_requests or source_requests >= per_source_limit:
                break
            progress = f"{sid}::{str(search.get('query') or '').strip()}"
            page = pages.get(progress, 1)
            try:
                rows, has_more = _query_source(config, source, search, page)
                requests += 1
                source_requests += 1
                stats[sid]["requests"] += 1
            except Exception as error:
                requests += 1
                source_requests += 1
                stats[sid]["requests"] += 1
                stats[sid]["errors"] += 1
                print(json.dumps({"stock_source": sid, "status": "DEGRADED", "error_type": type(error).__name__}))
                continue

            pages[progress] = page + 1 if has_more else 1
            for row in rows:
                item = _stock_item(config, source, search, row)
                if not item:
                    continue
                key = core.image_key(item["image"])
                if not key or key in seen:
                    continue
                phash = None
                if bool(dedupe_cfg.get("enabled", True)) and hash_attempts < hash_limit:
                    hash_attempts += 1
                    phash = core.perceptual_hash_for_url(item["dedupe_image"], hash_timeout)
                if phash and core.near_duplicate(phash, phashes, threshold):
                    continue
                if phash:
                    item["perceptual_hash"] = phash
                    phashes.add(phash)
                seen.add(key)
                acquired.append(item)
                stats[sid]["acquired"] += 1
                if len(pool) + len(acquired) >= target or len(acquired) >= max_new:
                    break

    pool.extend(acquired)
    pool = pool[: int(config.get("max_pool_items", 120))]
    core.save_json(core.POOL_PATH, pool)
    log.update({
        "schema_version": 3,
        "department_id": "aura3",
        "provider": "STOCK_MEDIA_GOVERNED",
        "active_sources": ["pexels", "pixabay", "unsplash"],
        "stock_source_pages": pages,
        "seen_image_keys": sorted(seen),
        "seen_perceptual_hashes": sorted(phashes),
        "last_run_acquired": len(acquired),
        "last_run_requests": requests,
        "source_stats": stats,
        "observed_at": datetime.now(core.IST).isoformat(),
    })
    core.save_json(core.LOG_PATH, log)

    configured = [sid for sid, row in stats.items() if row["credential_present"]]
    if not configured:
        status = "WAITING_FOR_STOCK_SOURCE_CREDENTIALS"
    elif acquired:
        status = "STOCK_IMAGES_ACQUIRED"
    else:
        status = "NO_NEW_STOCK_IMAGES_FOUND"
    print(json.dumps({"status": status, "acquired": len(acquired), "fresh_pool_items": len(pool), "requests": requests, "configured_sources": configured, "source_stats": stats}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
