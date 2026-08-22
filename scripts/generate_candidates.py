#!/usr/bin/env python3
"""Generate the daily AURA2 caption batch against a curated interior image pool."""

from __future__ import annotations

import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
IST = timezone(timedelta(hours=5, minutes=30))
REQUESTED_GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "").strip()
GEMINI_MODELS = tuple(
    dict.fromkeys(
        model
        for model in (
            REQUESTED_GEMINI_MODEL,
            "gemini-3.7-flash",
            "gemini-3.5-flash",
            "gemini-3.5-flash-lite",
        )
        if model
    )
)
CANDIDATE_COUNT = 10
RETRYABLE_HTTP_CODES = {429, 500, 502, 503, 504}
RETRY_DELAYS_SECONDS = (2, 5, 10)

CANDIDATE_SCHEMA = {
    "type": "ARRAY",
    "minItems": CANDIDATE_COUNT,
    "maxItems": CANDIDATE_COUNT,
    "items": {
        "type": "OBJECT",
        "properties": {
            "slot": {"type": "INTEGER", "minimum": 1, "maximum": CANDIDATE_COUNT},
            "hook_en": {"type": "STRING"},
            "caption_hi": {"type": "STRING"},
            "hashtags": {"type": "STRING"},
        },
        "required": ["slot", "hook_en", "caption_hi", "hashtags"],
    },
}

SYSTEM_PROMPT = """You create lead-generation Instagram copy for Design Infra, a premium
turnkey-interiors company serving Delhi NCR. Write concise, credible bilingual content.
Every candidate must contain:
- a strong English hook;
- a natural Hindi/Hinglish caption of 60-100 words;
- one concrete conversion signal: price band, timeline, inclusions, or process;
- a free-consultation/official-website/link-in-bio CTA;
- 3-6 relevant hashtags.

The caption must contain at least one literal CTA phrase from this list: "free consultation",
"official website", "link in bio", or "designinfra.in".

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
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text)
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\[.*\]", text, re.DOTALL)
        if not match:
            raise ValueError("Gemini reply did not contain a JSON array")
        parsed = json.loads(match.group(0))

    if isinstance(parsed, dict):
        for key in ("candidates", "items", "posts"):
            if isinstance(parsed.get(key), list):
                return parsed[key]
    return parsed


def request_json(request: urllib.request.Request, timeout: int = 120) -> dict:
    for attempt in range(len(RETRY_DELAYS_SECONDS) + 1):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return json.load(response)
        except urllib.error.HTTPError as error:
            detail = error.read().decode("utf-8", errors="replace")[:500]
            if error.code not in RETRYABLE_HTTP_CODES or attempt == len(RETRY_DELAYS_SECONDS):
                raise RuntimeError(f"Gemini HTTP {error.code}: {detail}") from error
            delay = RETRY_DELAYS_SECONDS[attempt]
            print(f"Gemini HTTP {error.code}; retrying in {delay}s")
            time.sleep(delay)
        except urllib.error.URLError as error:
            if attempt == len(RETRY_DELAYS_SECONDS):
                raise RuntimeError(f"Gemini network error: {error.reason}") from error
            delay = RETRY_DELAYS_SECONDS[attempt]
            print(f"Gemini network error; retrying in {delay}s")
            time.sleep(delay)
    raise RuntimeError("Gemini request exhausted retries")


def gemini_generate(api_key: str, selected: list[dict]) -> tuple[list[dict], str]:
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
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "responseMimeType": "application/json",
            "responseSchema": CANDIDATE_SCHEMA,
            "maxOutputTokens": 8000,
        },
    }
    data = None
    used_model = ""
    for index, model in enumerate(GEMINI_MODELS):
        endpoint = (
            "https://generativelanguage.googleapis.com/v1beta/models/"
            f"{urllib.parse.quote(model, safe='')}:generateContent"
            f"?key={urllib.parse.quote(api_key, safe='')}"
        )
        request = urllib.request.Request(
            endpoint,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            data = request_json(request)
            used_model = model
            break
        except RuntimeError as error:
            fallback_error = any(
                marker in str(error)
                for marker in (
                    "HTTP 404",
                    "HTTP 429",
                    "HTTP 500",
                    "HTTP 502",
                    "HTTP 503",
                    "HTTP 504",
                    "network error",
                )
            )
            if not fallback_error or index == len(GEMINI_MODELS) - 1:
                raise
            print(f"Gemini model {model} unavailable; trying {GEMINI_MODELS[index + 1]}")
    if data is None:
        raise RuntimeError("No Gemini generation model was available")
    parts = data["candidates"][0]["content"]["parts"]
    text = "".join(part.get("text", "") for part in parts)
    try:
        generated = extract_json(text)
    except (ValueError, json.JSONDecodeError) as error:
        finish_reason = data.get("candidates", [{}])[0].get("finishReason", "unknown")
        preview = re.sub(r"\s+", " ", text)[:400]
        raise ValueError(
            f"invalid structured reply; finish_reason={finish_reason}; preview={preview!r}"
        ) from error
    if not isinstance(generated, list) or len(generated) != CANDIDATE_COUNT:
        raise ValueError("Gemini must return exactly 10 candidates")
    return generated, used_model


CTA_TERMS = ("consult", "website", "link in bio", "official site", "designinfra.in", "सलाह")
DEFAULT_HASHTAGS = ("#DesignInfra", "#DelhiNCRInteriors", "#TurnkeyInteriors")


def normalize_copy(item: dict) -> dict:
    hook = str(item.get("hook_en", "")).strip()
    caption = str(item.get("caption_hi", "")).strip()
    hashtags = str(item.get("hashtags", "")).strip()

    if len(hook) > 140:
        hook = hook[:137].rstrip() + "..."

    if len(caption) > 800:
        caption = caption[:797].rstrip() + "..."
    if caption and not any(term in caption.lower() for term in CTA_TERMS):
        caption += "\n\nFree consultation ke liye designinfra.in visit karein."

    tags = re.findall(r"#[\w-]+", hashtags)
    for default_tag in DEFAULT_HASHTAGS:
        if default_tag.lower() not in {tag.lower() for tag in tags}:
            tags.append(default_tag)
        if len(tags) >= 3:
            break

    return {
        "slot": item.get("slot"),
        "hook_en": hook,
        "caption_hi": caption,
        "hashtags": " ".join(tags[:6]),
    }


def copy_validation_errors(item: dict) -> list[str]:
    hook = str(item.get("hook_en", "")).strip()
    caption = str(item.get("caption_hi", "")).strip()
    hashtags = re.findall(r"#[\w-]+", str(item.get("hashtags", "")))
    errors = []
    if not 12 <= len(hook) <= 140:
        errors.append("hook_length")
    if not 25 <= len(caption) <= 900:
        errors.append("caption_length")
    if len(hashtags) < 3:
        errors.append("hashtags")
    if not any(term in caption.lower() for term in CTA_TERMS):
        errors.append("cta")
    return errors


def valid_copy(item: dict) -> bool:
    hook = str(item.get("hook_en", "")).strip()
    caption = str(item.get("caption_hi", "")).strip()
    hashtags = str(item.get("hashtags", "")).strip()
    return (
        12 <= len(hook) <= 140
        and 25 <= len(caption) <= 900
        and hashtags.startswith("#")
        and len(re.findall(r"#[\w-]+", hashtags)) >= 3
        and any(term in caption.lower() for term in CTA_TERMS)
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
        generated, used_model = gemini_generate(api_key, selected)
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
        copy = normalize_copy(by_slot[slot])
        if not valid_copy(copy):
            errors = ",".join(copy_validation_errors(copy))
            print(f"GENERATION FAILED: candidate {slot} failed local copy validation: {errors}")
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
        "generator": f"Gemini {used_model}",
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
