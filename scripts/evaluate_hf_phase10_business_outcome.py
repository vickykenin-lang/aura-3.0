#!/usr/bin/env python3
import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def published_count(payload):
    if isinstance(payload, list):
        return len(payload)
    if isinstance(payload, dict):
        return len(payload)
    return 0


def is_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def threshold_for(outcome_class, thresholds):
    mapping = {
        "CONTENT_REWRITE_ATTRIBUTED_TO_HF_WARNING": "content_rewrites_attributed_to_warning_min",
        "MEASURED_REVIEW_TIME_REDUCTION": "review_minutes_saved_min",
        "PUBLISHED_CONTENT_DIVERSITY_IMPROVEMENT": "published_content_diversity_change_min_percentage_points",
        "ENGAGEMENT_IMPROVEMENT": "engagement_change_min_percent",
        "ENQUIRY_IMPROVEMENT": "enquiries_change_min_count",
        "QUALIFIED_LEAD_IMPROVEMENT": "qualified_leads_change_min_count",
        "REVENUE_ATTRIBUTED": "revenue_attributed_min_inr",
    }
    key = mapping.get(outcome_class)
    return thresholds.get(key) if key else None


def validate_outcome(item, policy):
    cls = item.get("outcome_class")
    eligible = cls in policy["eligible_outcome_classes"]
    threshold = threshold_for(cls, policy["verification_thresholds"])
    value = item.get("value")
    checks = {
        "eligible_class": eligible,
        "verified_flag": item.get("verified") is True,
        "hf_attribution": bool(item.get("hf_attribution")),
        "source_record": bool(item.get("source_record")),
        "measurement_method": bool(item.get("measurement_method")),
        "measurement_window": bool(item.get("measurement_window")),
        "numeric_value": is_number(value),
        "threshold_met": is_number(value) and is_number(threshold) and value >= threshold,
    }
    return all(checks.values()), checks, threshold


def evaluate(policy, ledger, phase9, published, department_state):
    phase9_live = (
        phase9.get("lifecycle", {}).get("production_deployed") is True
        and phase9.get("lifecycle", {}).get("live_verified") is True
        and phase9.get("privacy_and_authority", {}).get("business_outcome_verified") is False
    )

    pub_count = published_count(published)
    qualified_leads = department_state.get("business_outcome", {}).get("qualified_leads")
    outcomes = ledger.get("verified_outcomes", [])
    outcome_evaluations = []
    verified = []
    for item in outcomes:
        passed, checks, threshold = validate_outcome(item, policy)
        record = {
            "outcome_class": item.get("outcome_class"),
            "value": item.get("value"),
            "threshold": threshold,
            "passed": passed,
            "checks": checks,
        }
        outcome_evaluations.append(record)
        if passed:
            verified.append(record)

    window = ledger.get("measurement_window", {})
    pending = ledger.get("pending_metrics", {})
    measurement_window_established = window.get("status") == "ESTABLISHED"
    pending_real_metrics = [k for k, v in pending.items() if v == "NOT_MEASURED"]

    reason_codes = []
    if not phase9_live:
        reason_codes.append("PHASE9_LIVE_SHADOW_NOT_VERIFIED")
    if pub_count == 0:
        reason_codes.append("NO_CANONICAL_PUBLISHED_ITEMS")
    if qualified_leads in (0, None):
        reason_codes.append("NO_VERIFIED_QUALIFIED_LEAD_OUTCOME")
    if not measurement_window_established:
        reason_codes.append("MEASUREMENT_WINDOW_NOT_ESTABLISHED")
    if not outcomes:
        reason_codes.append("NO_ATTRIBUTED_HF_OUTCOME_RECORDS")
    if pending_real_metrics:
        reason_codes.append("REAL_BUSINESS_METRICS_STILL_NOT_MEASURED")

    if verified and phase9_live:
        verdict = "BUSINESS_OUTCOME_VERIFIED"
        business_outcome_verified = True
    elif not measurement_window_established or pub_count == 0 or not outcomes:
        verdict = "INSUFFICIENT_REAL_WORLD_EVIDENCE"
        business_outcome_verified = False
    else:
        verdict = "BUSINESS_OUTCOME_NOT_VERIFIED"
        business_outcome_verified = False

    return {
        "schema_version": 1,
        "department_id": "aura3",
        "phase": "HF_PHASE10_BUSINESS_OUTCOME_GATE",
        "evaluated_at": datetime.now(timezone.utc).isoformat(),
        "gate_operational": True,
        "verdict": verdict,
        "business_outcome_verified": business_outcome_verified,
        "phase9_live_shadow_verified": phase9_live,
        "evidence_snapshot": {
            "canonical_published_items": pub_count,
            "department_qualified_leads": qualified_leads,
            "measurement_window_status": window.get("status", "MISSING"),
            "hf_warning_interventions_observed": window.get("hf_warning_interventions_observed", 0),
            "verified_outcome_records": len(outcomes),
            "verified_outcomes_meeting_gate": len(verified),
            "not_measured_business_metrics": pending_real_metrics,
        },
        "outcome_evaluations": outcome_evaluations,
        "reason_codes": reason_codes,
        "decision": "RETAIN_HF_AS_NON_AUTHORITATIVE_SHADOW_AND_COLLECT_REAL_WORLD_EVIDENCE" if not business_outcome_verified else "ELIGIBLE_FOR_PHASE11_PROMOTION_RETAIN_REPLACE_DECISION",
        "authority": {
            "production_decision_authority_granted": False,
            "publish_authority_granted": False,
            "provider_replacement_authorized": False,
        },
        "truth_note": "Gate success means evidence was evaluated correctly. BUSINESS_OUTCOME_VERIFIED requires real, attributable evidence and cannot be inferred from model accuracy, workflow success, historical business scores, or lead-generation potential language."
    }


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--policy", default=str(ROOT / "governance/hf_business_outcome_gate.json"))
    p.add_argument("--ledger", default=str(ROOT / "data/hf_business_outcomes.json"))
    p.add_argument("--phase9", default=str(ROOT / "evaluation/HF_PHASE9_SEMANTIC_DEPLOYMENT_STATUS.json"))
    p.add_argument("--published", default=str(ROOT / "content/published.json"))
    p.add_argument("--department-state", default=str(ROOT / "state/department_state.json"))
    p.add_argument("--output", default=str(ROOT / "evaluation/results/hf-phase10-business-outcome.json"))
    args = p.parse_args()

    result = evaluate(
        load_json(args.policy),
        load_json(args.ledger),
        load_json(args.phase9),
        load_json(args.published),
        load_json(args.department_state),
    )
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
