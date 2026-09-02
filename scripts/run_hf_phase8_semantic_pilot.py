#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from runtime.hf_semantic_memory import MultilingualSemanticAdapter, load_policy

FIXTURES = ROOT / "evaluation" / "fixtures" / "hf-phase8-semantic-fixtures.json"
CALENDAR = ROOT / "content" / "calendar.json"
OUTPUT = ROOT / "evaluation" / "results" / "hf-phase8-semantic-pilot.json"


def pair_key(left: str, right: str) -> tuple[str, str]:
    return tuple(sorted((left, right)))


def main() -> int:
    fixture = json.loads(FIXTURES.read_text(encoding="utf-8"))
    calendar = json.loads(CALENDAR.read_text(encoding="utf-8"))
    adapter = MultilingualSemanticAdapter()
    policy = load_policy()

    started = time.perf_counter()
    fixture_scan = adapter.scan(fixture["items"])
    fixture_elapsed_ms = (time.perf_counter() - started) * 1000
    fixture_pairs = {
        pair_key(p["left_id"], p["right_id"]): p
        for p in fixture_scan["pairs"]
    }

    acceptance = []
    for rule in fixture["acceptance_pairs"]:
        pair = fixture_pairs[pair_key(rule["left"], rule["right"])]
        score = float(pair["similarity"])
        threshold = float(rule["threshold"])
        passed = score >= threshold if rule["rule"] == "AT_LEAST" else score < threshold
        acceptance.append({
            "left_id": rule["left"],
            "right_id": rule["right"],
            "purpose": rule["purpose"],
            "rule": rule["rule"],
            "threshold": threshold,
            "similarity": score,
            "classification": pair["classification"],
            "passed": passed,
        })

    corpus_items = []
    for day in calendar.get("days", []):
        ig = day.get("ig") or {}
        text = " ".join(filter(None, [ig.get("hook_en"), ig.get("caption_hi")]))
        corpus_items.append({"id": day["id"], "text": text})

    corpus_started = time.perf_counter()
    corpus_scan = adapter.scan(corpus_items)
    corpus_elapsed_ms = (time.perf_counter() - corpus_started) * 1000
    flagged = [p for p in corpus_scan["pairs"] if p["classification"] != "DISTINCT"]

    all_acceptance_passed = all(item["passed"] for item in acceptance)
    evidence = {
        "schema_version": 1,
        "department_id": "aura3",
        "phase": "HF_PHASE8_SEMANTIC_MEMORY_DUPLICATE_PILOT",
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "status": "CAPABILITY_VERIFIED" if all_acceptance_passed else "PILOT_FAILED",
        "mode": "SHADOW_ONLY",
        "decision_authority": False,
        "production_effect": "NONE",
        "public_action_performed": False,
        "business_outcome_claim": False,
        "model": {
            "model_id": fixture_scan["model_id"],
            "revision": fixture_scan["revision"],
            "backend": "local_transformers_mean_pooling",
        },
        "similarity_policy": {
            "duplicate_min": policy.duplicate_min,
            "repetitive_theme_min": policy.repetitive_theme_min,
        },
        "fixture_validation": {
            "classification": fixture["classification"],
            "cases": acceptance,
            "passed": sum(1 for item in acceptance if item["passed"]),
            "total": len(acceptance),
            "elapsed_ms_including_model_load": round(fixture_elapsed_ms, 2),
        },
        "aura3_corpus_scan": {
            "source": "content/calendar.json",
            "items": len(corpus_items),
            "pairwise_comparisons": len(corpus_scan["pairs"]),
            "duplicates": sum(1 for p in corpus_scan["pairs"] if p["classification"] == "DUPLICATE"),
            "repetitive_themes": sum(1 for p in corpus_scan["pairs"] if p["classification"] == "REPETITIVE_THEME"),
            "distinct_pairs": sum(1 for p in corpus_scan["pairs"] if p["classification"] == "DISTINCT"),
            "flagged_pairs": flagged[:20],
            "top_similarity_pairs": corpus_scan["pairs"][:10],
            "elapsed_ms": round(corpus_elapsed_ms, 2),
        },
        "privacy": {
            "raw_text_persisted": False,
            "embedding_vectors_persisted": False,
            "lead_or_contact_data_used": False,
            "confidential_client_data_used": False,
        },
        "cost": {
            "direct_hf_hosted_inference_charge_usd": 0.0,
            "github_actions_compute_attribution": "NOT_ATTRIBUTED",
        },
        "truth_note": "CAPABILITY_VERIFIED proves only controlled semantic similarity and duplicate/repetition detection on synthetic and current non-sensitive AURA3 text. It does not grant production decision/publish authority or prove business outcome.",
    }

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    print(json.dumps(evidence, indent=2))
    return 0 if all_acceptance_passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
