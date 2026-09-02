#!/usr/bin/env python3
from __future__ import annotations

import json
import statistics
from datetime import datetime, timezone
from pathlib import Path

from runtime.hf_shadow import HFShadowEvaluator

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "evaluation/results/hf-phase2-qualification.json"

ROOM_LABELS = {
    "living": "a living room interior",
    "kitchen": "a kitchen interior",
    "bedroom": "a bedroom interior",
    "bathroom": "a bathroom interior",
    "office": "an office interior",
    "dining": "a dining room interior",
}
ROOM_BY_LABEL = {v: k for k, v in ROOM_LABELS.items()}

SUITABILITY_POSITIVE = "a clean professional interior architecture photograph focused on the space"
SUITABILITY_NEGATIVE = [
    "a lifestyle photograph focused on people cooking or interacting",
    "an outdoor landscape photograph",
    "an animal or wildlife photograph",
    "an unrelated stock photograph not focused on interior architecture",
]
SUITABILITY_LABELS = [SUITABILITY_POSITIVE, *SUITABILITY_NEGATIVE]


def load_json(path: str):
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def top_label(result: dict) -> str | None:
    if result.get("status") != "SHADOW_RESULT":
        return None
    return result.get("result", {}).get("top_label")


def top_score(result: dict) -> float | None:
    if result.get("status") != "SHADOW_RESULT":
        return None
    value = result.get("result", {}).get("top_score")
    return float(value) if value is not None else None


def main() -> int:
    calendar = load_json("content/calendar.json")
    historical = load_json("data/gate_results.json")
    posts = calendar.get("days") or []
    hist_posts = historical.get("posts") or {}

    if len(posts) < 10:
        raise SystemExit("Phase 2 requires at least 10 controlled reference cases")

    evaluator = HFShadowEvaluator()
    cases = []
    inference_latencies = []
    room_correct_count = 0
    suitability_correct_count = 0
    successful_case_count = 0
    gemini_room_disagreements = 0
    gemini_suitability_disagreements = 0

    for post in posts[:10]:
        post_id = str(post.get("id"))
        expected_room = str(post.get("photo_tag") or "")
        hist = hist_posts.get(post_id, {})
        gemini_room = str((hist.get("vision") or {}).get("room_type") or "")
        gemini_visual_ok = bool(hist.get("visual_ok"))

        room_eval = evaluator.evaluate_url(
            str(post.get("image") or ""),
            list(ROOM_LABELS.values()),
            force_shadow=True,
        )
        suitability_eval = evaluator.evaluate_url(
            str(post.get("image") or ""),
            SUITABILITY_LABELS,
            force_shadow=True,
        )

        room_label = top_label(room_eval)
        predicted_room = ROOM_BY_LABEL.get(room_label or "")
        suitability_label = top_label(suitability_eval)
        predicted_visual_ok = suitability_label == SUITABILITY_POSITIVE if suitability_label else None

        room_correct = predicted_room == expected_room
        suitability_correct = predicted_visual_ok is not None and predicted_visual_ok == gemini_visual_ok
        if room_correct:
            room_correct_count += 1
        if suitability_correct:
            suitability_correct_count += 1

        statuses_ok = room_eval.get("status") == "SHADOW_RESULT" and suitability_eval.get("status") == "SHADOW_RESULT"
        if statuses_ok:
            successful_case_count += 1

        if predicted_room is not None and gemini_room and predicted_room != gemini_room:
            gemini_room_disagreements += 1
        if predicted_visual_ok is not None and predicted_visual_ok != gemini_visual_ok:
            gemini_suitability_disagreements += 1

        for result in (room_eval, suitability_eval):
            if result.get("status") == "SHADOW_RESULT" and result.get("latency_ms") is not None:
                inference_latencies.append(float(result["latency_ms"]))

        cases.append({
            "post_id": post_id,
            "source": post.get("image_source"),
            "input_classification": "PUBLIC_NON_SENSITIVE_REFERENCE_IMAGE",
            "expected_room_from_calendar": expected_room,
            "gemini_reference_room": gemini_room,
            "gemini_reference_visual_ok": gemini_visual_ok,
            "hf_predicted_room": predicted_room,
            "hf_room_top_score": top_score(room_eval),
            "hf_predicted_visual_ok": predicted_visual_ok,
            "hf_suitability_top_label": suitability_label,
            "hf_suitability_top_score": top_score(suitability_eval),
            "room_correct_against_calendar": room_correct,
            "suitability_correct_against_historical_gate": suitability_correct,
            "room_status": room_eval.get("status"),
            "suitability_status": suitability_eval.get("status"),
            "room_latency_ms": room_eval.get("latency_ms"),
            "suitability_latency_ms": suitability_eval.get("latency_ms"),
        })

    room_accuracy = room_correct_count / 10.0
    suitability_accuracy = suitability_correct_count / 10.0
    runtime_success_rate = successful_case_count / 10.0

    policy_rejection_probe = evaluator.evaluate_url(
        "http://example.com/not-allowed.jpg",
        ["interior"],
        force_shadow=True,
    )
    invalid_input_rejected = policy_rejection_probe.get("status") == "EVALUATION_REJECTED"

    thresholds = {
        "runtime_success_rate_min": 1.0,
        "suitability_accuracy_min": 0.9,
        "room_accuracy_min": 0.8,
        "invalid_input_must_fail_closed": True,
    }
    passed = (
        runtime_success_rate >= thresholds["runtime_success_rate_min"]
        and suitability_accuracy >= thresholds["suitability_accuracy_min"]
        and room_accuracy >= thresholds["room_accuracy_min"]
        and invalid_input_rejected
    )

    model_registry = load_json("hf/model_registry.json")
    config = load_json("hf/config.json")
    model = model_registry["models"][config["primary_model"]]

    evidence = {
        "schema_version": 1,
        "department_id": "aura3",
        "phase": "HF_PHASE2_TECHNICAL_QUALIFICATION",
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "status": "TEST_PASSED" if passed else "TEST_FAILED",
        "mode": "SHADOW_ONLY",
        "production_effect": "NONE",
        "public_action_performed": False,
        "business_outcome_claim": False,
        "model": {
            "model_id": model["model_id"],
            "revision": model["revision"],
            "execution_backend": config["execution"]["backend"],
            "production_authority": False,
        },
        "dataset": {
            "cases": 10,
            "source": "content/calendar.json + data/gate_results.json",
            "data_classification": "PUBLIC_NON_SENSITIVE_REFERENCE_IMAGES",
            "ground_truth_note": "Calendar photo_tag is used for room reference. Historical Gemini gate is used only as a visual-suitability comparison reference, not objective ground truth.",
        },
        "metrics": {
            "runtime_success_rate": round(runtime_success_rate, 4),
            "room_accuracy_against_calendar": round(room_accuracy, 4),
            "suitability_accuracy_against_historical_gate": round(suitability_accuracy, 4),
            "gemini_room_disagreements": gemini_room_disagreements,
            "gemini_suitability_disagreements": gemini_suitability_disagreements,
            "evaluation_calls": len(inference_latencies),
            "first_call_latency_ms_includes_model_load": inference_latencies[0] if inference_latencies else None,
            "median_call_latency_ms": round(statistics.median(inference_latencies), 2) if inference_latencies else None,
            "mean_call_latency_ms": round(statistics.mean(inference_latencies), 2) if inference_latencies else None,
            "max_call_latency_ms": round(max(inference_latencies), 2) if inference_latencies else None,
            "direct_hf_inference_charge_usd": 0.0,
            "runner_compute_cost": "NOT_ATTRIBUTED",
        },
        "failure_probe": {
            "type": "HTTP_URL_REJECTED_BY_HTTPS_POLICY",
            "passed": invalid_input_rejected,
            "status": policy_rejection_probe.get("status"),
            "production_effect": policy_rejection_probe.get("production_effect"),
        },
        "thresholds": thresholds,
        "cases": cases,
        "truth_note": "TEST_PASSED proves this controlled SigLIP shadow benchmark only. It does not prove production deployment, LIVE production operation, or business outcome.",
    }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    print(json.dumps(evidence, indent=2))
    return 0 if passed else 2


if __name__ == "__main__":
    raise SystemExit(main())
