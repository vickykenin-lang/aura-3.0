#!/usr/bin/env python3
import argparse
import json
from pathlib import Path


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--input", required=True)
    args = p.parse_args()
    data = json.loads(Path(args.input).read_text(encoding="utf-8"))

    checks = {
        "gate_operational": data.get("gate_operational") is True,
        "phase9_live_shadow_verified": data.get("phase9_live_shadow_verified") is True,
        "business_outcome_not_fabricated": data.get("business_outcome_verified") is False,
        "current_verdict_insufficient_evidence": data.get("verdict") == "INSUFFICIENT_REAL_WORLD_EVIDENCE",
        "no_published_items_detected": data.get("evidence_snapshot", {}).get("canonical_published_items") == 0,
        "qualified_leads_zero_detected": data.get("evidence_snapshot", {}).get("department_qualified_leads") == 0,
        "no_verified_outcomes": data.get("evidence_snapshot", {}).get("verified_outcomes_meeting_gate") == 0,
        "retention_decision_is_shadow_only": data.get("decision") == "RETAIN_HF_AS_NON_AUTHORITATIVE_SHADOW_AND_COLLECT_REAL_WORLD_EVIDENCE",
        "no_production_authority_granted": data.get("authority", {}).get("production_decision_authority_granted") is False,
        "no_publish_authority_granted": data.get("authority", {}).get("publish_authority_granted") is False,
        "no_provider_replacement_authorized": data.get("authority", {}).get("provider_replacement_authorized") is False,
    }
    failures = [name for name, passed in checks.items() if not passed]
    print(json.dumps({"checks": checks, "failures": failures}, indent=2))
    raise SystemExit(1 if failures else 0)


if __name__ == "__main__":
    main()
