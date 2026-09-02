#!/usr/bin/env python3
"""Run the AURA3 queue maintainer with bounded provider/network timeout resilience."""

from __future__ import annotations

import time
import urllib.error

import generate_candidates as generator
import maintain_approval_queue as maintainer
import score_with_deepseek as quality_gate

_ORIGINAL_GENERATOR_REQUEST_JSON = generator.request_json
_ORIGINAL_GATE_POST_JSON = quality_gate.post_json
_ORIGINAL_DOWNLOAD_IMAGE = quality_gate.download_image
TIMEOUT_SECONDS = 45
TIMEOUT_ATTEMPTS = 2


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


def main() -> int:
    generator.request_json = resilient_generator_request_json
    quality_gate.post_json = resilient_gate_post_json
    quality_gate.download_image = resilient_download_image
    return maintainer.main()


if __name__ == "__main__":
    raise SystemExit(main())
