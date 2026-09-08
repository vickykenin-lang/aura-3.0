#!/usr/bin/env python3
"""Production entrypoint for AURA3 Vastu consultant agent."""
from __future__ import annotations

import os

import vastu_consultant_agent as agent
from vastu_web_research import research


def _research(query: str, minimum_sources: int = 2, max_sources: int = 5):
    return research(query, minimum_sources=minimum_sources, max_sources=max_sources)


def _source_only(item: dict, tag: str) -> dict:
    os.environ["AURA3_VASTU_REDEVELOP"] = "yes"
    return {
        **item,
        "vision": {
            "visual_ok": False,
            "room_type": str(item.get("photo_tag") or tag or "interior").lower(),
            "quality": 0,
            "design_freshness": "SourceOnly",
            "style": "governed reference for Nova Canvas redevelopment",
            "visible_features": [],
            "sample_caption_angle": "Reference only. Final post may use only the freshly redeveloped image after strict visual validation.",
        },
        "redevelopment_source_only": True,
    }


def _choose_image(tag: str):
    """Prefer a strict fresh image; otherwise reuse a governed image only as Canvas input.

    Previously-used references are allowed here because the source is never posted again:
    Nova Canvas must produce a new asset and that new asset must pass the strict visual gate.
    Persistent blacklist remains excluded. If the fresh pool has no usable source, a previously
    gate-passed calendar visual can be used as the conditioning reference.
    """
    try:
        return agent.choose_image_original(tag)
    except Exception:
        blocked = agent.blacklisted_images()
        pool = agent.load(agent.POOL, [])
        if not isinstance(pool, list):
            pool = []

        # Source-only redevelopment may reuse an earlier governed pool reference.
        ranked = sorted(pool, key=lambda x: 0 if str(x.get("photo_tag", "")).lower() == tag else 1)
        for item in ranked:
            url = str(item.get("image", ""))
            key = agent.image_key(url)
            if not url.startswith("https://") or not key or key in blocked:
                continue
            return _source_only(item, tag)

        # Last safe source fallback: a previously gate-passed AURA3 calendar visual.
        calendar = agent.load(agent.CALENDAR, {"days": []})
        gates = agent.load(agent.GATES, {"posts": {}}).get("posts") or {}
        candidates = list(calendar.get("days", []))
        candidates.sort(key=lambda x: 0 if str(x.get("photo_tag", "")).lower() == tag else 1)
        for post in candidates:
            url = str(post.get("image", ""))
            key = agent.image_key(url)
            gate = gates.get(str(post.get("id", ""))) or {}
            if not url.startswith("https://") or not key or key in blocked:
                continue
            if not (gate.get("visual_ok") and gate.get("pass") and int(gate.get("score", 0) or 0) >= 7):
                continue
            return _source_only({
                "photo_tag": post.get("photo_tag", tag),
                "image": url,
                "source": post.get("image_source", "AURA3 governed calendar reference"),
                "source_page": "",
                "license": "AURA3 governed reference",
            }, tag)

        raise RuntimeError("no governed non-blacklisted image source available for Vastu redevelopment")


agent.ddg_research = _research
agent.choose_image_original = agent.choose_image
agent.choose_image = _choose_image


if __name__ == "__main__":
    raise SystemExit(agent.main())
