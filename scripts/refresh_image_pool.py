#!/usr/bin/env python3
"""Resilient network front-end for AURA3 governed image acquisition.

The acquisition policy and queue contract remain in refresh_image_pool_core.
This wrapper hardens Wikimedia/Openverse transport without relaxing CC0/Public
Domain, dedupe, current-design, or actual-image AI validation requirements.
"""
from __future__ import annotations

import importlib.util
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

_CORE_PATH = Path(__file__).with_name("refresh_image_pool_core.py")
_CORE_SPEC = importlib.util.spec_from_file_location("refresh_image_pool_core", _CORE_PATH)
if _CORE_SPEC is None or _CORE_SPEC.loader is None:
    raise ImportError(f"Unable to load acquisition core from {_CORE_PATH}")
core = importlib.util.module_from_spec(_CORE_SPEC)
_CORE_SPEC.loader.exec_module(core)

# Re-export the stable helper API expected by existing tests/callers.
for _name in dir(core):
    if not _name.startswith("__"):
        globals().setdefault(_name, getattr(core, _name))

RETRYABLE_HTTP = {403, 408, 425, 429, 500, 502, 503, 504}


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
        _headers(config),
        timeout,
        source="wikimedia_commons",
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
        _headers(config, openverse=True),
        timeout,
        source="openverse",
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


core.commons_query = commons_query
core.openverse_query = openverse_query


def main() -> int:
    return core.main()


if __name__ == "__main__":
    raise SystemExit(main())
