#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

EXPECTED_MODEL = "google/siglip-base-patch16-224"
EXPECTED_REVISION = "7fd15f0689c79d79e38b1c2e2e2370a7bf2761ed"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args()

    source = Path(args.input)
    data = json.loads(source.read_text(encoding="utf-8"))
    raw = source.read_text(encoding="utf-8")

    checks: list[tuple[str, bool]] = []
    checks.append(("execution_mode_shadow_only", data.get("execution_mode") == "SHADOW_ONLY"))
    checks.append(("production_effect_none", data.get("production_effect") == "NONE"))
    checks.append(("public_action_false", data.get("public_action_performed") is False))
    checks.append(("business_outcome_false", data.get("business_outcome_claim") is False))
    checks.append(("exactly_three_results", len(data.get("results") or []) == 3))
    checks.append(("no_source_image_urls_persisted", "images.unsplash.com" not in raw and "image_url" not in raw))

    latencies: list[float] = []
    observations = []
    for idx, row in enumerate(data.get("results") or [], start=1):
        result = row.get("result") or {}
        model_result = result.get("result") or {}
        latency = float(result.get("latency_ms") or 0.0)
        latencies.append(latency)
        row_checks = {
            "status": result.get("status") == "SHADOW_RESULT",
            "mode": result.get("mode") == "SHADOW_ONLY",
            "decision_authority": result.get("decision_authority") is False,
            "production_effect": result.get("production_effect") == "NONE",
            "business_outcome_claim": result.get("business_outcome_claim") is False,
            "model": model_result.get("model_id") == EXPECTED_MODEL,
            "revision": model_result.get("revision") == EXPECTED_REVISION,
            "latency_positive": latency > 0,
            "top_label_present": bool(model_result.get("top_label")),
        }
        checks.append((f"result_{idx}_valid", all(row_checks.values())))
        observations.append({
            "post_id": row.get("post_id"),
            "input_classification": row.get("input_classification"),
            "status": result.get("status"),
            "model_id": model_result.get("model_id"),
            "revision": model_result.get("revision"),
            "top_label": model_result.get("top_label"),
            "top_score": model_result.get("top_score"),
            "latency_ms": latency,
            "decision_authority": result.get("decision_authority"),
            "production_effect": result.get("production_effect"),
        })

    failures = [name for name, passed in checks if not passed]
    status = "LIVE_VERIFIED" if not failures else "LIVE_VERIFICATION_FAILED"
    evidence = {
        "schema_version": 1,
        "department_id": "aura3",
        "phase": "HF_PHASE7_LIVE_SHADOW_VERIFICATION",
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "status": status,
        "source_sha": args.source_sha,
        "workflow_run_id": args.run_id,
        "execution_scope": "MAIN_BRANCH_CONTROLLED_SHADOW_ONLY",
        "model": {
            "model_id": EXPECTED_MODEL,
            "revision": EXPECTED_REVISION,
            "backend": "local_transformers",
        },
        "results_observed": len(observations),
        "latency_ms": {
            "min": min(latencies) if latencies else None,
            "max": max(latencies) if latencies else None,
            "mean": (sum(latencies) / len(latencies)) if latencies else None,
        },
        "checks": {name: passed for name, passed in checks},
        "failures": failures,
        "observations": observations,
        "production_effect": "NONE",
        "public_action_performed": False,
        "decision_authority": False,
        "business_outcome_claim": False,
        "truth_note": "LIVE_VERIFIED proves fresh real SigLIP shadow inference executed from AURA3 main in an isolated GitHub Actions job. It does not grant production decision/publish authority or prove business outcome.",
    }

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    print(json.dumps(evidence, indent=2))
    return 0 if status == "LIVE_VERIFIED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
