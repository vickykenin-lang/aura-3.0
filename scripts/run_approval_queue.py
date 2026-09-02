#!/usr/bin/env python3
"""Run the AURA3 queue maintainer with bounded Gemini timeout retries."""

from __future__ import annotations

import time

import generate_candidates as generator
import maintain_approval_queue as maintainer

_ORIGINAL_REQUEST_JSON = generator.request_json
TIMEOUT_SECONDS = 45
TIMEOUT_ATTEMPTS = 2


def resilient_request_json(request, timeout: int = TIMEOUT_SECONDS):
    """Convert raw socket TimeoutError into generator-compatible network errors.

    The existing generator already knows how to fall back across Gemini models when it
    receives a RuntimeError containing "network error". This wrapper prevents a raw
    TimeoutError from bypassing that fallback chain.
    """
    last_error = None
    for attempt in range(TIMEOUT_ATTEMPTS):
        try:
            return _ORIGINAL_REQUEST_JSON(request, timeout=min(timeout, TIMEOUT_SECONDS))
        except TimeoutError as error:
            last_error = error
            if attempt + 1 < TIMEOUT_ATTEMPTS:
                print(f"Gemini request timeout; retrying attempt {attempt + 2}/{TIMEOUT_ATTEMPTS}")
                time.sleep(2)
    raise RuntimeError("Gemini network error: timeout") from last_error


def main() -> int:
    generator.request_json = resilient_request_json
    return maintainer.main()


if __name__ == "__main__":
    raise SystemExit(main())
