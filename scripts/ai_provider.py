#!/usr/bin/env python3
"""Minimal AI provider adapter for AURA3.

PRIMARY_PROVIDER=aws_bedrock_nova (default): AWS Bedrock / Amazon Nova handles
content generation, multimodal visual qualification, and the business gate.

AI_FALLBACK_PROVIDER=gemini (opt-in, default "none"): if the AWS primary
raises a hard (non-transient) provider error, fall back to the existing
Gemini implementations in generate_candidates.py / score_with_deepseek.py for
generation and vision. Fallback is intentionally NOT enabled by default:
Gemini is currently hard blocked on provider billing, so silently retrying it
would waste requests. Enable it only once Gemini's provider health is
actually restored. The business gate has no fallback: it is fully decided by
AWS Bedrock now that DeepSeek has been removed from the pipeline.

This module intentionally does not import generate_candidates or
score_with_deepseek at module load time: those modules may in turn end up
depending on this one (directly or via monkeypatching in
run_approval_queue.py), so cross-module lookups are done lazily inside the
functions that need them. This keeps the adapter a thin swap-in for the
existing Gemini/DeepSeek call sites without touching their own business-copy
or vision logic.
"""

from __future__ import annotations

import json
import os
import re
from typing import Any

import boto3
from botocore.exceptions import (
    ClientError,
    EndpointConnectionError,
    NoCredentialsError,
    ReadTimeoutError,
    ConnectTimeoutError,
)

CANDIDATE_COUNT = 10
DEFAULT_AWS_REGION = "us-east-1"
DEFAULT_AWS_MODEL_ID = "us.amazon.nova-2-lite-v1:0"

TRANSIENT_ERROR_CODES = {
    "ThrottlingException",
    "TooManyRequestsException",
    "ServiceUnavailableException",
    "ModelTimeoutException",
    "ModelNotReadyException",
    "InternalServerException",
}

HARD_ERROR_CODES = {
    "AccessDeniedException",
    "UnauthorizedException",
    "UnrecognizedClientException",
    "InvalidSignatureException",
    "ExpiredTokenException",
    "ValidationException",
    "ResourceNotFoundException",
    "ModelErrorException",
}

IMAGE_FORMAT_BY_MIME = {
    "image/jpeg": "jpeg",
    "image/png": "png",
    "image/webp": "webp",
}

BUSINESS_SYSTEM_PROMPT = """You are the independent AURA2 business quality gate for Design Infra,
a premium turnkey-interiors company in Delhi NCR. The actual image has already been inspected by
a vision model. Judge caption-to-room match, honest brand positioning, conversion signal
(price/timeline/process/inclusions), CTA, and lead-generation potential.

Return only valid JSON:
{"score":0-10,"pass":true/false,"reasons":["..."],"caption_match":true/false,"cta_ok":true/false,"conversion_ok":true/false}

PASS requires score >= 7, caption match, CTA, conversion signal, and no misleading claim that a
stock/reference image is Design Infra's completed work."""


class ProviderTransientError(RuntimeError):
    """Retryable provider condition: throttling, timeout, temporary outage, network issue."""


class ProviderHardError(RuntimeError):
    """Non-retryable provider condition: bad credentials, access/model disabled, billing/config block."""


def _primary_provider() -> str:
    return (os.environ.get("PRIMARY_PROVIDER") or "aws_bedrock_nova").strip().lower()


def primary_provider_name() -> str:
    """Public accessor for other modules that just want the configured provider label."""
    return _primary_provider()


def model_id_in_use() -> str:
    """Public accessor reporting the model identifier actually driving the primary provider."""
    if _primary_provider() == "aws_bedrock_nova":
        return _aws_model_id()
    return "gemini"


def _fallback_provider() -> str:
    return (os.environ.get("AI_FALLBACK_PROVIDER") or "none").strip().lower()


def _aws_region() -> str:
    return (os.environ.get("AWS_REGION") or DEFAULT_AWS_REGION).strip()


def _aws_model_id() -> str:
    return (os.environ.get("AWS_BEDROCK_MODEL_ID") or DEFAULT_AWS_MODEL_ID).strip()


def _generator_module():
    import generate_candidates  # deferred: avoids a load-time import cycle

    return generate_candidates


def _score_module():
    import score_with_deepseek  # deferred: avoids a load-time import cycle

    return score_with_deepseek


def _bedrock_client():
    return boto3.client("bedrock-runtime", region_name=_aws_region())


def _classify_client_error(error: Exception, context: str) -> Exception:
    if isinstance(error, NoCredentialsError):
        return ProviderHardError(f"{context}: AWS credentials not found/configured")
    if isinstance(error, (ReadTimeoutError, ConnectTimeoutError, EndpointConnectionError)):
        return ProviderTransientError(f"{context}: network error: {error}")
    if isinstance(error, ClientError):
        code = error.response.get("Error", {}).get("Code", "")
        message = error.response.get("Error", {}).get("Message", str(error))
        if code in TRANSIENT_ERROR_CODES:
            return ProviderTransientError(f"{context} {code}: {message}")
        if code in HARD_ERROR_CODES:
            return ProviderHardError(f"{context} {code}: {message}")
        lowered = message.lower()
        if "not authorized" in lowered or "access denied" in lowered or "disabled" in lowered:
            return ProviderHardError(f"{context} {code or 'AccessDenied'}: {message}")
        # Unknown Bedrock error code: fail closed rather than silently retrying
        # or silently downgrading quality standards.
        return ProviderHardError(f"{context} {code or 'UnknownClientError'}: {message}")
    return ProviderHardError(f"{context}: {type(error).__name__}: {error}")


def _extract_converse_text(response: dict) -> str:
    message = (response.get("output") or {}).get("message") or {}
    parts = message.get("content") or []
    text = "".join(str(part.get("text", "")) for part in parts if isinstance(part, dict)).strip()
    if not text:
        stop_reason = response.get("stopReason", "unknown")
        raise ValueError(f"AWS Bedrock returned no text; stop_reason={stop_reason}")
    return text


def _strip_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text)
    return text


def _extract_json_array(text: str) -> Any:
    text = _strip_fences(text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\[.*\]", text, re.DOTALL)
        if not match:
            raise ValueError("AWS Bedrock reply did not contain a JSON array")
        return json.loads(match.group(0))


def _extract_json_object(text: str) -> dict:
    text = _strip_fences(text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if not match:
            raise ValueError("AWS Bedrock reply did not contain a JSON object")
        return json.loads(match.group(0))


def _aws_bedrock_generate_content(selected: list[dict]) -> tuple[list[dict], str]:
    count = len(selected)
    if count < 1 or count > CANDIDATE_COUNT:
        raise ValueError(f"AWS Bedrock candidate batch must contain 1-{CANDIDATE_COUNT} image slots")

    system_prompt = _generator_module().SYSTEM_PROMPT
    inputs = [
        {"slot": index + 1, "room_tag": item["photo_tag"], "content_angle": item["angle"]}
        for index, item in enumerate(selected)
    ]
    prompt = (
        system_prompt
        + f"\n\nCreate exactly {count} items for these fixed image slots:\n"
        + json.dumps(inputs, ensure_ascii=False)
        + "\n\nReturn ONLY a raw JSON array, no prose, no markdown fences. "
        'Each object must be exactly: {"slot":1,"hook_en":"...","caption_hi":"...","hashtags":"#... #..."}'
    )

    model_id = _aws_model_id()
    try:
        client = _bedrock_client()
        response = client.converse(
            modelId=model_id,
            messages=[{"role": "user", "content": [{"text": prompt}]}],
            inferenceConfig={"maxTokens": max(1200, 800 * count), "temperature": 0.4},
        )
    except (ClientError, EndpointConnectionError, NoCredentialsError, ReadTimeoutError, ConnectTimeoutError) as error:
        raise _classify_client_error(error, "AWS Bedrock generation") from error

    text = _extract_converse_text(response)
    try:
        generated = _extract_json_array(text)
    except (ValueError, json.JSONDecodeError) as error:
        preview = re.sub(r"\s+", " ", text)[:400]
        raise ValueError(f"AWS Bedrock invalid structured reply: {error}; preview={preview!r}") from error

    if not isinstance(generated, list) or len(generated) != count:
        raise ValueError(f"AWS Bedrock must return exactly {count} candidates")
    return generated, model_id


def _aws_bedrock_analyze_image(image_url: str) -> dict:
    download_image = _score_module().download_image
    vision_prompt_base = _score_module().VISION_PROMPT
    mime_type, image_bytes = download_image(image_url)
    image_format = IMAGE_FORMAT_BY_MIME.get(mime_type)
    if not image_format:
        raise ValueError(f"unsupported image content type for Bedrock: {mime_type}")

    vision_prompt = (
        vision_prompt_base
        + "\n\nReturn ONLY a raw JSON object, no prose, no markdown fences, exactly: "
        '{"visual_ok":true/false,"room_type":"living|kitchen|bedroom|bathroom|dining|office|other",'
        '"quality":0-10,"reasons":["..."]}'
    )

    model_id = _aws_model_id()
    try:
        client = _bedrock_client()
        response = client.converse(
            modelId=model_id,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"image": {"format": image_format, "source": {"bytes": image_bytes}}},
                        {"text": vision_prompt},
                    ],
                }
            ],
            inferenceConfig={"maxTokens": 400, "temperature": 0},
        )
    except (ClientError, EndpointConnectionError, NoCredentialsError, ReadTimeoutError, ConnectTimeoutError) as error:
        raise _classify_client_error(error, "AWS Bedrock vision") from error

    text = _extract_converse_text(response)
    try:
        result = _extract_json_object(text)
    except (ValueError, json.JSONDecodeError) as error:
        preview = re.sub(r"\s+", " ", text)[:400]
        raise ValueError(f"AWS Bedrock invalid vision reply: {error}; preview={preview!r}") from error

    quality = max(0, min(10, int(result.get("quality", 0))))
    return {
        "visual_ok": bool(result.get("visual_ok", False)) and quality >= 6,
        "room_type": str(result.get("room_type", "other")),
        "quality": quality,
        "reasons": result.get("reasons") or [],
        "model": model_id,
    }


def _aws_bedrock_evaluate_business(post: dict, vision: dict) -> dict:
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
    prompt = (
        BUSINESS_SYSTEM_PROMPT
        + "\n\n"
        + user_prompt
        + "\n\nReturn ONLY a raw JSON object, no prose, no markdown fences, exactly: "
        '{"score":0-10,"pass":true/false,"reasons":["..."],"caption_match":true/false,'
        '"cta_ok":true/false,"conversion_ok":true/false}'
    )

    model_id = _aws_model_id()
    try:
        client = _bedrock_client()
        response = client.converse(
            modelId=model_id,
            messages=[{"role": "user", "content": [{"text": prompt}]}],
            inferenceConfig={"maxTokens": 500, "temperature": 0},
        )
    except (ClientError, EndpointConnectionError, NoCredentialsError, ReadTimeoutError, ConnectTimeoutError) as error:
        raise _classify_client_error(error, "AWS Bedrock business gate") from error

    text = _extract_converse_text(response)
    try:
        result = _extract_json_object(text)
    except (ValueError, json.JSONDecodeError) as error:
        preview = re.sub(r"\s+", " ", text)[:400]
        raise ValueError(f"AWS Bedrock invalid business-gate reply: {error}; preview={preview!r}") from error

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
        "model": model_id,
    }


def generate_content(selected: list[dict]) -> tuple[list[dict], str]:
    """Provider-agnostic replacement for generate_candidates.gemini_generate.

    Returns (generated_items, used_model) with the exact same slot/hook_en/
    caption_hi/hashtags contract the rest of the pipeline already validates.
    """
    primary = _primary_provider()
    if primary == "aws_bedrock_nova":
        try:
            return _aws_bedrock_generate_content(selected)
        except ProviderHardError:
            if _fallback_provider() == "gemini":
                gemini_key = (os.environ.get("GEMINI_API_KEY") or "").strip()
                if gemini_key:
                    generated, used_model = _generator_module().gemini_generate(gemini_key, selected)
                    return generated, f"gemini-fallback:{used_model}"
            raise
    if primary == "gemini":
        gemini_key = (os.environ.get("GEMINI_API_KEY") or "").strip()
        if not gemini_key:
            raise ProviderHardError("PRIMARY_PROVIDER=gemini but GEMINI_API_KEY is not set")
        return _generator_module().gemini_generate(gemini_key, selected)
    raise ProviderHardError(f"Unknown PRIMARY_PROVIDER: {primary!r}")


def analyze_image(image_url: str) -> dict:
    """Provider-agnostic replacement for score_with_deepseek.gemini_vision.

    Returns {"visual_ok","room_type","quality","reasons","model"} matching the
    existing vision contract consumed by the business gate.
    """
    primary = _primary_provider()
    if primary == "aws_bedrock_nova":
        try:
            return _aws_bedrock_analyze_image(image_url)
        except ProviderHardError:
            if _fallback_provider() == "gemini":
                gemini_key = (os.environ.get("GEMINI_API_KEY") or "").strip()
                if gemini_key:
                    vision = _score_module().gemini_vision(gemini_key, image_url)
                    vision["model"] = f"gemini-fallback:{vision.get('model', '')}"
                    return vision
            raise
    if primary == "gemini":
        gemini_key = (os.environ.get("GEMINI_API_KEY") or "").strip()
        if not gemini_key:
            raise ProviderHardError("PRIMARY_PROVIDER=gemini but GEMINI_API_KEY is not set")
        return _score_module().gemini_vision(gemini_key, image_url)
    raise ProviderHardError(f"Unknown PRIMARY_PROVIDER: {primary!r}")


def evaluate_business(post: dict, vision: dict) -> dict:
    """Provider-agnostic replacement for score_with_deepseek.deepseek_business.

    Returns {"score","pass","reasons","caption_match","cta_ok","conversion_ok","model"}
    matching the existing business-gate contract, using the same pass rules
    (score>=7 and caption_match and cta_ok and conversion_ok) regardless of
    which model judges them.
    """
    primary = _primary_provider()
    if primary == "aws_bedrock_nova":
        return _aws_bedrock_evaluate_business(post, vision)
    raise ProviderHardError(f"Business gate is not implemented for PRIMARY_PROVIDER={primary!r}")
