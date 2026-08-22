#!/usr/bin/env python3
"""Generate the daily AURA2 caption batch against a curated interior image pool."""

from __future__ import annotations

import json
import os
import re
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
IST = timezone(timedelta(hours=5, minutes=30))
GEMINI_MODEL = os.environ.get("GEMINI_MODEL") or "gemini-3.7-flash"
CANDIDATE_COUNT = 10

SYSTEM_PROMPT = """You create lead-generation Instagram copy for Design Infra, a premium
turnkey-interiors company serving Delhi NCR. Write concise, credible bilingual content.
Every candidate must contain:
- a strong English hook;
- a natural Hindi/Hinglish caption;
- one concrete conversion signal: price band, timeline, inclusions, or process;
- a free-consultation/official-website/link-in-bio CTA;
- 3-6 relevant hashtags.

Never claim that a reference/stock image is a completed Design Infra project. Do not invent
testimonials, warranties, project counts, prices presented as fixed quotations, or guarantees."""


def load_json(path: str, default):
    try:
        with open(os.path.join(ROOT, path), encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, json.JSONDecodeError):
        return default


def save_json(path: str, data) -> None:
    with open(os.path.join(ROOT, path), "w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2, ensure_ascii=False)
        handle.write("\n")


def extract_json(text: str):
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\[.*\]", text, re.DOTALL)
        if not match:
            raise ValueError("Gemini reply did not contain a JSON array")
        return json.loads(match.group(0))


def gemini_generate(api_key: str, selected: list[dict]) -> list[dict]:
    inputs = [
        {
            "slot": index + 1,
            "room_tag": item["photo_tag"],
            "content_angle": item["angle"],
        }
        for index, item in enumerate(selected)
    ]
    prompt = (
        SYSTEM_PROMPT
        + "\n\nCreate exactly 10 items for these fixed image slots:\n"
        + json.dumps(inputs, ensure_ascii=False)
        + '\n\nReturn only a JSON array. Each object must be: '
        '{"slot":1,"hook_en":"...","caption_hi":"...","hashtags":"#... #..."}'
    )
    endpoint = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        f"{urllib.parse.quote(GEMINI_MODEL, safe='')}:generateContent"
        f"?key={urllib.parse.quote(api_key, safe='')}"
    )
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "responseMimeType": "application/json",
            "maxOutputTokens": 3500,
        },
    }
    request = urllib.request.Request(
        endpoint,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=120) as response:
        data = json.load(response)
    parts = data["candidates"][0]["content"]["parts"]
    text = "".join(part.get("text", "") for part in parts)
    generated = extract_json(text)
    if not isinstance(generated, list) or len(generated) != CANDIDATE_COUNT:
        raise ValueError("Gemini must return exactly 10 candidates")
    return generated


def valid_copy(item: dict) -> bool:
    hook = str(item.get("hook_en", "")).strip()
    caption = str(item.get("caption_hi", "")).strip()
    hashtags = str(item.get("hashtags", "")).strip()
    cta = caption.lower()
    return (
        12 <= len(hook) <= 140
        and 25 <= len(caption) <= 900
        and hashtags.startswith("#")
        and any(
            term in cta
            for term in ("consult", "website", "link in bio", "official site", "सलाह")
        )
    )


def main() -> int:
    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not api_key:
        print("GEMINI_API_KEY is required")
        return 1

    pool = load_json("data/image_pool.json", [])
    if len(pool) < CANDIDATE_COUNT:
        print("data/image_pool.json needs at least 10 curated images")
        return 1

    now = datetime.now(IST)
    start = now.toordinal() % len(pool)
    selected = [pool[(start + offset) % len(pool)] for offset in range(CANDIDATE_COUNT)]

    try:
        generated = gemini_generate(api_key, selected)
    except Exception as error:
        print(f"GENERATION FAILED: {type(error).__name__}: {error}")
        return 1

    by_slot = {int(item.get("slot", 0)): item for item in generated}
    if set(by_slot) != set(range(1, CANDIDATE_COUNT + 1)):
        print("GENERATION FAILED: slots must be 1 through 10 exactly once")
        return 1

    batch_date = now.date().isoformat()
    day_id = now.strftime("%Y%m%d")
    posts = []
    for slot, image in enumerate(selected, start=1):
        copy = by_slot[slot]
        if not valid_copy(copy):
            print(f"GENERATION FAILED: candidate {slot} failed local copy validation")
            return 1
        posts.append(
            {
                "id": f"{day_id}-{slot:02d}",
                "date": batch_date,
                "photo_tag": image["photo_tag"],
                "image": image["image"],
                "image_source": image.get("source", "curated"),
                "disclosure": "Inspiration reference; not a completed Design Infra project.",
                "ig": {
                    "hook_en": str(copy["hook_en"]).strip(),
                    "caption_hi": str(copy["caption_hi"]).strip(),
                    "hashtags": str(copy["hashtags"]).strip(),
                },
            }
        )

    calendar = {
        "engine": "AURA2",
        "mode": "daily_batch",
        "batch_date": batch_date,
        "generator": f"Gemini {GEMINI_MODEL}",
        "notes": "Candidates require Gemini Vision + DeepSeek business gate before dashboard.",
        "days": posts,
    }
    save_json("content/calendar.json", calendar)

    approvals = load_json("data/approvals.json", {})
    approvals["_note"] = (
        "Only Founder-triggered dual-gate-passed posts can be approved for manual publishing."
    )
    for post in posts:
        approvals.setdefault(post["id"], "pending")
    save_json("data/approvals.json", approvals)
    print(f"Generated {len(posts)} candidates for {batch_date}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
