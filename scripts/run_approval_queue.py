#!/usr/bin/env python3
"""Run the AURA3 queue maintainer with bounded provider/network resilience."""

from __future__ import annotations

import json
import time
import urllib.error
from pathlib import Path

import ai_provider
import generate_candidates as generator
import maintain_approval_queue as maintainer
import score_with_deepseek as quality_gate

ROOT = Path(__file__).resolve().parents[1]
STATUS_PATH = ROOT / "data/approval_queue_status.json"
_ORIGINAL_GENERATOR_REQUEST_JSON = generator.request_json
_ORIGINAL_GEMINI_GENERATE = generator.gemini_generate
_ORIGINAL_GATE_POST_JSON = quality_gate.post_json
_ORIGINAL_DOWNLOAD_IMAGE = quality_gate.download_image
_ORIGINAL_GENERATE_CONTENT = ai_provider.generate_content
_ORIGINAL_ANALYZE_IMAGE = ai_provider.analyze_image
TIMEOUT_SECONDS = 45
TIMEOUT_ATTEMPTS = 2


class GeminiProjectBillingDenied(RuntimeError):
    """Raised when Google denies the whole Gemini project for billing/access reasons."""


class AWSProviderHardBlocked(RuntimeError):
    """Raised when AWS Bedrock hard-blocks the department (credentials/access/config)."""


def is_gemini_project_billing_denied_text(value: str) -> bool:
    text = str(value or "").lower()
    return (
        "dunning decision is deny" in text
        or ("gemini http 403" in text and "permission_denied" in text)
        or ("http 403" in text and "project access" in text and "billing" in text)
    )


def resilient_generator_request_json(request, timeout: int = TIMEOUT_SECONDS):
    """Convert raw Gemini socket timeouts into the generator's fallback contract."""
    last_error = None
    for attempt in range(TIMEOUT_ATTEMPTS):
        try:
            return _ORIGINAL_GENERATOR_REQUEST_JSON(request, timeout=min(timeout, TIMEOUT_SECONDS))
        except TimeoutError as error:
            last_error = error
            if attempt + 1 < TIMEOUT_ATTEMPTS:
                print(f"Gemini generation timeout; retrying attempt {attempt + 2}/{TIMEOUT_ATTEMPTS}")
                time.sleep(2)
    raise RuntimeError("Gemini network error: timeout") from last_error


def resilient_gemini_generate(api_key: str, selected: list[dict]):
    """Promote project-level Gemini 403/billing denial to a non-transient error type."""
    try:
        return _ORIGINAL_GEMINI_GENERATE(api_key, selected)
    except RuntimeError as error:
        if is_gemini_project_billing_denied_text(str(error)):
            raise GeminiProjectBillingDenied("Gemini project access or billing denied") from error
        raise


def resilient_gate_post_json(request, provider: str, timeout: int = TIMEOUT_SECONDS):
    """Bound raw socket timeouts for Gemini Vision and DeepSeek requests."""
    last_error = None
    for attempt in range(TIMEOUT_ATTEMPTS):
        try:
            return _ORIGINAL_GATE_POST_JSON(request, provider, timeout=min(timeout, TIMEOUT_SECONDS))
        except TimeoutError as error:
            last_error = error
            if attempt + 1 < TIMEOUT_ATTEMPTS:
                print(f"{provider} qualification timeout; retrying attempt {attempt + 2}/{TIMEOUT_ATTEMPTS}")
                time.sleep(2)
    raise RuntimeError(f"{provider} network error: timeout") from last_error


def resilient_download_image(url: str):
    """Retry transient raw/network timeouts while downloading a public reference image."""
    last_error = None
    for attempt in range(TIMEOUT_ATTEMPTS):
        try:
            return _ORIGINAL_DOWNLOAD_IMAGE(url)
        except (TimeoutError, urllib.error.URLError) as error:
            last_error = error
            if attempt + 1 < TIMEOUT_ATTEMPTS:
                print(f"Reference image download timeout; retrying attempt {attempt + 2}/{TIMEOUT_ATTEMPTS}")
                time.sleep(2)
    raise RuntimeError("image network error: timeout") from last_error


def resilient_generate_content(selected: list[dict]):
    """Retry transient AI-provider errors; promote hard provider errors to a typed block."""
    last_error = None
    for attempt in range(TIMEOUT_ATTEMPTS):
        try:
            return _ORIGINAL_GENERATE_CONTENT(selected)
        except ai_provider.ProviderTransientError as error:
            last_error = error
            if attempt + 1 < TIMEOUT_ATTEMPTS:
                print(f"AI provider transient error; retrying attempt {attempt + 2}/{TIMEOUT_ATTEMPTS}: {error}")
                time.sleep(2)
                continue
            raise RuntimeError(f"AI provider transient error: {error}") from error
        except ai_provider.ProviderHardError as error:
            raise AWSProviderHardBlocked(str(error)) from error
    raise RuntimeError("AI provider generation exhausted retries") from last_error


def resilient_analyze_image(image_url: str):
    """Retry transient AI-provider vision errors; promote hard provider errors to a typed block."""
    last_error = None
    for attempt in range(TIMEOUT_ATTEMPTS):
        try:
            return _ORIGINAL_ANALYZE_IMAGE(image_url)
        except ai_provider.ProviderTransientError as error:
            last_error = error
            if attempt + 1 < TIMEOUT_ATTEMPTS:
                print(f"AI provider transient vision error; retrying attempt {attempt + 2}/{TIMEOUT_ATTEMPTS}: {error}")
                time.sleep(2)
                continue
            raise RuntimeError(f"AI provider transient vision error: {error}") from error
        except ai_provider.ProviderHardError as error:
            raise AWSProviderHardBlocked(str(error)) from error
    raise RuntimeError("AI provider vision analysis exhausted retries") from last_error


def promote_provider_block_status(exit_code: int) -> None:
    """Persist a sanitized hard-block truth state after maintainer catches typed errors."""
    if exit_code == 0:
        return
    try:
        status = json.loads(STATUS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    errors = list(status.get("technical_errors") or [])
    if any(str(item.get("type")) == "GeminiProjectBillingDenied" for item in errors):
        status["status"] = "REFILL_BLOCKED_GEMINI_PROJECT_BILLING"
        status["provider_blocker"] = "GEMINI_PROJECT_ACCESS_OR_BILLING_DENIED"
        status["truth_note"] = (
            "Gemini generation is blocked by provider project access/billing state. "
            "AURA3 must not self-retry this non-transient condition. Existing Founder and publishing authority remain unchanged."
        )
    elif any(str(item.get("type")) == "AWSProviderHardBlocked" for item in errors):
        status["status"] = "REFILL_BLOCKED_AWS_PROVIDER"
        status["provider_blocker"] = "AWS_PROVIDER_ACCESS_OR_CONFIG_DENIED"
        status["truth_note"] = (
            "AWS Bedrock generation/vision is blocked by a provider credentials, access, or configuration "
            "condition. AURA3 must not self-retry this non-transient condition. Existing Founder and publishing "
            "authority remain unchanged."
        )
    else:
        return
    STATUS_PATH.write_text(json.dumps(status, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def main() -> int:
    generator.request_json = resilient_generator_request_json
    generator.gemini_generate = resilient_gemini_generate
    quality_gate.post_json = resilient_gate_post_json
    quality_gate.download_image = resilient_download_image
    ai_provider.generate_content = resilient_generate_content
    ai_provider.analyze_image = resilient_analyze_image
    exit_code = maintainer.main()
    promote_provider_block_status(exit_code)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
