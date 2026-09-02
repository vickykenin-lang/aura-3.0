#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.hf_observability import (
    assert_privacy_minimized,
    build_observation,
    load_json,
    sha256_file,
    summarize,
    verify_source_integrity,
)
from runtime.hf_shadow import HFShadowEvaluator

SOURCE_PATHS = ["content/calendar.json", "data/gate_results.json"]


def save_json(path: str, data: dict) -> None:
    full = ROOT / path
    full.parent.mkdir(parents=True, exist_ok=True)
    full.write_text(json.dumps(data, indent=2), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--output", default="evaluation/results/hf-phase4-observability.json")
    args = parser.parse_args()

    policy = load_json("hf/observability_policy.json")
    limit = max(1, min(int(args.limit), int(policy.get("max_cases", 10))))
    calendar = load_json("content/calendar.json")
    gate_results = load_json("data/gate_results.json")
    posts = calendar.get("days") or []
    historical_posts = gate_results.get("posts") or {}

    before = {path: sha256_file(path) for path in SOURCE_PATHS}
    evaluator = HFShadowEvaluator()
    observations = []

    for post in posts[:limit]:
        post_id = str(post.get("id") or "")
        historical = historical_posts.get(post_id, {})
        row = build_observation(post, historical, evaluator)
        assert_privacy_minimized(row)
        observations.append(row)

    after = {path: sha256_file(path) for path in SOURCE_PATHS}
    integrity_ok = verify_source_integrity(before, after)
    metrics = summarize(observations)
    all_non_authoritative = all(
        row.get("decision_authority") is False and row.get("production_effect") == "NONE"
        for row in observations
    )
    no_forbidden_data = True
    try:
        for row in observations:
            assert_privacy_minimized(row)
    except ValueError:
        no_forbidden_data = False

    passed = (
        bool(observations)
        and metrics["cases_observed"] == len(observations)
        and integrity_ok
        and all_non_authoritative
        and no_forbidden_data
    )

    evidence = {
        "schema_version": 1,
        "department_id": "aura3",
        "phase": "HF_PHASE4_SHADOW_INTEGRATION_AND_OBSERVABILITY",
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "status": "OBSERVABILITY_VERIFIED" if passed else "OBSERVABILITY_FAILED",
        "mode": "SHADOW_OBSERVE_ONLY",
        "production_effect": "NONE",
        "decision_authority": False,
        "public_action_performed": False,
        "business_outcome_claim": False,
        "source_artifacts": {
            "access": "READ_ONLY",
            "hashes_before": before,
            "hashes_after": after,
            "unchanged": integrity_ok,
        },
        "privacy": {
            "image_urls_stored": False,
            "caption_text_stored": False,
            "lead_or_contact_data_stored": False,
            "confidential_client_data_used": False,
            "privacy_minimized": no_forbidden_data,
        },
        "integration": {
            "input": "existing AURA3 candidate and Gemini/DeepSeek gate artifacts",
            "observer": "HF SigLIP shadow evaluator",
            "qualified_scope": policy.get("qualified_scope"),
            "production_gate_modified": False,
            "publish_path_modified": False,
            "routing_modified": False,
        },
        "metrics": metrics,
        "observations": observations,
        "truth_note": "OBSERVABILITY_VERIFIED proves read-only parallel observation on existing AURA3 candidate/gate artifacts in the isolated branch workflow. It does not prove production deployment, LIVE production operation, publish authority, or business outcome.",
    }
    save_json(args.output, evidence)
    print(json.dumps(evidence, indent=2))
    return 0 if passed else 2


if __name__ == "__main__":
    raise SystemExit(main())
