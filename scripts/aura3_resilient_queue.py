#!/usr/bin/env python3
"""Resilient AURA3 queue runner.

Hardens the existing strict visual pipeline without changing Founder authority:
- persistent dead/rejected image blacklist
- per-stage sanitized incident codes
- current-design visual validation before copy generation
- image-grounded caption semantic gate
- automatic rejected/stale pending cleanup
- bounded provider retry so one transient failure does not stop 20/20 refill
"""
from __future__ import annotations

import base64
import json
import os
import re
import time
import urllib.error
from datetime import datetime, timedelta, timezone
from pathlib import Path

import run_deepseek_primary as core

ROOT = Path(__file__).resolve().parents[1]
RULEBOOK_PATH = ROOT / "governance/image_validation_rulebook.json"
BLACKLIST_PATH = ROOT / "data/dead_image_blacklist.json"
INCIDENT_PATH = ROOT / "data/pipeline_incidents.json"
IST = timezone(timedelta(hours=5, minutes=30))
_VISUAL_CACHE: dict[str, dict] = {}
_ORIGINAL_GENERATE = core.deepseek_generate
_ORIGINAL_BUSINESS = core.deepseek_business
DOWNLOAD_RETRY_DELAYS = (2, 5, 10)
PROVIDER_RETRY_DELAYS = (15, 30, 60)
SEMANTIC_MIN_SCORE = 7
RESILIENCE_VERSION = 1


def _load(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def _save(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _image_key(url: str) -> str:
    return core.maintainer.image_key(str(url or ""))


def _record_incident(code: str, stage: str, detail: str = "", image_url: str = "", post_id: str = "") -> None:
    data = _load(INCIDENT_PATH, {"schema_version": 1, "department_id": "aura3", "events": []})
    events = list(data.get("events") or [])
    events.append({
        "observed_at": datetime.now(IST).isoformat(),
        "code": code,
        "stage": stage,
        "detail": re.sub(r"(?i)(bearer|token|key|secret)\s*[:=]\s*\S+", r"\1=[REDACTED]", str(detail))[:300],
        "image_key": _image_key(image_url) if image_url else "",
        "post_id": str(post_id or ""),
    })
    data["events"] = events[-200:]
    _save(INCIDENT_PATH, data)


def _blacklist() -> dict:
    return _load(BLACKLIST_PATH, {"schema_version": 1, "department_id": "aura3", "images": {}})


def _is_blacklisted(url: str) -> bool:
    key = _image_key(url)
    return bool(key and key in (_blacklist().get("images") or {}))


def _mark_blacklisted(url: str, reason: str, source: str = "runtime") -> None:
    key = _image_key(url)
    if not key:
        return
    data = _blacklist()
    images = data.setdefault("images", {})
    previous = images.get(key) or {}
    images[key] = {
        "reason": reason,
        "source": source,
        "first_seen": previous.get("first_seen") or datetime.now(IST).isoformat(),
        "last_seen": datetime.now(IST).isoformat(),
        "url": str(url),
    }
    _save(BLACKLIST_PATH, data)


def load_rulebook() -> dict:
    return _load(RULEBOOK_PATH, {})


def build_vision_prompt(rulebook: dict) -> str:
    min_score = int((rulebook.get("quality") or {}).get("minimum_visual_quality_score", 7))
    categories = " | ".join((rulebook.get("content_categorization") or {}).get("primary_categories") or [])
    concepts = " | ".join((rulebook.get("content_categorization") or {}).get("design_concepts") or [])
    return f"""You are AURA3's Interior Design Image Validator & Optimizer for Design Infra.
Inspect the actual image. Do not approve merely because it is an interior.

REQUIREMENTS
- Premium, current/recent, commercially relevant interior-design visual.
- Good brightness, clarity, composition, natural color and clear design subject.
- Minimum quality {min_score}/10.
- Reject blur, poor lighting, clutter, people-dominated lifestyle scenes, animals, outdoor-only scenes,
  roads/railways, food-only scenes, memes, unrelated stock, watermarks, copyright notices or prominent unapproved logos.
- Reject visibly old, dated, archival, vintage, retro, heritage/period-dominant interiors, obsolete office layouts,
  dated ceiling/lighting/partition systems, old-fashioned finishes or archival-looking photography.
- Prefer modern/contemporary/current industrial/current luxury/current minimalist/current sustainable design.
- Extract only visible facts for captions: room type, layout/circulation, materials/finishes, lighting,
  color palette, furniture/features and one design takeaway. Never invent a material or feature.

Primary category: {categories}
Design concepts: {concepts}

Return JSON only:
{{"status":"APPROVED|NEEDS_REVISION|DO_NOT_POST","visual_ok":true,"room_type":"office|commercial|hospitality|retail|living|kitchen|bedroom|bathroom|dining|other","quality":0,"brightness_level":"Good|Fair|Poor","composition":"...","color_accuracy":"Good|Fair|Poor","design_freshness":"Current|Dated|Vintage|Unclear","copyright_status":"Clear|Flagged|Unknown","watermarks":"None|Present","brand_logo_risk":"None|Present|Unclear","primary_category":"...","design_concepts":["..."],"style":"...","visible_features":["..."],"sample_caption_angle":"...","reasons":["..."]}}

visual_ok=true only if status=APPROVED, quality>={min_score}, design_freshness=Current and no legal/brand blocker."""


def _download_with_retry(url: str) -> tuple[str, bytes]:
    last: Exception | None = None
    for attempt in range(len(DOWNLOAD_RETRY_DELAYS) + 1):
        try:
            return core.quality_gate.download_image(url)
        except urllib.error.HTTPError as exc:
            last = exc
            transient = exc.code in {408, 425, 429, 500, 502, 503, 504}
            if not transient or attempt == len(DOWNLOAD_RETRY_DELAYS):
                raise
            time.sleep(DOWNLOAD_RETRY_DELAYS[attempt])
        except urllib.error.URLError as exc:
            last = exc
            if attempt == len(DOWNLOAD_RETRY_DELAYS):
                raise
            time.sleep(DOWNLOAD_RETRY_DELAYS[attempt])
    raise last or RuntimeError("image download retry exhausted")


def _as_list(value) -> list[str]:
    if isinstance(value, list):
        return [str(x) for x in value]
    return [str(value)] if value else []


def strict_vision(api_key: str, image_url: str) -> dict:
    if not api_key:
        raise RuntimeError("DEEPSEEK_API_KEY is required for vision gate")
    if not str(image_url).startswith("https://"):
        raise ValueError("visual source must use HTTPS")
    if _is_blacklisted(image_url):
        raise ValueError("image is persistently blacklisted")
    if image_url in _VISUAL_CACHE:
        return dict(_VISUAL_CACHE[image_url])

    rulebook = load_rulebook()
    min_score = int((rulebook.get("quality") or {}).get("minimum_visual_quality_score", 7))
    try:
        mime, image_bytes = _download_with_retry(image_url)
    except urllib.error.HTTPError as exc:
        code = int(getattr(exc, "code", 0) or 0)
        _mark_blacklisted(image_url, f"SOURCE_HTTP_{code}")
        _record_incident(f"IMG_HTTP_{code or 'ERROR'}", "image_source", image_url=image_url)
        raise
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        _mark_blacklisted(image_url, f"SOURCE_{type(exc).__name__.upper()}")
        _record_incident("IMG_SOURCE_UNUSABLE", "image_source", type(exc).__name__, image_url)
        raise

    data_url = f"data:{mime};base64,{base64.b64encode(image_bytes).decode('ascii')}"
    model = os.environ.get("DEEPSEEK_VISION_MODEL", "deepseek-v4-flash-vision-exp")
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": [
            {"type": "text", "text": build_vision_prompt(rulebook)},
            {"type": "image_url", "image_url": {"url": data_url}},
        ]}],
        "response_format": {"type": "json_object"},
        "thinking": {"type": "disabled"},
        "temperature": 0,
        "max_tokens": 1200,
    }
    result = core._deepseek_json(payload, "strict_interior_vision_gate")
    if not isinstance(result, dict):
        raise RuntimeError("strict image validator returned non-object JSON")

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
        "design_concepts": _as_list(result.get("design_concepts")),
        "style": str(result.get("style", "")),
        "visible_features": _as_list(result.get("visible_features")),
        "sample_caption_angle": str(result.get("sample_caption_angle", "")),
        "reasons": _as_list(result.get("reasons")),
        "rulebook": "governance/image_validation_rulebook.json",
        "resilience_rulebook_version": RESILIENCE_VERSION,
        "model": model,
    }
    _VISUAL_CACHE[image_url] = normalized
    if not visual_ok:
        _mark_blacklisted(image_url, f"VISUAL_REJECT_{freshness.upper()}", "vision_gate")
        _record_incident("IMG_VISUAL_REJECT", "vision", f"freshness={freshness};quality={quality}", image_url)
    return dict(normalized)


def _fresh_candidates() -> list[dict]:
    calendar = core.maintainer.load_json("content/calendar.json", {"days": []})
    return [x for x in core.maintainer.fresh_pool_items(calendar) if not _is_blacklisted(str(x.get("image", "")))]


def image_grounded_generate(_unused_key: str, selected: list[dict]) -> tuple[list[dict], str]:
    api_key = (os.environ.get("DEEPSEEK_API_KEY") or os.environ.get("DEEPSEEK_KEY") or "").strip()
    requested = len(selected)
    queue = [x for x in selected if not _is_blacklisted(str(x.get("image", "")))]
    seen = {_image_key(str(x.get("image", ""))) for x in queue}
    for candidate in _fresh_candidates():
        key = _image_key(str(candidate.get("image", "")))
        if key and key not in seen:
            queue.append(candidate)
            seen.add(key)

    validated, enriched = [], []
    for item in queue:
        if len(validated) >= requested:
            break
        url = str(item.get("image", ""))
        try:
            vision = strict_vision(api_key, url)
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, ValueError):
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
        _record_incident("NO_VALID_VISUALS", "generation", f"requested={requested}")
        return [], ""

    last_error: Exception | None = None
    for attempt in range(len(PROVIDER_RETRY_DELAYS) + 1):
        try:
            return _ORIGINAL_GENERATE("", enriched)
        except Exception as exc:
            last_error = exc
            text = str(exc)
            transient = any(marker in text for marker in ("HTTP 429", "HTTP 500", "HTTP 502", "HTTP 503", "HTTP 504", "network", "timeout"))
            _record_incident("GEN_PROVIDER_TRANSIENT" if transient else "GEN_PROVIDER_ERROR", "generation", type(exc).__name__)
            if not transient or attempt == len(PROVIDER_RETRY_DELAYS):
                raise
            time.sleep(PROVIDER_RETRY_DELAYS[attempt])
    raise last_error or RuntimeError("generation retry exhausted")


def _semantic_caption_check(post: dict, vision: dict) -> dict:
    ig = post.get("ig") or {}
    payload = {
        "model": os.environ.get("DEEPSEEK_MODEL", "deepseek-v4-flash"),
        "messages": [{"role": "user", "content": (
            "You are AURA3 caption-to-image semantic validator. Compare the caption only against the supplied actual-image evidence. "
            "Return JSON only: {\"score\":0-10,\"grounded\":true/false,\"contradictions\":[\"...\"],\"reasons\":[\"...\"]}. "
            "Score >=7 requires the hook/caption to clearly arise from visible image facts and contain no invented materials/features.\n"
            f"room={vision.get('room_type')}\nstyle={vision.get('style')}\nvisible_features={vision.get('visible_features')}\n"
            f"caption_angle={vision.get('sample_caption_angle')}\nhook={ig.get('hook_en','')}\ncaption={ig.get('caption_hi','')}"
        )}],
        "response_format": {"type": "json_object"},
        "thinking": {"type": "disabled"},
        "temperature": 0,
        "max_tokens": 500,
    }
    result = core._deepseek_json(payload, "caption_semantic_gate")
    if not isinstance(result, dict):
        raise RuntimeError("semantic caption gate returned non-object JSON")
    try:
        score = max(0, min(10, int(result.get("score", 0))))
    except (TypeError, ValueError):
        score = 0
    contradictions = _as_list(result.get("contradictions"))
    grounded = bool(result.get("grounded")) and score >= SEMANTIC_MIN_SCORE and not contradictions
    return {"score": score, "grounded": grounded, "contradictions": contradictions, "reasons": _as_list(result.get("reasons"))}


def resilient_business(api_key: str, post: dict, vision: dict) -> dict:
    business = _ORIGINAL_BUSINESS(api_key, post, vision)
    semantic = _semantic_caption_check(post, vision)
    business["caption_semantic"] = semantic
    business["caption_match"] = bool(business.get("caption_match")) and semantic["grounded"]
    business["pass"] = bool(business.get("pass")) and semantic["grounded"]
    if not semantic["grounded"]:
        _record_incident("CAPTION_IMAGE_MISMATCH", "caption_semantic", f"score={semantic['score']}", str(post.get("image", "")), str(post.get("id", "")))
    return business


def _cleanup_rejected_and_stale() -> None:
    calendar = core.maintainer.load_json("content/calendar.json", {"days": []})
    approvals = core.maintainer.load_json("data/approvals.json", {})
    gates_doc = core.maintainer.load_json("data/gate_results.json", {"posts": {}})
    gates = gates_doc.setdefault("posts", {})
    kept = []
    removed = []
    for post in calendar.get("days", []):
        post_id = str(post.get("id", ""))
        state = core.maintainer.approval_state(approvals, post_id)
        gate = gates.get(post_id) or {}
        vision = gate.get("vision") or {}
        stale_reject = state == "pending" and vision.get("resilience_rulebook_version") == RESILIENCE_VERSION and not bool(vision.get("visual_ok"))
        if state == "rejected" or stale_reject:
            _mark_blacklisted(str(post.get("image", "")), "FOUNDER_REJECTED" if state == "rejected" else "STALE_VISUAL_REJECT", "cleanup")
            gates.pop(post_id, None)
            removed.append(post_id)
            continue
        kept.append(post)
    if removed:
        calendar["days"] = kept
        core.maintainer.save_json("content/calendar.json", calendar)
        core.maintainer.save_json("data/gate_results.json", gates_doc)
        _record_incident("STALE_REJECTED_CLEANUP", "cleanup", f"removed={len(removed)}")


def main() -> int:
    _cleanup_rejected_and_stale()
    core.deepseek_vision = strict_vision
    core.deepseek_generate = image_grounded_generate
    core.deepseek_business = resilient_business
    return core.main()


if __name__ == "__main__":
    raise SystemExit(main())
