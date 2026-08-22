#!/usr/bin/env python3
"""AURA2 dual quality gate: Gemini sees the image, DeepSeek judges conversion."""

from __future__ import annotations

import base64
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
DEEPSEEK_API = "https://api.deepseek.com/chat/completions"
DEEPSEEK_MODELS_API = "https://api.deepseek.com/models"
DEEPSEEK_MODEL = os.environ.get("DEEPSEEK_MODEL") or "deepseek-v4-flash"
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
MAX_IMAGE_BYTES = 8 * 1024 * 1024
RETRYABLE_HTTP_CODES = {429, 500, 502, 503, 504}
RETRY_DELAYS_SECONDS = (2, 5)
SEMANTIC_RETRY_DELAYS_SECONDS = (1, 2, 4, 8)
ACTIVE_GEMINI_MODEL = ""

VISION_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "visual_ok": {"type": "BOOLEAN"},
        "room_type": {
            "type": "STRING",
            "enum": ["living", "kitchen", "bedroom", "bathroom", "dining", "office", "other"],
        },
        "quality": {"type": "INTEGER", "minimum": 0, "maximum": 10},
        "reasons": {"type": "ARRAY", "items": {"type": "STRING"}},
    },
    "required": ["visual_ok", "room_type", "quality", "reasons"],
}

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
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if not match:
            raise ValueError("model reply did not contain JSON")
        return json.loads(match.group(0))


def post_json(request: urllib.request.Request, provider: str, timeout: int = 90) -> dict:
    for attempt in range(len(RETRY_DELAYS_SECONDS) + 1):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return json.load(response)
        except urllib.error.HTTPError as error:
            detail = error.read().decode("utf-8", errors="replace")[:500]
            if error.code not in RETRYABLE_HTTP_CODES or attempt == len(RETRY_DELAYS_SECONDS):
                raise RuntimeError(f"{provider} HTTP {error.code}: {detail}") from error
            delay = RETRY_DELAYS_SECONDS[attempt]
            print(f"{provider} HTTP {error.code}; retrying in {delay}s")
            time.sleep(delay)
        except urllib.error.URLError as error:
            if attempt == len(RETRY_DELAYS_SECONDS):
                raise RuntimeError(f"{provider} network error: {error.reason}") from error
            delay = RETRY_DELAYS_SECONDS[attempt]
            print(f"{provider} network error; retrying in {delay}s")
            time.sleep(delay)
    raise RuntimeError(f"{provider} request exhausted retries")


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


def gemini_response_text(data: dict) -> str:
    """Return text from a Gemini response or raise a diagnostic-safe error."""
    candidates = data.get("candidates") or []
    if not candidates:
        block_reason = (data.get("promptFeedback") or {}).get("blockReason", "unknown")
        raise RuntimeError(f"Gemini returned no candidates; block_reason={block_reason}")

    candidate = candidates[0] or {}
    parts = (candidate.get("content") or {}).get("parts") or []
    text = "".join(str(part.get("text", "")) for part in parts if isinstance(part, dict)).strip()
    if not text:
        finish_reason = candidate.get("finishReason", "unknown")
        raise RuntimeError(f"Gemini returned no text; finish_reason={finish_reason}")
    return text


def deepseek_preflight(api_key: str) -> None:
    """Fail before image scoring when the DeepSeek key or model is unusable."""
    request = urllib.request.Request(
        DEEPSEEK_MODELS_API,
        headers={"Authorization": f"Bearer {api_key}"},
        method="GET",
    )
    data = post_json(request, "DeepSeek", timeout=45)
    model_ids = {
        str(model.get("id"))
        for model in data.get("data", [])
        if isinstance(model, dict) and model.get("id")
    }
    if DEEPSEEK_MODEL not in model_ids:
        available = ", ".join(sorted(model_ids)) or "none"
        raise RuntimeError(
            f"DeepSeek model {DEEPSEEK_MODEL!r} is unavailable; available models: {available}"
        )


def gemini_vision(api_key: str, image_url: str) -> dict:
    global ACTIVE_GEMINI_MODEL
    mime_type, image = download_image(image_url)
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
            "responseSchema": VISION_SCHEMA,
            "maxOutputTokens": 400,
        },
    }
    data = None
    result = None
    used_model = ""
    model_order = tuple(dict.fromkeys(model for model in (ACTIVE_GEMINI_MODEL, *GEMINI_MODELS) if model))
    last_error = None
    for index, model in enumerate(model_order):
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
        for response_attempt in range(len(SEMANTIC_RETRY_DELAYS_SECONDS) + 1):
            try:
                data = post_json(request, "Gemini")
                text = gemini_response_text(data)
                result = extract_json(text)
                used_model = model
                break
            except (ValueError, json.JSONDecodeError) as error:
                last_error = error
                if response_attempt == len(SEMANTIC_RETRY_DELAYS_SECONDS):
                    break
                delay = SEMANTIC_RETRY_DELAYS_SECONDS[response_attempt]
                print(
                    f"Gemini model {model} returned invalid JSON; "
                    f"retrying response in {delay}s"
                )
                time.sleep(delay)
            except RuntimeError as error:
                last_error = error
                response_shape_error = any(
                    marker in str(error)
                    for marker in ("Gemini returned no candidates", "Gemini returned no text")
                )
                if (
                    response_shape_error
                    and response_attempt < len(SEMANTIC_RETRY_DELAYS_SECONDS)
                ):
                    delay = SEMANTIC_RETRY_DELAYS_SECONDS[response_attempt]
                    print(
                        f"Gemini model {model} returned an empty response; "
                        f"retrying response in {delay}s"
                    )
                    time.sleep(delay)
                    continue
                break

        if result is not None:
            break

        error = last_error or RuntimeError("Gemini response could not be parsed")
        if error:
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
                    "Gemini returned no candidates",
                    "Gemini returned no text",
                    "model reply did not contain JSON",
                )
            )
            if not fallback_error or index == len(model_order) - 1:
                raise error
            print(
                f"Gemini model {model} returned an unusable response; "
                f"trying {model_order[index + 1]}"
            )
    if data is None or result is None:
        raise RuntimeError("No Gemini vision model was available") from last_error
    ACTIVE_GEMINI_MODEL = used_model
    quality = max(0, min(10, int(result.get("quality", 0))))
    return {
        "visual_ok": bool(result.get("visual_ok", False)) and quality >= 6,
        "room_type": str(result.get("room_type", "other")),
        "quality": quality,
        "reasons": result.get("reasons") or [],
        "model": used_model,
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
    data = post_json(request, "DeepSeek")
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

    try:
        deepseek_preflight(deepseek_key)
    except Exception as error:
        print(f"DEEPSEEK PREFLIGHT FAILED: {type(error).__name__}: {error}")
        if "DeepSeek HTTP 401" in str(error):
            print("DeepSeek authentication failed; update the DEEPSEEK_KEY repository secret")
        return 1

    calendar = load_json("content/calendar.json", {"days": []})
    days = calendar.get("days") or []
    if not days:
        print("No candidates in content/calendar.json")
        return 1

    results = {
        "updated": datetime.now(IST).isoformat(),
        "pipeline": "Gemini Vision -> DeepSeek Business Gate",
        "vision_models": list(GEMINI_MODELS),
        "business_model": DEEPSEEK_MODEL,
        "batch_complete": False,
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
            if "DeepSeek HTTP 401" in str(error):
                print("DeepSeek authentication failed; update the DEEPSEEK_KEY repository secret")
                break

    results["batch_complete"] = (
        technical_errors == 0 and len(results["posts"]) == len(days)
    )
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
    if technical_errors:
        print(
            f"Batch incomplete: {technical_errors} candidate(s) had technical gate errors; "
            "no authoritative batch result will be committed"
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
