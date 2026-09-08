#!/usr/bin/env python3
"""Resilient public-web research for the AURA3 Vastu consultant agent.

Uses public RSS/search endpoints without credentials. It returns only short titles,
snippets and source URLs; source prose is never copied into AURA3 captions.
"""
from __future__ import annotations

import html
import json
import re
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from urllib.parse import urlsplit

UA = "AURA3-VastuResearch/2.0"


def _clean(value: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html.unescape(str(value or "")))).strip()


def _domain(url: str, fallback: str = "") -> str:
    try:
        host = (urlsplit(url).hostname or "").lower().removeprefix("www.")
        if host:
            return host
    except ValueError:
        pass
    return re.sub(r"[^a-z0-9]+", "-", fallback.lower()).strip("-") or "source"


def google_news_rss(query: str, limit: int = 8) -> list[dict]:
    params = urllib.parse.urlencode({"q": query, "hl": "en-IN", "gl": "IN", "ceid": "IN:en"})
    url = "https://news.google.com/rss/search?" + params
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=15) as response:
        root = ET.fromstring(response.read())
    results = []
    for item in root.findall(".//item"):
        title = _clean(item.findtext("title") or "")
        link = _clean(item.findtext("link") or "")
        description = _clean(item.findtext("description") or "")
        source = item.find("source")
        source_name = _clean(source.text if source is not None else "")
        source_url = _clean(source.attrib.get("url", "") if source is not None else "")
        if not title or not link:
            continue
        results.append({
            "title": title[:220],
            "snippet": description[:500],
            "url": link,
            "domain": _domain(source_url, source_name),
            "publisher": source_name,
            "research_channel": "google_news_rss",
        })
        if len(results) >= limit:
            break
    return results


def bing_news_rss(query: str, limit: int = 8) -> list[dict]:
    url = "https://www.bing.com/news/search?" + urllib.parse.urlencode({"q": query, "format": "rss"})
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=15) as response:
        root = ET.fromstring(response.read())
    results = []
    for item in root.findall(".//item"):
        title = _clean(item.findtext("title") or "")
        link = _clean(item.findtext("link") or "")
        description = _clean(item.findtext("description") or "")
        if not title or not link:
            continue
        results.append({
            "title": title[:220],
            "snippet": description[:500],
            "url": link,
            "domain": _domain(link),
            "publisher": _domain(link),
            "research_channel": "bing_news_rss",
        })
        if len(results) >= limit:
            break
    return results


def wikipedia_search(query: str, limit: int = 3) -> list[dict]:
    params = urllib.parse.urlencode({
        "action": "query", "format": "json", "list": "search",
        "srsearch": query, "srlimit": str(limit), "utf8": "1",
    })
    url = "https://en.wikipedia.org/w/api.php?" + params
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=15) as response:
        payload = json.load(response)
    results = []
    for row in ((payload.get("query") or {}).get("search") or []):
        title = _clean(row.get("title", ""))
        if not title:
            continue
        page_url = "https://en.wikipedia.org/wiki/" + urllib.parse.quote(title.replace(" ", "_"))
        results.append({
            "title": title,
            "snippet": _clean(row.get("snippet", ""))[:500],
            "url": page_url,
            "domain": "wikipedia.org",
            "publisher": "Wikipedia",
            "research_channel": "wikipedia_search",
        })
    return results


def research(query: str, minimum_sources: int = 2, max_sources: int = 5) -> list[dict]:
    candidates: list[dict] = []
    errors: list[str] = []
    for fn in (google_news_rss, bing_news_rss, wikipedia_search):
        try:
            candidates.extend(fn(query, max_sources + 3))
        except Exception as exc:
            errors.append(type(exc).__name__)

    selected = []
    seen_domains = set()
    seen_titles = set()
    for row in candidates:
        domain = str(row.get("domain") or "").lower()
        title_key = str(row.get("title") or "").lower()
        if not domain or domain in seen_domains or title_key in seen_titles:
            continue
        seen_domains.add(domain)
        seen_titles.add(title_key)
        selected.append(row)
        if len(selected) >= max_sources:
            break

    if len(selected) < minimum_sources:
        raise RuntimeError(
            f"internet research insufficient: sources={len(selected)}; channels_failed={','.join(errors) or 'none'}"
        )
    return selected
