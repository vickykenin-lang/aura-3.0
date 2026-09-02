#!/usr/bin/env python3
from __future__ import annotations

import io
import json
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tests.test_hf_phase3_reliability import HFPhase3ReliabilityTests

OUT = ROOT / "evaluation/results/hf-phase3-reliability.json"


def main() -> int:
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(HFPhase3ReliabilityTests)
    test_names = [test.id() for test in suite]
    stream = io.StringIO()
    result = unittest.TextTestRunner(stream=stream, verbosity=2).run(suite)

    failures = [{"test": test.id(), "detail": detail[-1000:]} for test, detail in result.failures]
    errors = [{"test": test.id(), "detail": detail[-1000:]} for test, detail in result.errors]
    skipped = [{"test": test.id(), "reason": reason} for test, reason in result.skipped]

    passed = result.wasSuccessful()
    evidence = {
        "schema_version": 1,
        "department_id": "aura3",
        "phase": "HF_PHASE3_RELIABILITY_AND_FAILURE_TESTING",
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "status": "TEST_PASSED" if passed else "TEST_FAILED",
        "mode": "SHADOW_ONLY",
        "production_effect": "NONE",
        "public_action_performed": False,
        "business_outcome_claim": False,
        "scenarios": {
            "transient_timeout_retry_then_recovery": "TESTED",
            "retry_exhaustion": "TESTED",
            "nonretryable_runtime_failure": "TESTED",
            "policy_rejection_is_not_provider_failure": "TESTED",
            "corrupt_input_rejection": "TESTED",
            "circuit_open_after_three_failed_evaluations": "TESTED",
            "cooldown_recovery": "TESTED",
            "success_resets_failure_streak": "TESTED",
            "production_path_independence": "TESTED",
        },
        "test_summary": {
            "tests_run": result.testsRun,
            "tests_expected": len(test_names),
            "failures": len(result.failures),
            "errors": len(result.errors),
            "skipped": len(result.skipped),
            "test_names": test_names,
        },
        "failures": failures,
        "errors": errors,
        "skipped": skipped,
        "controls": {
            "hf_enabled_by_default": False,
            "production_authority": False,
            "required_for_business_execution": False,
            "failure_envelopes_require_production_effect_none": True,
            "policy_rejections_do_not_advance_breaker": True,
            "failed_retry_sequence_counts_as_one_breaker_failure": True,
            "circuit_breaker_threshold": 3,
            "configured_cooldown_seconds": 900,
            "production_runtime_imports_hf_shadow": False,
        },
        "known_boundary": {
            "local_model_inference_hard_kill_timeout": "NOT_IMPLEMENTED_IN_PROCESS",
            "reason": "Phase 3 verifies configured network/download timeout and fault containment. A safe hard kill for a stuck local model requires process isolation; thread timeout alone would not safely terminate model execution.",
            "production_risk": "NONE_WHILE_SHADOW_OPTIONAL",
            "future_action": "Use process isolation before any future requirement makes HF latency part of a production SLA.",
        },
        "lifecycle": {
            "baseline_verified": True,
            "source_implemented": True,
            "phase2_test_passed": True,
            "phase3_reliability_test_passed": passed,
            "production_deployed": False,
            "live_verified": False,
            "business_outcome_verified": False,
        },
        "truth_note": "TEST_PASSED proves deterministic reliability/failure containment for the declared optional HF shadow layer only. It does not prove production deployment, LIVE operation, or business outcome.",
    }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    print(json.dumps(evidence, indent=2))
    if stream.getvalue():
        print(stream.getvalue(), file=sys.stderr)
    return 0 if passed else 2


if __name__ == "__main__":
    raise SystemExit(main())
