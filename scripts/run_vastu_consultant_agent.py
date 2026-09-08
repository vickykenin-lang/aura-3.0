#!/usr/bin/env python3
"""Production entrypoint for AURA3 Vastu consultant agent."""
from __future__ import annotations

import os

import vastu_consultant_agent as agent
from vastu_web_research import research


def _research(query: str, minimum_sources: int = 2, max_sources: int = 5):
    return research(query, minimum_sources=minimum_sources, max_sources=max_sources)


def _choose_image(tag: str):
    """Prefer a strict current image; otherwise use a governed source only as Canvas input.

    The fallback source itself is never approval-ready. When this path is used we force
    Nova Canvas redevelopment and the newly generated image must pass the strict visual gate.
    """
    try:
        return agent.choose_image_original(tag)
    except Exception:
        used = agent.used_images()
        blocked = agent.blacklisted_images()
        pool = agent.load(agent.POOL, [])
        if not isinstance(pool, list):
            pool = []
        ranked = sorted(pool, key=lambda x: 0 if str(x.get("photo_tag", "")).lower() == tag else 1)
        for item in ranked:
            url = str(item.get("image", ""))
            key = agent.image_key(url)
            if not url.startswith("https://") or not key or key in used or key in blocked:
                continue
            os.environ["AURA3_VASTU_REDEVELOP"] = "yes"
            return {
                **item,
                "vision": {
                    "visual_ok": False,
                    "room_type": str(item.get("photo_tag") or tag or "interior").lower(),
                    "quality": 0,
                    "design_freshness": "SourceOnly",
                    "style": "governed reference for redevelopment",
                    "visible_features": [],
                    "sample_caption_angle": "Use only after Nova Canvas redevelopment and fresh visual validation.",
                },
                "redevelopment_source_only": True,
            }
        raise RuntimeError("no governed image source available for Vastu redevelopment")


agent.ddg_research = _research
agent.choose_image_original = agent.choose_image
agent.choose_image = _choose_image


if __name__ == "__main__":
    raise SystemExit(agent.main())
