#!/usr/bin/env python3
"""AURA2 dual quality gate: Gemini sees the image, DeepSeek judges conversion."""

from __future__ import annotations

import base64
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
IST = timezone(timedelta(hours=5, minutes=30))
DEEPSEEK_API = "https://api.deepseek.com/chat/completions"
DEEPSEEK_MODEL = os.environ.get("DEEPSEEK_MODEL") or "deepseek-v4-flash"
GEMINI_MODEL = os.environ.get("GEMINI_MODEL") or "gemini-3.7-flash"
MAX_IMAGE_BYTES = 8 * 1024 * 1024

HARD_REJECT_TAGS = {
    "animal",
    "wildlife",
    "leopard",
    "nature-only",
    "landscape",
    "railway",
    "food-only",
    "meme",
    "kids",
    "bubblebee",
}

VISION_PROMPT = """Inspect this actual image for Design Infra, a Delhi NCR turnkey-interiors brand.
Return only JSON:
{"visual_ok":true/false,"room_type":"living|kitchen|bedroom|bathroom|dining|office|other","quality":0-10,"reasons":["..."]}

Set visual_ok=false for animals, wildlife, outdoor landscape without an interior, roads/railways,
food-only lifestyle, children, memes, unrelated stock, visible watermarks, severe blur, or an image
that is not suitable for a premium interior-design Instagram post."""

BUSINESS_SYSTEM = """You are the independent AURA2 business quality gate for Design Infra,
a premium turnkey-interiors company in Delhi NCR. The actual image has already been inspected by
Gemini Vision. Judge caption-to-room match, honest brand positioning, conversion signal
(price/timeline/process/inclusions), CTA, and lead-generation potential.

Return only valid JSON:
{"score":0-10,"pass":true/false,"reasons":["..."],"caption_match":true/false,"cta_ok":true/false,"conversion_ok":true/false}

PASS requires score >= 7, caption match, CTA, conversion signal, and no misleading claim that a
stock/reference image is Design Infra's completed work."""


def load_json(path: str, default):
    try:
        with open(os.path.join(ROOT, path), encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, json.JSONDecodeError):
        return default


def save_json(path: str, data) -> None:
    full_path = os.path.join(ROOT, path)
    os.makedirs(os.path.dirname(full_path), exist_ok=True)
    with open(full_path, "w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2, ensure_ascii=False)
        handle.write("\n")


def extract_json(text: str) -> dict:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if not match:
            raise ValueError("model reply did not contain JSON")
        return json.loads(match.group(0))


def download_image(url: str) -> tuple[str, bytes]:
    if not url.startswith("https://"):
        raise ValueError("image URL must use HTTPS")
    request = urllib.request.Request(url, headers={"User-Agent": "AURA2-QC/1.0"})
    with urllib.request.urlopen(request, timeout=45) as response:
        mime_type = response.headers.get_content_type()
        if mime_type not in {"image/jpeg", "image/png", "image/webp"}:
            raise ValueError(f"unsupported image content type: {mime_type}")
        image = response.read(MAX_IMAGE_BYTES + 1)
    if len(image) > MAX_IMAGE_BYTES:
        raise ValueError("image exceeds 8 MB vision limit")
    if not image:
        raise ValueError("downloaded image is empty")
    return mime_type, image


def gemini_vision(api_key: str, image_url: str) -> dict:
    mime_type, image = download_image(image_url)
    endpoint = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        f"{urllib.parse.quote(GEMINI_MODEL, safe='')}:generateContent"
        f"?key={urllib.parse.quote(api_key, safe='')}"
    )
    payload = {
        "contents": [
            {
                "parts": [
                    {"text": VISION_PROMPT},
                    {
                        "inline_data": {
                            "mime_type": mime_type,
                            "data": base64.b64encode(image).decode("ascii"),
                        }
                    },
                ]
            }
        ],
        "generationConfig": {
            "responseMimeType": "application/json",
            "maxOutputTokens": 400,
        },
    }
    request = urllib.request.Request(
        endpoint,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=90) as response:
        data = json.load(response)
    parts = data["candidates"][0]["content"]["parts"]
    text = "".join(part.get("text", "") for part in parts)
    result = extract_json(text)
    quality = max(0, min(10, int(result.get("quality", 0))))
    return {
        "visual_ok": bool(result.get("visual_ok", False)) and quality >= 6,
        "room_type": str(result.get("room_type", "other")),
        "quality": quality,
        "reasons": result.get("reasons") or [],
        "model": GEMINI_MODEL,
    }


def deepseek_business(api_key: str, post: dict, vision: dict) -> dict:
    instagram = post.get("ig") or {}
    disclosure = post.get("disclosure", "")
    user_prompt = (
        f"post_id: {post.get('id')}\n"
        f"declared_room_tag: {post.get('photo_tag', '')}\n"
        f"vision_room_type: {vision.get('room_type')}\n"
        f"vision_quality: {vision.get('quality')}\n"
        f"hook_en: {instagram.get('hook_en', '')}\n"
        f"caption_hi: {instagram.get('caption_hi', '')}\n"
        f"disclosure: {disclosure}\n"
        f"hashtags: {instagram.get('hashtags', '')}\n"
        "Judge strictly for qualified lead generation."
    )
    payload = {
        "model": DEEPSEEK_MODEL,
        "messages": [
            {"role": "system", "content": BUSINESS_SYSTEM},
            {"role": "user", "content": user_prompt},
        ],
        "response_format": {"type": "json_object"},
        "max_tokens": 500,
    }
    request = urllib.request.Request(
        DEEPSEEK_API,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=90) as response:
        data = json.load(response)
    result = extract_json(data["choices"][0]["message"]["content"])
    score = max(0, min(10, int(result.get("score", 0))))
    caption_match = bool(result.get("caption_match", False))
    cta_ok = bool(result.get("cta_ok", False))
    conversion_ok = bool(result.get("conversion_ok", False))
    passed = (
        bool(result.get("pass", False))
        and score >= 7
        and caption_match
        and cta_ok
        and conversion_ok
    )
    return {
        "score": score,
        "pass": passed,
        "reasons": result.get("reasons") or [],
        "caption_match": caption_match,
        "cta_ok": cta_ok,
        "conversion_ok": conversion_ok,
        "model": DEEPSEEK_MODEL,
    }


def rejected(reason: str, vision: dict | None = None) -> dict:
    return {
        "score": 0,
        "pass": False,
        "reasons": [reason],
        "visual_ok": False,
        "caption_match": False,
        "cta_ok": False,
        "conversion_ok": False,
        "vision": vision or {},
    }


def main() -> int:
    deepseek_key = (
        os.environ.get("DEEPSEEK_KEY") or os.environ.get("DEEPSEEK_API_KEY") or ""
    ).strip()
    gemini_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not deepseek_key or not gemini_key:
        print("Both DEEPSEEK_KEY and GEMINI_API_KEY are required; gate failed closed")
        return 1

    calendar = load_json("content/calendar.json", {"days": []})
    days = calendar.get("days") or []
    if not days:
        print("No candidates in content/calendar.json")
        return 1

    results = {
        "updated": datetime.now(IST).isoformat(),
        "pipeline": "Gemini Vision -> DeepSeek Business Gate",
        "vision_model": GEMINI_MODEL,
        "business_model": DEEPSEEK_MODEL,
        "posts": {},
    }
    technical_errors = 0

    for post in days:
        post_id = post.get("id")
        if not post_id:
            continue
        tag = str(post.get("photo_tag") or "").lower().strip()
        if tag in HARD_REJECT_TAGS:
            results["posts"][post_id] = rejected(f"hard_reject_tag:{tag}")
            print(post_id, "HARD REJECT", tag)
            continue

        try:
            vision = gemini_vision(gemini_key, str(post.get("image", "")))
            if not vision.get("visual_ok"):
                results["posts"][post_id] = rejected("gemini_visual_reject", vision)
                print(post_id, "VISUAL REJECT", vision.get("reasons"))
                continue
            business = deepseek_business(deepseek_key, post, vision)
            business["visual_ok"] = True
            business["vision"] = vision
            results["posts"][post_id] = business
            print(post_id, "score", business["score"], "pass", business["pass"])
        except Exception as error:
            technical_errors += 1
            results["posts"][post_id] = rejected(
                f"gate_error:{type(error).__name__}:{str(error)[:180]}"
            )
            print(post_id, "ERROR", type(error).__name__, error)

    save_json("data/gate_results.json", results)
    report = {
        post_id: {
            "score": gate.get("score", 0),
            "pass": gate.get("pass", False),
            "visual_ok": gate.get("visual_ok", False),
            "reasons": gate.get("reasons", []),
        }
        for post_id, gate in results["posts"].items()
    }
    save_json("data/business_report.json", report)

    passed = sum(1 for gate in results["posts"].values() if gate.get("pass"))
    print(f"Dual gate complete: {passed}/{len(results['posts'])} passed")
    if technical_errors == len(results["posts"]):
        print("All candidates failed because of technical gate errors")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
