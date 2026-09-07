#!/usr/bin/env python3
"""Run AURA3 approval queue with DeepSeek as the production AI provider.

Gemini is not required in this path. Until Bedrock/Nova is available, visual eligibility
uses the existing governed curated image pool and hard-reject tags; no model-based image
inspection is claimed.
"""
from __future__ import annotations

import json
import os
import re
import time
import urllib.request

os.environ.setdefault("GEMINI_API_KEY", "DISABLED_DEEPSEEK_PRIMARY")
os.environ.setdefault("DEEPSEEK_MODEL", "deepseek-v4-flash")

import generate_candidates as generator
import maintain_approval_queue as maintainer
import score_with_deepseek as quality_gate

DEEPSEEK_API = "https://api.deepseek.com/chat/completions"
JSON_RETRY_DELAYS = (1, 2, 4)


def _message_text(data: dict) -> str:
    """Extract visible assistant content without exposing reasoning content."""
    choices = data.get("choices") or []
    if not choices:
        return ""
    message = (choices[0] or {}).get("message") or {}
    content = message.get("content")
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict) and isinstance(item.get("text"), str):
                parts.append(item["text"])
        return "".join(parts).strip()
    return ""


def _parse_json_text(text: str):
    text = str(text or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text)
    if not text:
        raise ValueError("empty assistant content")
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        for pattern in (r"\{.*\}", r"\[.*\]"):
            match = re.search(pattern, text, re.DOTALL)
            if match:
                return json.loads(match.group(0))
        raise


def _deepseek_json(payload: dict, label: str) -> dict | list:
    """Call DeepSeek JSON mode with bounded semantic retries.

    V4 thinking is disabled intentionally for deterministic production JSON. DeepSeek's
    JSON mode can occasionally return empty content, so empty/invalid replies are retried.
    """
    last_error: Exception | None = None
    for attempt in range(len(JSON_RETRY_DELAYS) + 1):
        request = urllib.request.Request(
            DEEPSEEK_API,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {os.environ['DEEPSEEK_API_KEY']}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        data = quality_gate.post_json(request, "DeepSeek", timeout=120)
        try:
            return _parse_json_text(_message_text(data))
        except (ValueError, json.JSONDecodeError) as error:
            last_error = error
            if attempt == len(JSON_RETRY_DELAYS):
                break
            finish_reason = ((data.get("choices") or [{}])[0] or {}).get("finish_reason", "unknown")
            delay = JSON_RETRY_DELAYS[attempt]
            print(f"{label}: empty/invalid JSON; finish_reason={finish_reason}; retrying in {delay}s")
            time.sleep(delay)
            # Mildly strengthen the output instruction on retries without changing task meaning.
            messages = payload.get("messages") or []
            if messages and isinstance(messages[-1], dict):
                messages[-1]["content"] = str(messages[-1].get("content", "")) + "\nReturn a non-empty JSON object only."
    raise RuntimeError(f"{label}: DeepSeek did not return valid JSON") from last_error


def deepseek_generate(_unused_key: str, selected: list[dict]) -> tuple[list[dict], str]:
    api_key = (os.environ.get("DEEPSEEK_API_KEY") or os.environ.get("DEEPSEEK_KEY") or "").strip()
    if not api_key:
        raise RuntimeError("DEEPSEEK_API_KEY is required")
    os.environ["DEEPSEEK_API_KEY"] = api_key

    count = len(selected)
    if count < 1 or count > generator.CANDIDATE_COUNT:
        raise ValueError(f"DeepSeek candidate batch must contain 1-{generator.CANDIDATE_COUNT} image slots")
    inputs = [
        {
            "slot": i + 1,
            "room_tag": item.get("photo_tag", "interior"),
            "content_angle": item.get("angle", ""),
        }
        for i, item in enumerate(selected)
    ]
    prompt = (
        generator.SYSTEM_PROMPT
        + f"\n\nCreate exactly {count} items for these fixed image slots:\n"
        + json.dumps(inputs, ensure_ascii=False)
        + '\nReturn JSON only in this shape: {"candidates":[{"slot":1,"hook_en":"...","caption_hi":"...","hashtags":"#... #..."}]}. '
        + f"The candidates array must contain exactly {count} items and slots 1 through {count} exactly once."
    )
    model = os.environ.get("DEEPSEEK_MODEL", "deepseek-v4-flash")
    payload = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": "You are AURA3 production copy generation. Follow governance exactly and output valid JSON.",
            },
            {"role": "user", "content": prompt},
        ],
        "response_format": {"type": "json_object"},
        "thinking": {"type": "disabled"},
        "temperature": 0.2,
        "max_tokens": max(2200, 750 * count),
    }
    parsed = _deepseek_json(payload, "generation")
    candidates = parsed.get("candidates") if isinstance(parsed, dict) else parsed
    if not isinstance(candidates, list) or len(candidates) != count:
        raise RuntimeError("DeepSeek generator returned invalid candidate count")
    slots = {int(item.get("slot", 0)) for item in candidates if isinstance(item, dict)}
    if slots != set(range(1, count + 1)):
        raise RuntimeError("DeepSeek generator returned invalid slot coverage")
    return candidates, model


def deepseek_business(api_key: str, post: dict, vision: dict) -> dict:
    if not api_key:
        raise RuntimeError("DEEPSEEK_API_KEY is required for business gate")
    os.environ["DEEPSEEK_API_KEY"] = api_key
    instagram = post.get("ig") or {}
    user_prompt = (
        f"post_id: {post.get('id')}\n"
        f"declared_room_tag: {post.get('photo_tag', '')}\n"
        f"visual_room_type: {vision.get('room_type')}\n"
        f"visual_quality: {vision.get('quality')}\n"
        f"hook_en: {instagram.get('hook_en', '')}\n"
        f"caption_hi: {instagram.get('caption_hi', '')}\n"
        f"disclosure: {post.get('disclosure', '')}\n"
        f"hashtags: {instagram.get('hashtags', '')}\n"
        "Judge strictly for qualified lead generation and return JSON only."
    )
    model = os.environ.get("DEEPSEEK_MODEL", "deepseek-v4-flash")
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": quality_gate.BUSINESS_SYSTEM},
            {"role": "user", "content": user_prompt},
        ],
        "response_format": {"type": "json_object"},
        "thinking": {"type": "disabled"},
        "temperature": 0,
        "max_tokens": 700,
    }
    result = _deepseek_json(payload, "business_gate")
    if not isinstance(result, dict):
        raise RuntimeError("DeepSeek business gate returned non-object JSON")
    score = max(0, min(10, int(result.get("score", 0))))
    caption_match = bool(result.get("caption_match", False))
    cta_ok = bool(result.get("cta_ok", False))
    conversion_ok = bool(result.get("conversion_ok", False))
    passed = bool(result.get("pass", False)) and score >= 7 and caption_match and cta_ok and conversion_ok
    return {
        "score": score,
        "pass": passed,
        "reasons": result.get("reasons") or [],
        "caption_match": caption_match,
        "cta_ok": cta_ok,
        "conversion_ok": conversion_ok,
        "model": model,
    }


def deepseek_only_qualify_post(post: dict, _unused_gemini_key: str, deepseek_key: str) -> dict:
    tag = str(post.get("photo_tag") or "").lower().strip()
    if tag in quality_gate.HARD_REJECT_TAGS:
        return quality_gate.rejected(f"hard_reject_tag:{tag}")
    room_type = tag if tag in {"living", "kitchen", "bedroom", "bathroom", "dining", "office"} else "other"
    visual = {
        "visual_ok": True,
        "room_type": room_type,
        "quality": 7,
        "reasons": ["governed curated image-pool metadata gate; no vision-model inspection claimed"],
        "model": "CURATED_METADATA_GATE",
    }
    business = deepseek_business(deepseek_key, post, visual)
    business["visual_ok"] = True
    business["vision"] = visual
    return business


def _deepseek_refresh_gate_metadata(gate_results: dict, calendar: dict) -> None:
    gates = gate_results.setdefault("posts", {})
    gate_results.update({
        "updated": maintainer.datetime.now(maintainer.IST).isoformat(),
        "pipeline": "Curated metadata visual eligibility -> DeepSeek Business Gate",
        "vision_models": ["CURATED_METADATA_GATE"],
        "business_model": os.environ.get("DEEPSEEK_MODEL", "deepseek-v4-flash"),
        "batch_complete": all(
            str(post.get("id", "")) in gates
            for post in calendar.get("days", [])
            if post.get("id")
        ),
    })


_ORIGINAL_PERSIST_QUEUE_STATE = maintainer.persist_queue_state


def _deepseek_persist_queue_state(calendar: dict, gate_results: dict) -> None:
    _ORIGINAL_PERSIST_QUEUE_STATE(calendar, gate_results)
    model = os.environ.get("DEEPSEEK_MODEL", "deepseek-v4-flash")
    calendar["generator"] = f"DeepSeek {model} rolling queue maintainer"
    calendar["notes"] = (
        "Maintain up to 20 DeepSeek-gated posts awaiting Founder approval; one unique governed image per card. "
        "Visual eligibility currently uses curated metadata until Bedrock/Nova vision is enabled."
    )
    maintainer.save_json("content/calendar.json", calendar)


def main() -> int:
    generator.gemini_generate = deepseek_generate
    quality_gate.deepseek_business = deepseek_business
    quality_gate.GEMINI_MODELS = ("CURATED_METADATA_GATE",)
    maintainer.qualify_post = deepseek_only_qualify_post
    maintainer.refresh_gate_metadata = _deepseek_refresh_gate_metadata
    maintainer.persist_queue_state = _deepseek_persist_queue_state
    return maintainer.main()


if __name__ == "__main__":
    raise SystemExit(main())
