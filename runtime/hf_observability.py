#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]

ROOM_LABELS = {
    "living": "a living room interior",
    "kitchen": "a kitchen interior",
    "bedroom": "a bedroom interior",
    "bathroom": "a bathroom interior",
    "office": "an office interior",
    "dining": "a dining room interior",
}
ROOM_BY_LABEL = {value: key for key, value in ROOM_LABELS.items()}
RELEVANCE_NEGATIVE_LABELS = [
    "a lifestyle photograph focused mainly on people rather than the interior space",
    "an outdoor landscape photograph without an interior space",
    "an animal or wildlife photograph",
]
RELEVANCE_LABELS = [*ROOM_LABELS.values(), *RELEVANCE_NEGATIVE_LABELS]


def load_json(path: str) -> dict[str, Any]:
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def sha256_file(path: str) -> str:
    return hashlib.sha256((ROOT / path).read_bytes()).hexdigest()


def _result_top_label(result: dict[str, Any]) -> str | None:
    if result.get("status") != "SHADOW_RESULT":
        return None
    return (result.get("result") or {}).get("top_label")


def _result_top_score(result: dict[str, Any]) -> float | None:
    if result.get("status") != "SHADOW_RESULT":
        return None
    value = (result.get("result") or {}).get("top_score")
    return float(value) if value is not None else None


def _result_model(result: dict[str, Any]) -> tuple[str | None, str | None]:
    payload = result.get("result") or {}
    return payload.get("model_id"), payload.get("revision")


def build_observation(post: dict[str, Any], historical: dict[str, Any], evaluator: Any) -> dict[str, Any]:
    """Build one privacy-minimized, non-authoritative shadow observation."""
    post_id = str(post.get("id") or "")
    image_url = str(post.get("image") or "")
    reference_room = str((historical.get("vision") or {}).get("room_type") or post.get("photo_tag") or "")
    reference_visual_ok = bool(historical.get("visual_ok"))

    room_result = evaluator.evaluate_url(image_url, list(ROOM_LABELS.values()), force_shadow=True)
    relevance_result = evaluator.evaluate_url(image_url, RELEVANCE_LABELS, force_shadow=True)

    room_top_label = _result_top_label(room_result)
    relevance_top_label = _result_top_label(relevance_result)
    hf_room = ROOM_BY_LABEL.get(room_top_label or "")
    hf_relevant = relevance_top_label in ROOM_BY_LABEL if relevance_top_label else None
    model_id, revision = _result_model(room_result)
    if not model_id:
        model_id, revision = _result_model(relevance_result)

    room_disagreement = None if hf_room is None or not reference_room else hf_room != reference_room
    relevance_disagreement = None if hf_relevant is None else hf_relevant != reference_visual_ok

    statuses = {room_result.get("status"), relevance_result.get("status")}
    status = "OBSERVED" if statuses == {"SHADOW_RESULT"} else "OBSERVER_UNAVAILABLE"

    return {
        "post_id": post_id,
        "input_classification": "PUBLIC_NON_SENSITIVE_REFERENCE_IMAGE",
        "status": status,
        "decision_authority": False,
        "production_effect": "NONE",
        "model_id": model_id,
        "revision": revision,
        "reference_room": reference_room or None,
        "hf_predicted_room": hf_room,
        "room_disagreement": room_disagreement,
        "reference_visual_ok": reference_visual_ok,
        "hf_interior_relevance": hf_relevant,
        "relevance_disagreement": relevance_disagreement,
        "room_top_score": _result_top_score(room_result),
        "relevance_top_score": _result_top_score(relevance_result),
        "room_latency_ms": room_result.get("latency_ms"),
        "relevance_latency_ms": relevance_result.get("latency_ms"),
        "room_evaluator_status": room_result.get("status"),
        "relevance_evaluator_status": relevance_result.get("status"),
    }


def summarize(observations: list[dict[str, Any]]) -> dict[str, Any]:
    observed = [row for row in observations if row.get("status") == "OBSERVED"]
    room_compared = [row for row in observed if row.get("room_disagreement") is not None]
    relevance_compared = [row for row in observed if row.get("relevance_disagreement") is not None]
    latencies = [
        float(value)
        for row in observed
        for value in (row.get("room_latency_ms"), row.get("relevance_latency_ms"))
        if value is not None
    ]
    return {
        "cases_requested": len(observations),
        "cases_observed": len(observed),
        "observer_availability_rate": round(len(observed) / len(observations), 4) if observations else 0.0,
        "room_comparisons": len(room_compared),
        "room_disagreements": sum(1 for row in room_compared if row["room_disagreement"]),
        "relevance_comparisons": len(relevance_compared),
        "relevance_disagreements": sum(1 for row in relevance_compared if row["relevance_disagreement"]),
        "evaluation_calls": len(latencies),
        "mean_latency_ms": round(sum(latencies) / len(latencies), 2) if latencies else None,
        "max_latency_ms": round(max(latencies), 2) if latencies else None,
    }


def assert_privacy_minimized(observation: dict[str, Any]) -> None:
    forbidden = {"image", "image_url", "caption", "caption_hi", "hook_en", "email", "phone"}
    found = forbidden.intersection(observation)
    if found:
        raise ValueError(f"observability record contains forbidden fields: {sorted(found)}")


def verify_source_integrity(before: dict[str, str], after: dict[str, str]) -> bool:
    return before == after
