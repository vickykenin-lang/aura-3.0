#!/usr/bin/env python3
"""AURA3 production queue entrypoint with strict current-design image validation.

This wrapper preserves the existing production flow and Founder authority while replacing the
basic visual screen with the governed Interior Design Image Validator & Optimizer rulebook.
Captions are grounded in visual evidence from the actual selected image before generation.
"""
from __future__ import annotations

import base64
import json
import os
from pathlib import Path

import run_deepseek_primary as core

RULEBOOK_PATH = Path("governance/image_validation_rulebook.json")
_VISUAL_CACHE: dict[str, dict] = {}
_ORIGINAL_DEEPSEEK_GENERATE = core.deepseek_generate


def load_rulebook() -> dict:
    return json.loads(RULEBOOK_PATH.read_text(encoding="utf-8"))


def build_vision_prompt(rulebook: dict) -> str:
    min_score = int(rulebook["quality"]["minimum_visual_quality_score"])
    categories = " | ".join(rulebook["content_categorization"]["primary_categories"])
    concepts = " | ".join(rulebook["content_categorization"]["design_concepts"])
    return f"""You are AURA3's Interior Design Image Validator & Optimizer for Design Infra.
Assess the actual image for commercial Instagram/Facebook use. Do not approve merely because the
image contains an interior. Evaluate premium brand fit, current-design relevance and posting readiness.

QUALITY VALIDATION
- Brightness and clarity must be usable and visually appealing.
- Composition must have strong framing, angle, balance and a clear interior-design subject.
- Colors should look natural and credible, not heavily filtered or distorted.
- Reject severe blur, poor lighting, messy/distracting clutter, people-dominated lifestyle scenes,
  animals/wildlife, outdoor-only scenes, roads/railways, food-only scenes, memes, unrelated stock,
  and anything unsuitable for a premium interior-design social feed.
- Minimum visual quality score for approval: {min_score}/10.

CURRENT-DESIGN / FRESHNESS RULE
- The visible design and the photograph must look current/recent and commercially relevant today.
- DO NOT approve visibly old, dated, archival, vintage, retro, heritage/period-dominant interiors.
- Reject outdated furniture, obsolete office layouts, dated ceiling/lighting/partition systems,
  old-fashioned finishes, archival-looking processing, or any image that reads as an old picture.
- Modern, contemporary, current industrial, current luxury, current minimalist and current sustainable
  interiors are preferred. If visual age is uncertain but the image clearly looks dated, reject it.

COPYRIGHT / LEGAL VISUAL SCREEN
- Detect visible watermarks, copyright notices, photographer credits, prominent third-party logos,
  or obvious third-party IP risk.
- If any visible watermark/copyright notice or prominent unapproved brand/logo is present, do not
  visually approve the image.
- Do NOT claim that commercial rights are verified from pixels. Source/licensing rights are checked
  separately by AURA3's governed acquisition layer.

CONTENT CATEGORIZATION
Primary category must be one of: {categories}.
Design concepts may include: {concepts}.
Also classify room_type as living|kitchen|bedroom|bathroom|dining|office|commercial|hospitality|retail|other.

IMAGE-GROUNDED CAPTION EVIDENCE
- Identify visible features that can safely drive the caption: actual room type, layout, circulation,
  materials/finishes, lighting, color palette, furniture/feature elements and one design takeaway.
- Do not invent a material, feature, room function or design detail that is not visible.
- sample_caption_angle must be based on the actual image, not a generic interior topic.

SOCIAL MEDIA OPTIMIZATION
Assess whether the image is suitable for feed use and suggest a caption angle focused on the visible
concept, planning, materials, lighting, spatial use or execution value rather than aesthetics alone.

Return JSON only in this exact structure:
{{
  "status":"APPROVED|NEEDS_REVISION|DO_NOT_POST",
  "visual_ok":true,
  "room_type":"office",
  "quality":0,
  "brightness_level":"Good|Fair|Poor",
  "composition":"brief assessment",
  "color_accuracy":"Good|Fair|Poor",
  "design_freshness":"Current|Dated|Vintage|Unclear",
  "copyright_status":"Clear|Flagged|Unknown",
  "watermarks":"None|Present",
  "brand_logo_risk":"None|Present|Unclear",
  "primary_category":"Office/Corporate Interior",
  "design_concepts":["Modern","Spatial Planning & Layout"],
  "style":"brief style description",
  "visible_features":["feature visible in image","another visible feature"],
  "issues":["..."],
  "recommendations":["..."],
  "suggested_edits":["..."],
  "social_media_optimization":["..."],
  "sample_caption_angle":"brief image-grounded angle",
  "reasons":["..."]
}}

Set visual_ok=true only when status is APPROVED, quality >= {min_score}, design_freshness is Current,
composition/lighting/color are acceptable, and no visible watermark/copyright/logo/IP blocker is present."""


def _as_list(result: dict, key: str) -> list[str]:
    value = result.get(key)
    if isinstance(value, list):
        return [str(item) for item in value]
    return [str(value)] if value else []


def strict_vision(api_key: str, image_url: str) -> dict:
    if not api_key:
        raise RuntimeError("DEEPSEEK_API_KEY is required for vision gate")
    if not str(image_url).startswith("https://"):
        raise RuntimeError("visual source must use HTTPS")
    if image_url in _VISUAL_CACHE:
        return dict(_VISUAL_CACHE[image_url])

    rulebook = load_rulebook()
    min_score = int(rulebook["quality"]["minimum_visual_quality_score"])
    os.environ["DEEPSEEK_API_KEY"] = api_key
    model = os.environ.get("DEEPSEEK_VISION_MODEL", "deepseek-v4-flash-vision-exp")
    mime_type, image_bytes = core.quality_gate.download_image(str(image_url))
    image_data_url = f"data:{mime_type};base64,{base64.b64encode(image_bytes).decode('ascii')}"
    payload = {
        "model": model,
        "messages": [{
            "role": "user",
            "content": [
                {"type": "text", "text": build_vision_prompt(rulebook)},
                {"type": "image_url", "image_url": {"url": image_data_url}},
            ],
        }],
        "response_format": {"type": "json_object"},
        "thinking": {"type": "disabled"},
        "temperature": 0,
        "max_tokens": 1400,
    }
    result = core._deepseek_json(payload, "strict_interior_vision_gate")
    if not isinstance(result, dict):
        raise RuntimeError("strict image validator returned non-object JSON")

    allowed_rooms = {"living", "kitchen", "bedroom", "bathroom", "dining", "office", "commercial", "hospitality", "retail", "other"}
    room_type = str(result.get("room_type", "other")).lower().strip()
    if room_type not in allowed_rooms:
        room_type = "other"
    try:
        quality = max(0, min(10, int(result.get("quality", 0))))
    except (TypeError, ValueError):
        quality = 0

    status = str(result.get("status", "DO_NOT_POST")).upper().strip()
    if status not in {"APPROVED", "NEEDS_REVISION", "DO_NOT_POST"}:
        status = "DO_NOT_POST"
    watermarks = str(result.get("watermarks", "Present")).strip()
    copyright_status = str(result.get("copyright_status", "Unknown")).strip()
    brand_logo_risk = str(result.get("brand_logo_risk", "Unclear")).strip()
    freshness = str(result.get("design_freshness", "Unclear")).strip().title()
    if freshness not in {"Current", "Dated", "Vintage", "Unclear"}:
        freshness = "Unclear"
    blocking_visual_legal = (
        watermarks.lower() != "none"
        or copyright_status.lower() == "flagged"
        or brand_logo_risk.lower() == "present"
    )
    visual_ok = (
        bool(result.get("visual_ok", False))
        and status == "APPROVED"
        and quality >= min_score
        and freshness == "Current"
        and not blocking_visual_legal
    )

    normalized = {
        "visual_ok": visual_ok,
        "status": status if visual_ok else ("NEEDS_REVISION" if status == "NEEDS_REVISION" else "DO_NOT_POST"),
        "room_type": room_type,
        "quality": quality,
        "brightness_level": str(result.get("brightness_level", "Unknown")),
        "composition": str(result.get("composition", "")),
        "color_accuracy": str(result.get("color_accuracy", "Unknown")),
        "design_freshness": freshness,
        "copyright_status": copyright_status,
        "watermarks": watermarks,
        "brand_logo_risk": brand_logo_risk,
        "usage_rights": "Verified separately by governed source/licensing policy",
        "primary_category": str(result.get("primary_category", "")),
        "design_concepts": _as_list(result, "design_concepts"),
        "style": str(result.get("style", "")),
        "visible_features": _as_list(result, "visible_features"),
        "issues": _as_list(result, "issues"),
        "recommendations": _as_list(result, "recommendations"),
        "suggested_edits": _as_list(result, "suggested_edits"),
        "social_media_optimization": _as_list(result, "social_media_optimization"),
        "sample_caption_angle": str(result.get("sample_caption_angle", "")),
        "reasons": _as_list(result, "reasons"),
        "rulebook": "governance/image_validation_rulebook.json",
        "model": model,
    }
    _VISUAL_CACHE[image_url] = normalized
    return dict(normalized)


def image_grounded_generate(_unused_key: str, selected: list[dict]) -> tuple[list[dict], str]:
    """Generate captions only after extracting visual evidence from each selected image."""
    api_key = (os.environ.get("DEEPSEEK_API_KEY") or os.environ.get("DEEPSEEK_KEY") or "").strip()
    if not api_key:
        raise RuntimeError("DEEPSEEK_API_KEY is required for image-grounded generation")

    enriched: list[dict] = []
    for item in selected:
        image_url = str(item.get("image", ""))
        vision = strict_vision(api_key, image_url)
        visible_features = ", ".join(vision.get("visible_features") or []) or "no safely identified visible features"
        concepts = ", ".join(vision.get("design_concepts") or []) or vision.get("style", "")
        grounded_angle = (
            f"ACTUAL IMAGE EVIDENCE ONLY — room={vision.get('room_type')}; "
            f"freshness={vision.get('design_freshness')}; style={vision.get('style')}; "
            f"concepts={concepts}; visible_features={visible_features}; "
            f"caption_angle={vision.get('sample_caption_angle')}. "
            "Hook and caption must be based on these visible facts. Do not invent any feature or material."
        )
        enriched.append({**item, "angle": grounded_angle})

    return _ORIGINAL_DEEPSEEK_GENERATE("", enriched)


def main() -> int:
    core.deepseek_vision = strict_vision
    core.deepseek_generate = image_grounded_generate
    return core.main()


if __name__ == "__main__":
    raise SystemExit(main())
