#!/usr/bin/env python3
"""Governed AURA3 image-cleanup layer.

If the strict visual gate finds an otherwise-current, high-quality interior image with a
visible watermark, small logo, or unwanted text overlay, this layer makes one bounded
cleanup attempt through Runway, persists the cleaned asset in the repository, and requires
fresh strict visual re-validation before the image can continue to Founder approval.

The cleanup layer never changes Founder authority, source licensing, provider rotation,
or business/caption gates. It does not treat a cleanup API success as visual approval.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path

RUNWAY_API = "https://api.dev.runwayml.com/v1"
RUNWAY_VERSION = "2024-11-06"
RUNWAY_MODEL = os.environ.get("AURA3_IMAGE_CLEANUP_MODEL", "seedream5_pro")
RUNWAY_RATIO = os.environ.get("AURA3_IMAGE_CLEANUP_RATIO", "auto_1k")
POLL_DELAYS = (5, 5, 7, 7, 10, 10, 15, 15, 20, 20, 20, 20)
_CLEANED_URLS: dict[str, str] = {}
_INSTALLED = False


def _json_request(url: str, *, method: str = "GET", payload: dict | None = None, timeout: int = 60) -> dict:
    secret = (os.environ.get("RUNWAYML_API_SECRET") or "").strip()
    if not secret:
        raise RuntimeError("RUNWAYML_API_SECRET is required for image cleanup")
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(
        url,
        data=data,
        headers={
            "Authorization": f"Bearer {secret}",
            "Content-Type": "application/json",
            "X-Runway-Version": RUNWAY_VERSION,
        },
        method=method,
    )
    with urllib.request.urlopen(req, timeout=timeout) as response:
        body = response.read().decode("utf-8")
    parsed = json.loads(body)
    if not isinstance(parsed, dict):
        raise RuntimeError("image cleanup provider returned non-object JSON")
    return parsed


def _cleanup_candidate(vision: dict) -> bool:
    if vision.get("visual_ok"):
        return False
    try:
        quality = int(vision.get("quality", 0) or 0)
    except (TypeError, ValueError):
        quality = 0
    freshness = str(vision.get("design_freshness", "Unclear")).lower()
    copyright_status = str(vision.get("copyright_status", "Unknown")).lower()
    watermark = str(vision.get("watermarks", "None")).lower()
    logo = str(vision.get("brand_logo_risk", "None")).lower()
    overlay_present = watermark == "present" or logo == "present"
    return quality >= 7 and freshness == "current" and copyright_status != "flagged" and overlay_present


def _create_cleanup_task(source_url: str) -> str:
    payload = {
        "model": RUNWAY_MODEL,
        "ratio": RUNWAY_RATIO,
        "promptText": (
            "Edit @source only. Remove the visible watermark, small logo, and unwanted text overlay. "
            "Preserve the original interior scene, camera angle, crop, geometry, furniture, materials, "
            "lighting, colors and all design details. Do not add text, logos, objects, people or styling."
        ),
        "referenceImages": [{"uri": source_url, "tag": "source"}],
    }
    result = _json_request(f"{RUNWAY_API}/text_to_image", method="POST", payload=payload, timeout=90)
    task_id = str(result.get("id") or "").strip()
    if not task_id:
        raise RuntimeError("image cleanup provider did not return a task id")
    return task_id


def _wait_for_output(task_id: str) -> str:
    for delay in POLL_DELAYS:
        task = _json_request(f"{RUNWAY_API}/tasks/{task_id}", timeout=45)
        status = str(task.get("status") or "").upper()
        if status == "SUCCEEDED":
            outputs = task.get("output") or []
            if isinstance(outputs, list) and outputs and str(outputs[0]).startswith("https://"):
                return str(outputs[0])
            raise RuntimeError("image cleanup task succeeded without an image output")
        if status in {"FAILED", "CANCELED", "CANCELLED"}:
            raise RuntimeError(f"image cleanup task ended with status {status}")
        time.sleep(delay)
    raise TimeoutError("image cleanup task exceeded bounded polling window")


def _download_image(url: str) -> tuple[str, bytes]:
    req = urllib.request.Request(url, headers={"User-Agent": "AURA3-Image-Cleanup/1.0"}, method="GET")
    with urllib.request.urlopen(req, timeout=90) as response:
        content_type = str(response.headers.get("Content-Type") or "").split(";", 1)[0].lower()
        body = response.read()
    if not content_type.startswith("image/") or not body:
        raise ValueError("image cleanup output was not valid image bytes")
    return content_type, body


def _persist_cleaned_asset(source_url: str, output_url: str) -> tuple[str, Path]:
    content_type, image_bytes = _download_image(output_url)
    extension = ".png" if content_type == "image/png" else ".webp" if content_type == "image/webp" else ".jpg"
    digest = hashlib.sha256((source_url + "\n").encode("utf-8") + image_bytes).hexdigest()[:20]
    root = Path(__file__).resolve().parents[1]
    relative = Path("assets") / "cleaned" / f"aura3-clean-{digest}{extension}"
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(image_bytes)

    repository = (os.environ.get("GITHUB_REPOSITORY") or "vickykenin-lang/aura-3.0").strip("/")
    owner, repo = repository.split("/", 1)
    stable_url = f"https://{owner}.github.io/{repo}/{relative.as_posix()}"
    return stable_url, path


def cleanup_image(source_url: str) -> tuple[str, str]:
    """Return (ephemeral_provider_url, durable_pages_url) after one cleanup task."""
    if not str(source_url).startswith("https://"):
        raise ValueError("cleanup source must use HTTPS")
    task_id = _create_cleanup_task(source_url)
    output_url = _wait_for_output(task_id)
    stable_url, _ = _persist_cleaned_asset(source_url, output_url)
    return output_url, stable_url


def install_into_resilient_runtime(resilient) -> None:
    """Patch the active resilient runtime with cleanup-before-reject behavior."""
    global _INSTALLED
    if _INSTALLED:
        return

    original_strict_vision = resilient.strict_vision
    original_image_grounded_generate = resilient.image_grounded_generate

    def cleanup_aware_strict_vision(api_key: str, image_url: str) -> dict:
        vision = original_strict_vision(api_key, image_url)
        if not _cleanup_candidate(vision):
            return vision

        if not (os.environ.get("RUNWAYML_API_SECRET") or "").strip():
            resilient._record_incident(
                "IMG_CLEANUP_CREDENTIALS_UNAVAILABLE",
                "image_cleanup",
                "cleanup candidate retained as visual reject; RUNWAYML_API_SECRET unavailable",
                image_url,
            )
            return vision

        try:
            provider_url, stable_url = cleanup_image(image_url)
            cleaned = original_strict_vision(api_key, provider_url)
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, ValueError, RuntimeError) as exc:
            resilient._record_incident("IMG_CLEANUP_FAILED", "image_cleanup", type(exc).__name__, image_url)
            return vision

        if not cleaned.get("visual_ok"):
            resilient._record_incident("IMG_CLEANUP_REVALIDATION_REJECT", "image_cleanup", "strict gate rejected cleaned output", image_url)
            return vision

        annotated = dict(cleaned)
        annotated.update({
            "cleanup_applied": True,
            "cleanup_provider": "runway",
            "cleanup_original_image": image_url,
            "cleanup_stable_image": stable_url,
        })
        _CLEANED_URLS[image_url] = stable_url
        resilient._VISUAL_CACHE[stable_url] = dict(annotated)
        resilient._record_incident("IMG_CLEANUP_REVALIDATED_PASS", "image_cleanup", "cleaned output passed strict visual gate", image_url)
        return annotated

    def cleanup_aware_generate(_unused_key: str, selected: list[dict]):
        result = original_image_grounded_generate(_unused_key, selected)
        for item in selected:
            original_url = str(item.get("image") or "")
            stable_url = _CLEANED_URLS.get(original_url)
            if not stable_url:
                continue
            item["original_image"] = original_url
            item["image"] = stable_url
            item["image_cleanup"] = {
                "applied": True,
                "provider": "runway",
                "revalidated": True,
            }
        return result

    resilient.strict_vision = cleanup_aware_strict_vision
    resilient.image_grounded_generate = cleanup_aware_generate
    _INSTALLED = True
