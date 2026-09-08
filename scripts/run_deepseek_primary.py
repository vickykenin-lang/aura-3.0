#!/usr/bin/env python3
"""Run AURA3 approval queue with DeepSeek as the production AI provider.

Operating pattern: choose a unique governed reference image, generate post copy, inspect the
actual image with a vision model, run an independent business/conversion gate, then place only
passing posts in the Founder approval queue. Gemini is not required; DeepSeek provides text and
vision capabilities. Temporary metadata-only visual approvals created during provider recovery
are automatically revalidated before the queue is maintained.
"""
from __future__ import annotations

import base64
import json
import os
import re
import time
import urllib.request

os.environ.setdefault("GEMINI_API_KEY", "DISABLED_DEEPSEEK_PRIMARY")
os.environ.setdefault("DEEPSEEK_MODEL", "deepseek-v4-flash")
os.environ.setdefault("DEEPSEEK_VISION_MODEL", "deepseek-v4-flash-vision-exp")

import generate_candidates as generator
import maintain_approval_queue as maintainer
import score_with_deepseek as quality_gate

DEEPSEEK_API = "https://api.deepseek.com/chat/completions"
DEEPSEEK_MODELS_API = "https://api.deepseek.com/models"
JSON_RETRY_DELAYS = (1, 2, 4)
VISION_ROOMS = {"living", "kitchen", "bedroom", "bathroom", "dining", "office", "other"}
TEMPORARY_VISUAL_MODELS = {"", "CURATED_METADATA_GATE"}
MAX_INTERNAL_MAINTAIN_CYCLES = 4
VISION_PROMPT = """Inspect this actual image for Design Infra, a Delhi NCR turnkey-interiors brand.
Return JSON only in this exact shape:
{"visual_ok":true,"room_type":"living|kitchen|bedroom|bathroom|dining|office|other","quality":0,"reasons":["..."]}

Set visual_ok=false for animals, wildlife, outdoor-only scenes, roads/railways, food-only
lifestyle, children, memes, unrelated stock, visible watermarks, severe blur, people-dominated
lifestyle images, or anything unsuitable for a premium interior-design Instagram post.
Use quality 0-10. A premium usable interior reference should normally score 6 or above."""


def _message_text(data: dict) -> str:
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


def _strengthen_json_instruction(payload: dict) -> None:
    messages = payload.get("messages") or []
    if not messages or not isinstance(messages[-1], dict):
        return
    content = messages[-1].get("content")
    instruction = "Return a non-empty JSON object only."
    if isinstance(content, str):
        messages[-1]["content"] = content + "\n" + instruction
    elif isinstance(content, list):
        content.append({"type": "text", "text": instruction})


def _deepseek_json(payload: dict, label: str) -> dict | list:
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
            _strengthen_json_instruction(payload)
    raise RuntimeError(f"{label}: DeepSeek did not return valid JSON") from last_error


def deepseek_provider_preflight(api_key: str) -> set[str]:
    if not api_key:
        raise RuntimeError("DEEPSEEK_API_KEY is required")
    request = urllib.request.Request(
        DEEPSEEK_MODELS_API,
        headers={"Authorization": f"Bearer {api_key}"},
        method="GET",
    )
    data = quality_gate.post_json(request, "DeepSeek", timeout=45)
    model_ids = {
        str(model.get("id"))
        for model in data.get("data", [])
        if isinstance(model, dict) and model.get("id")
    }
    required = {
        os.environ.get("DEEPSEEK_MODEL", "deepseek-v4-flash"),
        os.environ.get("DEEPSEEK_VISION_MODEL", "deepseek-v4-flash-vision-exp"),
    }
    missing = sorted(required - model_ids)
    if missing:
        available = ", ".join(sorted(model_ids)) or "none"
        raise RuntimeError(f"DeepSeek required model(s) unavailable: {missing}; available models: {available}")
    return model_ids


def deepseek_generate(_unused_key: str, selected: list[dict]) -> tuple[list[dict], str]:
    api_key = (os.environ.get("DEEPSEEK_API_KEY") or os.environ.get("DEEPSEEK_KEY") or "").strip()
    if not api_key:
        raise RuntimeError("DEEPSEEK_API_KEY is required")
    os.environ["DEEPSEEK_API_KEY"] = api_key
    count = len(selected)
    if count < 1 or count > generator.CANDIDATE_COUNT:
        raise ValueError(f"DeepSeek candidate batch must contain 1-{generator.CANDIDATE_COUNT} image slots")
    inputs = [
        {"slot": i + 1, "room_tag": item.get("photo_tag", "interior"), "content_angle": item.get("angle", "")}
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
            {"role": "system", "content": "You are AURA3 production copy generation. Follow governance exactly and output valid JSON."},
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


def deepseek_vision(api_key: str, image_url: str) -> dict:
    if not api_key:
        raise RuntimeError("DEEPSEEK_API_KEY is required for vision gate")
    if not str(image_url).startswith("https://"):
        raise RuntimeError("visual source must use HTTPS")
    os.environ["DEEPSEEK_API_KEY"] = api_key
    model = os.environ.get("DEEPSEEK_VISION_MODEL", "deepseek-v4-flash-vision-exp")
    mime_type, image_bytes = quality_gate.download_image(str(image_url))
    image_data_url = f"data:{mime_type};base64,{base64.b64encode(image_bytes).decode('ascii')}"
    payload = {
        "model": model,
        "messages": [{
            "role": "user",
            "content": [
                {"type": "text", "text": VISION_PROMPT},
                {"type": "image_url", "image_url": {"url": image_data_url}},
            ],
        }],
        "response_format": {"type": "json_object"},
        "thinking": {"type": "disabled"},
        "temperature": 0,
        "max_tokens": 500,
    }
    result = _deepseek_json(payload, "vision_gate")
    if not isinstance(result, dict):
        raise RuntimeError("DeepSeek vision gate returned non-object JSON")
    room_type = str(result.get("room_type", "other")).lower().strip()
    if room_type not in VISION_ROOMS:
        room_type = "other"
    try:
        quality = max(0, min(10, int(result.get("quality", 0))))
    except (TypeError, ValueError):
        quality = 0
    visual_ok = bool(result.get("visual_ok", False)) and quality >= 6
    reasons = result.get("reasons")
    if not isinstance(reasons, list):
        reasons = [str(reasons)] if reasons else []
    return {
        "visual_ok": visual_ok,
        "room_type": room_type,
        "quality": quality,
        "reasons": [str(reason) for reason in reasons],
        "model": model,
    }


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
    business_system = quality_gate.BUSINESS_SYSTEM.replace("AURA2", "AURA3").replace("Gemini Vision", "DeepSeek Vision")
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": business_system},
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


def deepseek_qualify_post(post: dict, _unused_gemini_key: str, deepseek_key: str) -> dict:
    tag = str(post.get("photo_tag") or "").lower().strip()
    if tag in quality_gate.HARD_REJECT_TAGS:
        return quality_gate.rejected(f"hard_reject_tag:{tag}")
    visual = deepseek_vision(deepseek_key, str(post.get("image", "")))
    if not visual.get("visual_ok"):
        return quality_gate.rejected("deepseek_visual_reject", visual)
    business = deepseek_business(deepseek_key, post, visual)
    business["visual_ok"] = True
    business["vision"] = visual
    return business


def _temporary_or_missing_visual_gate(gate: dict | None) -> bool:
    gate = gate or {}
    vision = gate.get("vision") or {}
    model = str(vision.get("model") or "").strip()
    return model in TEMPORARY_VISUAL_MODELS


def _deepseek_refresh_gate_metadata(gate_results: dict, calendar: dict) -> None:
    gates = gate_results.setdefault("posts", {})
    gate_results.update({
        "updated": maintainer.datetime.now(maintainer.IST).isoformat(),
        "pipeline": "DeepSeek Vision -> DeepSeek Business Gate",
        "vision_models": [os.environ.get("DEEPSEEK_VISION_MODEL", "deepseek-v4-flash-vision-exp")],
        "business_model": os.environ.get("DEEPSEEK_MODEL", "deepseek-v4-flash"),
        "batch_complete": all(str(post.get("id", "")) in gates for post in calendar.get("days", []) if post.get("id")),
    })


def revalidate_legacy_metadata_gates(deepseek_key: str) -> dict:
    """Replace temporary metadata-only evidence on still-pending posts with real vision evidence.

    Historical Gemini Vision evidence remains valid and is deliberately preserved. Published,
    approved/rejected, and otherwise Founder-decided posts are not mutated.
    """
    calendar = maintainer.load_json("content/calendar.json", {"days": []})
    approvals = maintainer.load_json("data/approvals.json", {})
    published = maintainer.load_json("content/published.json", {})
    gate_results = maintainer.load_json("data/gate_results.json", {"posts": {}})
    gates = gate_results.setdefault("posts", {})
    targets: list[dict] = []
    for post in calendar.get("days", []):
        post_id = str(post.get("id", "")).strip()
        if not post_id or maintainer.is_published(published, post_id):
            continue
        if maintainer.approval_state(approvals, post_id) != "pending":
            continue
        if _temporary_or_missing_visual_gate(gates.get(post_id)):
            targets.append(post)

    replacements: dict[str, dict] = {}
    passed = 0
    rejected = 0
    for post in targets:
        post_id = str(post["id"])
        result = deepseek_qualify_post(post, "", deepseek_key)
        replacements[post_id] = result
        if maintainer.gate_passed(result):
            passed += 1
        else:
            rejected += 1
        print(f"LEGACY VISUAL REVALIDATED: {post_id} -> {'PASS' if maintainer.gate_passed(result) else 'REJECT'}")

    gates.update(replacements)
    summary = {
        "status": "COMPLETE",
        "scanned_pending": sum(
            1
            for post in calendar.get("days", [])
            if post.get("id")
            and not maintainer.is_published(published, str(post.get("id")))
            and maintainer.approval_state(approvals, str(post.get("id"))) == "pending"
        ),
        "revalidated": len(targets),
        "passed": passed,
        "rejected": rejected,
        "vision_model": os.environ.get("DEEPSEEK_VISION_MODEL", "deepseek-v4-flash-vision-exp"),
        "preserved_historical_model_evidence": True,
        "observed_at": maintainer.datetime.now(maintainer.IST).isoformat(),
    }
    gate_results["legacy_visual_revalidation"] = summary
    _deepseek_refresh_gate_metadata(gate_results, calendar)
    maintainer.save_json("data/gate_results.json", gate_results)
    print(json.dumps({"legacy_visual_revalidation": summary}, ensure_ascii=False))
    return summary


_ORIGINAL_PERSIST_QUEUE_STATE = maintainer.persist_queue_state


def _deepseek_persist_queue_state(calendar: dict, gate_results: dict) -> None:
    _ORIGINAL_PERSIST_QUEUE_STATE(calendar, gate_results)
    model = os.environ.get("DEEPSEEK_MODEL", "deepseek-v4-flash")
    vision_model = os.environ.get("DEEPSEEK_VISION_MODEL", "deepseek-v4-flash-vision-exp")
    calendar["generator"] = f"DeepSeek {model} rolling queue maintainer"
    calendar["notes"] = (
        "Maintain up to 20 dual-gate-passed posts awaiting Founder approval; one unique governed image per card. "
        f"Actual image inspection: {vision_model}. Business gate: {model}."
    )
    maintainer.save_json("content/calendar.json", calendar)


def _run_bounded_maintainer_cycles() -> int:
    """Continue safe refill cycles when only the per-cycle generation limit was reached."""
    last_code = 1
    for cycle in range(1, MAX_INTERNAL_MAINTAIN_CYCLES + 1):
        last_code = maintainer.main()
        status = maintainer.load_json("data/approval_queue_status.json", {})
        ready = int(status.get("approval_ready", 0) or 0)
        target = int(status.get("target", 20) or 20)
        state = str(status.get("status") or "UNKNOWN")
        print(json.dumps({"internal_maintain_cycle": cycle, "status": state, "approval_ready": ready, "target": target, "exit_code": last_code}))
        if last_code == 0 or ready >= target:
            return 0
        can_continue = (
            state == "QUEUE_PARTIAL_MAX_ROUNDS"
            and not (status.get("technical_errors") or [])
            and int(status.get("unique_pool_available", 0) or 0) > 0
        )
        if not can_continue:
            return last_code
    return last_code


def main() -> int:
    deepseek_key = (os.environ.get("DEEPSEEK_API_KEY") or os.environ.get("DEEPSEEK_KEY") or "").strip()
    if not deepseek_key:
        print("REFILL BLOCKED: DEEPSEEK_API_KEY is required")
        return 1
    os.environ["DEEPSEEK_API_KEY"] = deepseek_key
    try:
        deepseek_provider_preflight(deepseek_key)
        revalidate_legacy_metadata_gates(deepseek_key)
    except Exception as error:
        print(f"REFILL BLOCKED: DeepSeek full provider/legacy visual revalidation failed: {type(error).__name__}")
        return 1

    generator.gemini_generate = deepseek_generate
    quality_gate.deepseek_business = deepseek_business
    quality_gate.GEMINI_MODELS = (os.environ.get("DEEPSEEK_VISION_MODEL", "deepseek-v4-flash-vision-exp"),)
    maintainer.qualify_post = deepseek_qualify_post
    maintainer.refresh_gate_metadata = _deepseek_refresh_gate_metadata
    maintainer.persist_queue_state = _deepseek_persist_queue_state
    return _run_bounded_maintainer_cycles()


if __name__ == "__main__":
    raise SystemExit(main())
