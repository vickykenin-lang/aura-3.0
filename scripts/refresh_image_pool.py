#!/usr/bin/env python3
"""Resilient network front-end for AURA3 governed image acquisition.

The acquisition policy and queue contract remain in refresh_image_pool_core.
This wrapper hardens Wikimedia/Openverse transport and adds a governed Nappy
CC0 recovery fallback without relaxing dedupe, current-design, or actual-image
AI validation requirements.
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
_CORE_SPEC = importlib.util.spec_from_file_location("refresh_image_pool_core", _CORE_PATH)
if _CORE_SPEC is None or _CORE_SPEC.loader is None:
    raise ImportError(f"Unable to load acquisition core from {_CORE_PATH}")
core = importlib.util.module_from_spec(_CORE_SPEC)
_CORE_SPEC.loader.exec_module(core)

for _name in dir(core):
    if not _name.startswith("__"):
        globals().setdefault(_name, getattr(core, _name))

RETRYABLE_HTTP = {403, 408, 425, 429, 500, 502, 503, 504}
NAPPY_CC0_URL = "https://creativecommons.org/publicdomain/zero/1.0/"


def _headers(config: dict, *, openverse: bool = False) -> dict[str, str]:
    headers = {
        "User-Agent": str(config.get("user_agent", "AURA3-VisualAcquisition/8.0")),
        "Accept": "application/json",
        "Accept-Encoding": "identity",
    }
    if openverse:
        token = str(os.getenv("OPENVERSE_ACCESS_TOKEN") or "").strip()
        if token:
            headers["Authorization"] = f"Bearer {token}"
    return headers


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
    last_error: Exception | None = None
    for attempt in range(max(1, attempts)):
        request = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return json.load(response)
        except urllib.error.HTTPError as error:
            last_error = error
            code = int(getattr(error, "code", 0) or 0)
            print(json.dumps({
                "image_source_http_warning": source,
                "http_status": code,
                "attempt": attempt + 1,
                "retryable": code in RETRYABLE_HTTP,
                "authenticated": "Authorization" in headers,
            }))
            if code not in RETRYABLE_HTTP or attempt + 1 >= attempts:
                raise
            time.sleep(_retry_delay(error, attempt))
        except (TimeoutError, urllib.error.URLError) as error:
            last_error = error
            if attempt + 1 >= attempts:
                raise
            time.sleep(min(6.0, 0.75 * (2 ** attempt)))
    assert last_error is not None
    raise last_error


def _commons_search_text(search: dict) -> str:
    query = str(search.get("query") or "").strip()
    for token in (" photograph", " photography"):
        query = query.replace(token, "")
    return (query + " filetype:bitmap").strip()


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
        "gsrsearch": _commons_search_text(search),
        "gsrlimit": str(page_size),
        "prop": "imageinfo",
        "iiprop": "url|mime|size|extmetadata",
        "iiurlwidth": "1600",
    }
    if offset > 0:
        params["gsroffset"] = str(offset)
    timeout = int(source.get("timeout_seconds", config.get("timeout_seconds", 15)))
    payload = _json_request(
        endpoint + "?" + urllib.parse.urlencode(params),
        _headers(config), timeout, source="wikimedia_commons",
        attempts=max(1, int(source.get("http_retry_attempts", 3))),
    )
    pages = list((payload.get("query") or {}).get("pages") or [])
    continuation = payload.get("continue") or {}
    next_raw = continuation.get("gsroffset")
    if next_raw is not None:
        try:
            return pages, max(offset + 1, int(next_raw)), True
        except (TypeError, ValueError):
            pass
    if len(pages) >= page_size:
        return pages, offset + page_size, True
    return pages, offset, False


def _openverse_once(config: dict, search: dict, page: int, source: dict, licenses: list[str]) -> dict:
    endpoint = str(source.get("endpoint") or "https://api.openverse.org/v1/images/")
    page_size = max(1, min(80, int(source.get("page_size", config.get("search_page_size", 50)))))
    params = {
        "q": str(search["query"]),
        "page": str(max(1, page)),
        "page_size": str(page_size),
        "license": ",".join(licenses),
        "mature": "false",
    }
    timeout = int(source.get("timeout_seconds", config.get("timeout_seconds", 15)))
    return _json_request(
        endpoint + "?" + urllib.parse.urlencode(params),
        _headers(config, openverse=True), timeout, source="openverse",
        attempts=max(1, int(source.get("http_retry_attempts", 3))),
    )


def openverse_query(config: dict, search: dict, page: int = 1, source: dict | None = None) -> tuple[list[dict], int, bool]:
    source = source or {}
    licenses = list(source.get("license_slugs") or ["cc0", "pdm"])
    try:
        payload = _openverse_once(config, search, page, source, licenses)
    except urllib.error.HTTPError as error:
        if int(getattr(error, "code", 0) or 0) != 400 or len(licenses) <= 1:
            raise
        merged: list[dict] = []
        page_count = page
        for slug in licenses:
            part = _openverse_once(config, search, page, source, [slug])
            merged.extend(list(part.get("results") or []))
            page_count = max(page_count, int(part.get("page_count") or page))
        payload = {"page": page, "page_count": page_count, "results": merged}
    results = list(payload.get("results") or [])
    current = int(payload.get("page") or page)
    page_count = int(payload.get("page_count") or current)
    return results, current + 1, current < page_count


def nappy_query(config: dict, page: int = 1) -> tuple[list[dict], int, bool]:
    source = dict(config.get("nappy_fallback") or {})
    endpoint = str(source.get("endpoint") or "https://api.nappy.co/v1/openverse/images")
    per_page = max(1, min(100, int(source.get("page_size", 50))))
    params = {"page": str(max(1, page)), "per_page": str(per_page)}
    payload = _json_request(
        endpoint + "?" + urllib.parse.urlencode(params),
        _headers(config), int(source.get("timeout_seconds", config.get("timeout_seconds", 15))),
        source="nappy_cc0", attempts=max(1, int(source.get("http_retry_attempts", 3))),
    )
    rows = list(payload.get("images") or [])
    return rows, page + 1, bool(payload.get("next_page"))


def _nappy_metadata_text(item: dict) -> str:
    return " ".join([
        str(item.get("title") or ""),
        str(item.get("tags") or ""),
        str(item.get("foreign_landing_url") or ""),
    ]).lower()


def pool_item_from_nappy(config: dict, item: dict) -> dict | None:
    if str(item.get("license") or "").strip().upper() != "CC0":
        return None
    filetype = str(item.get("filetype") or "").strip().lower().lstrip(".")
    mime = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png", "webp": "image/webp"}.get(filetype, "")
    if mime not in {str(x).lower() for x in config.get("allowed_mime_types", [])}:
        return None
    try:
        width, height = int(item.get("width") or 0), int(item.get("height") or 0)
    except (TypeError, ValueError):
        return None
    if width < int(config.get("min_width", 1200)) or height < int(config.get("min_height", 800)):
        return None
    image_url = str(item.get("url") or "").strip()
    landing = str(item.get("foreign_landing_url") or "").strip()
    if not image_url.startswith("https://") or not landing.startswith("https://"):
        return None
    text = _nappy_metadata_text(item)
    rules = config.get("metadata_prefilter") or {}
    positive = [str(x).lower() for x in rules.get("positive_tokens", []) if str(x).strip()]
    negative = [str(x).lower() for x in rules.get("negative_tokens", []) if str(x).strip()]
    if any(token in text for token in negative):
        return None
    if positive and not any(token in text for token in positive):
        return None
    identifier = str(item.get("foreign_identifier") or "").strip()
    tag = "meeting" if "meeting" in text or "conference" in text else "office"
    return {
        "photo_tag": tag,
        "angle": "current commercial workspace planning, people, furniture and execution",
        "image": image_url,
        "dedupe_image": image_url + "?auto=format&w=600&q=75",
        "source": "Nappy",
        "source_page": landing,
        "source_title": str(item.get("title") or "").strip(),
        "source_identifier": f"nappy:{identifier or core.image_key(landing)}",
        "license": "CC0 1.0",
        "license_url": NAPPY_CC0_URL,
        "author": str(item.get("creator") or "Nappy contributor").strip(),
        "rights_basis": "NAPPY_API_CC0_ONLY_PROVIDER_CONTRACT",
        "acquired_at": datetime.now(core.IST).isoformat(),
    }


def refresh_nappy_fallback(config: dict) -> int:
    source = dict(config.get("nappy_fallback") or {})
    if not source.get("enabled", False):
        return 0
    pool = core.load_json(core.POOL_PATH, [])
    if not isinstance(pool, list):
        pool = []
    target = int(config.get("target_fresh_pool_items", 80))
    if len(pool) >= target:
        return 0
    log = core.load_json(core.LOG_PATH, {"seen_image_keys": []})
    used = core.used_calendar_keys()
    seen = {str(x) for x in log.get("seen_image_keys", []) if str(x)} | used
    seen.update(core.image_key(str(x.get("image") or "")) for x in pool if isinstance(x, dict))
    phashes = {str(x) for x in log.get("seen_perceptual_hashes", []) if re.fullmatch(r"[0-9a-fA-F]{16}", str(x))}
    for existing in pool:
        value = str(existing.get("perceptual_hash") or "") if isinstance(existing, dict) else ""
        if re.fullmatch(r"[0-9a-fA-F]{16}", value):
            phashes.add(value)
    dedupe_cfg = config.get("perceptual_dedupe") or {}
    threshold = int(dedupe_cfg.get("max_hamming_distance", 4))
    hash_timeout = int(dedupe_cfg.get("timeout_seconds", 10))
    max_new = min(int(config.get("max_new_items_per_run", 40)), int(source.get("max_new_items_per_run", 30)))
    max_pages = max(1, int(source.get("max_pages_per_run", 8)))
    acquired: list[dict] = []
    page = 1
    requests = 0
    try:
        for _ in range(max_pages):
            rows, nxt, has_more = nappy_query(config, page)
            requests += 1
            for row in rows:
                item = pool_item_from_nappy(config, row)
                if not item:
                    continue
                canonical = core.image_key(item["image"])
                if not canonical or canonical in seen:
                    continue
                phash = core.perceptual_hash_for_url(item["dedupe_image"], hash_timeout)
                if phash and core.near_duplicate(phash, phashes, threshold):
                    continue
                if phash:
                    item["perceptual_hash"] = phash
                    phashes.add(phash)
                seen.add(canonical)
                acquired.append(item)
                if len(acquired) >= max_new or len(pool) + len(acquired) >= target:
                    break
            if len(acquired) >= max_new or len(pool) + len(acquired) >= target or not has_more:
                break
            page = nxt
    except Exception as error:
        print(json.dumps({"nappy_fallback":"DEGRADED","error_type":type(error).__name__,"requests":requests}))
    if acquired:
        pool.extend(acquired)
        core.save_json(core.POOL_PATH, pool[:int(config.get("max_pool_items", 120))])
        log.update({
            "provider": "MULTI_SOURCE_GOVERNED",
            "last_nappy_status": "NAPPY_CC0_FALLBACK_ACQUIRED",
            "last_nappy_acquired_count": len(acquired),
            "last_nappy_requests": requests,
            "observed_at": datetime.now(core.IST).isoformat(),
            "seen_image_keys": sorted(seen),
            "seen_perceptual_hashes": sorted(phashes),
        })
        core.save_json(core.LOG_PATH, log)
    print(json.dumps({"nappy_fallback":"COMPLETE","acquired":len(acquired),"requests":requests,"fresh_pool_items":len(pool)+len(acquired)}))
    return len(acquired)


core.commons_query = commons_query
core.openverse_query = openverse_query


def main() -> int:
    rc = core.main()
    config = core.load_json(core.CONFIG_PATH, {})
    if len(core.load_json(core.POOL_PATH, [])) < int(config.get("target_fresh_pool_items", 80)):
        refresh_nappy_fallback(config)
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
