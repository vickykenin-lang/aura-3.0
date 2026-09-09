#!/usr/bin/env python3
import argparse
import json
from pathlib import Path


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--input", required=True)
    args = p.parse_args()
    data = json.loads(Path(args.input).read_text(encoding="utf-8"))

    evidence = data.get("evidence_snapshot", {})
    authority = data.get("authority", {})
    published_items = evidence.get("canonical_published_items")
    verified_outcomes = evidence.get("verified_outcomes_meeting_gate")
    business_verified = data.get("business_outcome_verified") is True
    verdict = data.get("verdict")

    evidence_shape_valid = (
        isinstance(published_items, int)
        and published_items >= 0
        and isinstance(verified_outcomes, int)
        and verified_outcomes >= 0
    )

    if business_verified:
        outcome_truth_consistent = (
            verdict == "BUSINESS_OUTCOME_VERIFIED"
            and isinstance(verified_outcomes, int)
            and verified_outcomes > 0
        )
    else:
        outcome_truth_consistent = (
            verdict in {"INSUFFICIENT_REAL_WORLD_EVIDENCE", "BUSINESS_OUTCOME_NOT_VERIFIED"}
            and (not isinstance(verified_outcomes, int) or verified_outcomes == 0)
        )

    checks = {
        "gate_operational": data.get("gate_operational") is True,
        "phase9_live_shadow_verified": data.get("phase9_live_shadow_verified") is True,
        "canonical_publication_evidence_is_well_formed": evidence_shape_valid,
        "business_outcome_truth_is_consistent": outcome_truth_consistent,
        "retention_or_verified_decision_is_consistent": (
            data.get("decision") == "ELIGIBLE_FOR_PHASE11_PROMOTION_RETAIN_REPLACE_DECISION"
            if business_verified
            else data.get("decision") == "RETAIN_HF_AS_NON_AUTHORITATIVE_SHADOW_AND_COLLECT_REAL_WORLD_EVIDENCE"
        ),
        "no_production_authority_granted": authority.get("production_decision_authority_granted") is False,
        "no_publish_authority_granted": authority.get("publish_authority_granted") is False,
        "no_provider_replacement_authorized": authority.get("provider_replacement_authorized") is False,
    }

    failures = [name for name, passed in checks.items() if not passed]
    print(json.dumps({
        "checks": checks,
        "evidence": {
            "canonical_published_items": published_items,
            "verified_outcomes_meeting_gate": verified_outcomes,
            "business_outcome_verified": business_verified,
            "verdict": verdict,
        },
        "failures": failures,
    }, indent=2))
    raise SystemExit(1 if failures else 0)


if __name__ == "__main__":
    main()
