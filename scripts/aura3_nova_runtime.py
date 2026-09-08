#!/usr/bin/env python3
"""Amazon Nova 2 Lite runtime for AURA3 provider rotation."""
from __future__ import annotations

import json
import os
import re
import time
from typing import Any

import boto3
from botocore.exceptions import ClientError, ConnectTimeoutError, EndpointConnectionError, NoCredentialsError, ReadTimeoutError

import aura3_resilient_queue as resilient

DEFAULT_MODEL = "us.amazon.nova-2-lite-v1:0"
TRANSIENT_CODES = {"ThrottlingException", "TooManyRequestsException", "ServiceUnavailableException", "ModelTimeoutException", "ModelNotReadyException", "InternalServerException"}
RETRY_DELAYS = (5, 15, 30)


def model_id() -> str:
    return (os.environ.get("AWS_BEDROCK_MODEL_ID") or DEFAULT_MODEL).strip()


def _client():
    return boto3.client("bedrock-runtime", region_name=(os.environ.get("AWS_REGION") or "us-east-1").strip())


def _extract_text(response: dict) -> str:
    parts = (((response.get("output") or {}).get("message") or {}).get("content") or [])
    text = "".join(str(part.get("text", "")) for part in parts if isinstance(part, dict)).strip()
    if not text:
        raise RuntimeError(f"Nova returned no text; stop_reason={response.get('stopReason','unknown')}")
    return text


def _parse_json(text: str) -> Any:
    text = str(text or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.I)
        text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        for pattern in (r"\{.*\}", r"\[.*\]"):
            match = re.search(pattern, text, re.S)
            if match:
                return json.loads(match.group(0))
        raise


def _converse(messages: list[dict], *, system: str = "", max_tokens: int = 1200, temperature: float = 0.0) -> Any:
    last: Exception | None = None
    for attempt in range(len(RETRY_DELAYS) + 1):
        try:
            kwargs = {
                "modelId": model_id(),
                "messages": messages,
                "inferenceConfig": {"maxTokens": max_tokens, "temperature": temperature},
            }
            if system:
                kwargs["system"] = [{"text": system}]
            response = _client().converse(**kwargs)
            return _parse_json(_extract_text(response))
        except ClientError as exc:
            last = exc
            code = (exc.response.get("Error") or {}).get("Code", "")
            if code not in TRANSIENT_CODES or attempt == len(RETRY_DELAYS):
                raise
        except (EndpointConnectionError, ReadTimeoutError, ConnectTimeoutError) as exc:
            last = exc
            if attempt == len(RETRY_DELAYS):
                raise
        except NoCredentialsError:
            raise
        if attempt < len(RETRY_DELAYS):
            time.sleep(RETRY_DELAYS[attempt])
    raise last or RuntimeError("Nova request exhausted retries")


def preflight(_unused_key: str = "") -> set[str]:
    if not (os.environ.get("AWS_ACCESS_KEY_ID") or "").strip() or not (os.environ.get("AWS_SECRET_ACCESS_KEY") or "").strip():
        raise RuntimeError("AWS credentials are required for Nova rotation cycle")
    result = _converse([{"role": "user", "content": [{"text": "Return JSON only: {\"ok\":true}"}]}], max_tokens=40)
    if not isinstance(result, dict) or not result.get("ok"):
        raise RuntimeError("Nova preflight returned unexpected payload")
    return {model_id()}


def strict_vision(_api_key: str, image_url: str) -> dict:
    if resilient._is_blacklisted(image_url):
        raise ValueError("image is persistently blacklisted")
    if image_url in resilient._VISUAL_CACHE:
        cached = dict(resilient._VISUAL_CACHE[image_url])
        if str(cached.get("model", "")).startswith("us.amazon.nova"):
            return cached
    mime, image_bytes = resilient._download_with_retry(image_url)
    fmt = {"image/jpeg": "jpeg", "image/png": "png", "image/webp": "webp"}.get(mime)
    if not fmt:
        raise ValueError(f"unsupported image content type: {mime}")
    prompt = resilient.build_vision_prompt(resilient.load_rulebook())
    result = _converse([{"role": "user", "content": [
        {"image": {"format": fmt, "source": {"bytes": image_bytes}}},
        {"text": prompt},
    ]}], max_tokens=1400)
    if not isinstance(result, dict):
        raise RuntimeError("Nova vision returned non-object JSON")
    min_score = int((resilient.load_rulebook().get("quality") or {}).get("minimum_visual_quality_score", 7))
    try:
        quality = max(0, min(10, int(result.get("quality", 0))))
    except (TypeError, ValueError):
        quality = 0
    freshness = str(result.get("design_freshness", "Unclear")).title()
    status = str(result.get("status", "DO_NOT_POST")).upper()
    watermarks = str(result.get("watermarks", "Present"))
    copyright_status = str(result.get("copyright_status", "Unknown"))
    logo_risk = str(result.get("brand_logo_risk", "Unclear"))
    legal_block = watermarks.lower() != "none" or copyright_status.lower() == "flagged" or logo_risk.lower() == "present"
    visual_ok = bool(result.get("visual_ok")) and status == "APPROVED" and quality >= min_score and freshness == "Current" and not legal_block
    normalized = {
        "visual_ok": visual_ok,
        "status": "APPROVED" if visual_ok else ("NEEDS_REVISION" if status == "NEEDS_REVISION" else "DO_NOT_POST"),
        "room_type": str(result.get("room_type", "other")).lower(),
        "quality": quality,
        "brightness_level": str(result.get("brightness_level", "Unknown")),
        "composition": str(result.get("composition", "")),
        "color_accuracy": str(result.get("color_accuracy", "Unknown")),
        "design_freshness": freshness,
        "copyright_status": copyright_status,
        "watermarks": watermarks,
        "brand_logo_risk": logo_risk,
        "primary_category": str(result.get("primary_category", "")),
        "design_concepts": resilient._as_list(result.get("design_concepts")),
        "style": str(result.get("style", "")),
        "visible_features": resilient._as_list(result.get("visible_features")),
        "sample_caption_angle": str(result.get("sample_caption_angle", "")),
        "reasons": resilient._as_list(result.get("reasons")),
        "rulebook": "governance/image_validation_rulebook.json",
        "resilience_rulebook_version": resilient.RESILIENCE_VERSION,
        "model": model_id(),
    }
    resilient._VISUAL_CACHE[image_url] = normalized
    if not visual_ok:
        resilient._mark_blacklisted(image_url, f"NOVA_VISUAL_REJECT_{freshness.upper()}", "nova_vision_gate")
        resilient._record_incident("NOVA_IMG_VISUAL_REJECT", "vision", f"freshness={freshness};quality={quality}", image_url)
    return dict(normalized)


def image_grounded_generate(_unused_key: str, selected: list[dict]) -> tuple[list[dict], str]:
    requested = len(selected)
    queue = [x for x in selected if not resilient._is_blacklisted(str(x.get("image", "")))]
    seen = {resilient._image_key(str(x.get("image", ""))) for x in queue}
    for candidate in resilient._fresh_candidates():
        key = resilient._image_key(str(candidate.get("image", "")))
        if key and key not in seen:
            queue.append(candidate)
            seen.add(key)
    validated, enriched = [], []
    for item in queue:
        if len(validated) >= requested:
            break
        url = str(item.get("image", ""))
        try:
            vision = strict_vision("", url)
        except Exception as exc:
            resilient._record_incident("NOVA_VISUAL_SOURCE_SKIP", "vision", type(exc).__name__, url)
            continue
        if not vision.get("visual_ok"):
            continue
        features = ", ".join(vision.get("visible_features") or [])
        concepts = ", ".join(vision.get("design_concepts") or [])
        angle = (
            f"ACTUAL IMAGE EVIDENCE ONLY: room={vision.get('room_type')}; style={vision.get('style')}; "
            f"concepts={concepts}; visible_features={features}; caption_angle={vision.get('sample_caption_angle')}. "
            "Hook and caption must use these visible facts only; never invent a material, feature or room function."
        )
        validated.append(item)
        enriched.append({**item, "angle": angle})
    selected[:] = validated
    if not enriched:
        return [], ""
    count = len(enriched)
    inputs = [{"slot": i + 1, "room_tag": x.get("photo_tag", "interior"), "content_angle": x.get("angle", "")} for i, x in enumerate(enriched)]
    prompt = resilient.core.generator.SYSTEM_PROMPT + "\n\nCreate exactly " + str(count) + " items for these fixed image slots:\n" + json.dumps(inputs, ensure_ascii=False) + "\nReturn ONLY a raw JSON array with exactly one object per slot: {\"slot\":1,\"hook_en\":\"...\",\"caption_hi\":\"...\",\"hashtags\":\"#... #...\"}."
    generated = _converse([{"role": "user", "content": [{"text": prompt}]}], system="You are AURA3 production copy generation. Follow governance exactly.", max_tokens=max(1800, 700 * count), temperature=0.2)
    if isinstance(generated, dict):
        generated = generated.get("candidates") or generated.get("items") or generated.get("posts")
    if not isinstance(generated, list) or len(generated) != count:
        raise RuntimeError("Nova generator returned invalid candidate count")
    slots = {int(x.get("slot", 0)) for x in generated if isinstance(x, dict)}
    if slots != set(range(1, count + 1)):
        raise RuntimeError("Nova generator returned invalid slot coverage")
    return generated, model_id()


def _semantic_caption_check(post: dict, vision: dict) -> dict:
    ig = post.get("ig") or {}
    prompt = (
        "You are AURA3 caption-to-image semantic validator. Compare caption only against actual-image evidence. "
        "Return JSON only: {\"score\":0-10,\"grounded\":true/false,\"contradictions\":[\"...\"],\"reasons\":[\"...\"]}. "
        "Score >=7 requires clear grounding in visible facts and no invented materials/features.\n"
        f"room={vision.get('room_type')}\nstyle={vision.get('style')}\nvisible_features={vision.get('visible_features')}\n"
        f"caption_angle={vision.get('sample_caption_angle')}\nhook={ig.get('hook_en','')}\ncaption={ig.get('caption_hi','')}"
    )
    result = _converse([{"role": "user", "content": [{"text": prompt}]}], max_tokens=500)
    if not isinstance(result, dict):
        raise RuntimeError("Nova semantic gate returned non-object JSON")
    try:
        score = max(0, min(10, int(result.get("score", 0))))
    except (TypeError, ValueError):
        score = 0
    contradictions = resilient._as_list(result.get("contradictions"))
    grounded = bool(result.get("grounded")) and score >= resilient.SEMANTIC_MIN_SCORE and not contradictions
    return {"score": score, "grounded": grounded, "contradictions": contradictions, "reasons": resilient._as_list(result.get("reasons"))}


def business(_api_key: str, post: dict, vision: dict) -> dict:
    ig = post.get("ig") or {}
    prompt = (
        "You are AURA3's independent business/conversion gate for Design Infra, a premium turnkey-interiors company in Delhi NCR. "
        "Judge caption-to-room match, honest positioning, conversion signal (price/timeline/process/inclusions), CTA and lead potential. "
        "Return JSON only: {\"score\":0-10,\"pass\":true/false,\"reasons\":[\"...\"],\"caption_match\":true/false,\"cta_ok\":true/false,\"conversion_ok\":true/false}. "
        "PASS requires score>=7, caption match, CTA, conversion signal and no claim that reference image is completed Design Infra work.\n"
        f"post_id={post.get('id')}\nroom={vision.get('room_type')}\nquality={vision.get('quality')}\nhook={ig.get('hook_en','')}\ncaption={ig.get('caption_hi','')}\n"
        f"hashtags={ig.get('hashtags','')}\ndisclosure={post.get('disclosure','')}"
    )
    result = _converse([{"role": "user", "content": [{"text": prompt}]}], max_tokens=700)
    if not isinstance(result, dict):
        raise RuntimeError("Nova business gate returned non-object JSON")
    try:
        score = max(0, min(10, int(result.get("score", 0))))
    except (TypeError, ValueError):
        score = 0
    caption_match = bool(result.get("caption_match"))
    cta_ok = bool(result.get("cta_ok"))
    conversion_ok = bool(result.get("conversion_ok"))
    semantic = _semantic_caption_check(post, vision)
    caption_match = caption_match and semantic["grounded"]
    passed = bool(result.get("pass")) and score >= 7 and caption_match and cta_ok and conversion_ok
    return {
        "score": score,
        "pass": passed,
        "reasons": resilient._as_list(result.get("reasons")),
        "caption_match": caption_match,
        "cta_ok": cta_ok,
        "conversion_ok": conversion_ok,
        "caption_semantic": semantic,
        "model": model_id(),
    }


def install_into_resilient_runtime() -> None:
    resilient.strict_vision = strict_vision
    resilient.image_grounded_generate = image_grounded_generate
    resilient.resilient_business = business
    resilient.core.deepseek_provider_preflight = preflight

    def refresh_metadata(gate_results: dict, calendar: dict) -> None:
        gates = gate_results.setdefault("posts", {})
        gate_results.update({
            "updated": resilient.core.maintainer.datetime.now(resilient.core.maintainer.IST).isoformat(),
            "pipeline": "Amazon Nova Vision -> Amazon Nova Business Gate",
            "vision_models": [model_id()],
            "business_model": model_id(),
            "active_provider": "aws_bedrock_nova",
            "batch_complete": all(str(post.get("id", "")) in gates for post in calendar.get("days", []) if post.get("id")),
        })

    resilient.core._deepseek_refresh_gate_metadata = refresh_metadata
    original_persist = resilient.core._ORIGINAL_PERSIST_QUEUE_STATE

    def persist(calendar: dict, gate_results: dict) -> None:
        original_persist(calendar, gate_results)
        calendar["generator"] = f"Amazon Nova {model_id()} rolling queue maintainer"
        calendar["notes"] = "Alternating-provider cycle. Actual image inspection, image-grounded caption, semantic gate and business gate all executed with Amazon Nova on this cycle."
        refresh_metadata(gate_results, calendar)
        resilient.core.maintainer.save_json("content/calendar.json", calendar)
        resilient.core.maintainer.save_json("data/gate_results.json", gate_results)

    resilient.core._deepseek_persist_queue_state = persist
