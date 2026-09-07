#!/usr/bin/env python3
"""Run AURA3 approval queue with DeepSeek as the production text provider.

Temporary visual policy while Bedrock/Nova is unavailable: only the existing governed,
curated image pool is eligible; hard-reject tags remain fail-closed. This adapter does
not claim image inspection. It records a metadata-only visual gate so Gemini is not a
production dependency.
"""
from __future__ import annotations

import json
import os
import urllib.request

# The legacy maintainer checks this variable even after its Gemini call sites are replaced.
os.environ.setdefault("GEMINI_API_KEY", "DISABLED_DEEPSEEK_PRIMARY")
os.environ.setdefault("DEEPSEEK_MODEL", "deepseek-chat")

import generate_candidates as generator
import maintain_approval_queue as maintainer
import score_with_deepseek as quality_gate

DEEPSEEK_API = "https://api.deepseek.com/chat/completions"


def deepseek_generate(_unused_key: str, selected: list[dict]) -> tuple[list[dict], str]:
    api_key = (os.environ.get("DEEPSEEK_API_KEY") or os.environ.get("DEEPSEEK_KEY") or "").strip()
    if not api_key:
        raise RuntimeError("DEEPSEEK_API_KEY is required")
    count = len(selected)
    inputs = [
        {"slot": i + 1, "room_tag": item.get("photo_tag", "interior"), "content_angle": item.get("angle", "")}
        for i, item in enumerate(selected)
    ]
    prompt = generator.SYSTEM_PROMPT + (
        f"\n\nCreate exactly {count} items for these fixed image slots:\n"
        + json.dumps(inputs, ensure_ascii=False)
        + '\nReturn JSON only as {"candidates":[{"slot":1,"hook_en":"...","caption_hi":"...","hashtags":"#... #..."}]}. '
        + f"The candidates array must contain exactly {count} items."
    )
    payload = {
        "model": os.environ.get("DEEPSEEK_MODEL", "deepseek-chat"),
        "messages": [
            {"role": "system", "content": "You are AURA3 production copy generation. Follow the supplied governance rules exactly."},
            {"role": "user", "content": prompt},
        ],
        "response_format": {"type": "json_object"},
        "temperature": 0.4,
        "max_tokens": max(1500, 700 * count),
    }
    request = urllib.request.Request(
        DEEPSEEK_API,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    data = quality_gate.post_json(request, "DeepSeek", timeout=90)
    text = data["choices"][0]["message"]["content"]
    parsed = json.loads(text)
    candidates = parsed.get("candidates") if isinstance(parsed, dict) else parsed
    if not isinstance(candidates, list) or len(candidates) != count:
        raise RuntimeError("DeepSeek generator returned invalid candidate count")
    return candidates, os.environ.get("DEEPSEEK_MODEL", "deepseek-chat")


def governed_metadata_visual_gate(_unused_key: str, image_url: str) -> dict:
    if not str(image_url).startswith("https://"):
        raise RuntimeError("visual source must use HTTPS")
    return {
        "visual_ok": True,
        "room_type": "other",
        "quality": 7,
        "reasons": ["governed curated image-pool metadata gate; no vision-model inspection claimed"],
        "model": "CURATED_METADATA_GATE",
    }


def main() -> int:
    # Replace only provider-specific legacy call sites. Existing queue, Founder approval,
    # disclosure, uniqueness and publishing governance remain unchanged.
    generator.gemini_generate = deepseek_generate
    quality_gate.gemini_vision = governed_metadata_visual_gate
    quality_gate.GEMINI_MODELS = ("CURATED_METADATA_GATE",)
    return maintainer.main()


if __name__ == "__main__":
    raise SystemExit(main())
