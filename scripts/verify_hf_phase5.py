#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

OUTPUT = ROOT / "evaluation/results/hf-phase5-readiness.json"


def main() -> int:
    suite = unittest.defaultTestLoader.loadTestsFromName("tests.test_hf_phase5_readiness")
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    status = "READY_FOR_CONTROLLED_SHADOW_DEPLOYMENT_ONLY" if result.wasSuccessful() else "NOT_READY"
    evidence = {
        "schema_version": 1,
        "department_id": "aura3",
        "phase": "HF_PHASE5_PRODUCTION_READINESS_AND_SECURITY_FINALIZATION",
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "status": status,
        "production_effect": "NONE",
        "production_authority": False,
        "public_action_performed": False,
        "credential_administration_performed": False,
        "main_merged": False,
        "test_summary": {
            "tests_run": result.testsRun,
            "failures": len(result.failures),
            "errors": len(result.errors),
            "skipped": len(result.skipped),
        },
        "security_controls": {
            "primary_model_revision_pinned": True,
            "primary_model_safetensors_forced": True,
            "remote_code_disabled": True,
            "direct_dependencies_exact_pinned": True,
            "transitive_constraints_exact_pinned": True,
            "github_actions_commit_sha_pinned": True,
            "checkout_credentials_persisted": False,
            "public_primary_hf_token_injected": False,
            "separate_job_isolation_required": True,
            "paid_hf_hosted_inference_allowed": False,
            "confidential_data_allowed": False,
        },
        "readiness_scope": "CONTROLLED_PRODUCTION_SHADOW_DEPLOYMENT_ONLY",
        "blocked_promotions": [
            "production_decision_authority",
            "publish_authority",
            "production_routing_authority",
            "Gemini_visual_gate_replacement",
            "business_outcome_claim",
        ],
        "rollback": "HF_EVALUATION_ENABLED=false / hf/config.json enabled=false",
        "truth_note": "A PASS means the isolated HF observer is security/readiness-qualified for a controlled shadow deployment only. It does not mean it is deployed on main, LIVE, authoritative, or business-outcome verified."
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(evidence, indent=2))
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
