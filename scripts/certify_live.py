#!/usr/bin/env python3
import json
from pathlib import Path
from datetime import datetime, timezone
import release_guard

ROOT = Path(__file__).resolve().parents[1]

REQUIRED = [
    "constitution/SOUL.md",
    "constitution/CHARTER.md",
    "governance/department_contract.json",
    "governance/authority_policy.json",
    "governance/capabilities.json",
    "governance/providers.json",
    "governance/evidence_policy.json",
    "governance/heartbeat_policy.json",
    "state/department_state.json",
    "state/control.json",
    "runtime/heartbeat_state.json",
    "runtime/provider_qualification.json",
    "runtime/capability_qualification.json",
]


def load(path):
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def check(condition, name, detail):
    return {"check": name, "pass": bool(condition), "detail": detail}


def fresh(record):
    try:
        stamp = datetime.fromisoformat(record["observed_at"].replace("Z", "+00:00"))
        return stamp.tzinfo is not None and -300 <= (datetime.now(timezone.utc) - stamp).total_seconds() <= 86400
    except (KeyError, TypeError, ValueError):
        return False


def main():
    now = datetime.now(timezone.utc).isoformat()
    missing = [p for p in REQUIRED if not (ROOT / p).exists()]
    checks = [check(not missing, "required_files", f"missing={missing}" if missing else "all present")]
    if missing:
        result = {"department_id":"aura3","certification":"FAILED","live":False,"observed_at":now,"checks":checks}
        print(json.dumps(result, indent=2))
        raise SystemExit(1)

    contract = load("governance/department_contract.json")
    authority = load("governance/authority_policy.json")
    heartbeat_policy = load("governance/heartbeat_policy.json")
    state = load("state/department_state.json")
    control = load("state/control.json")
    hb = load("runtime/heartbeat_state.json")
    providers = load("runtime/provider_qualification.json")
    capabilities = load("runtime/capability_qualification.json")

    checks += [
        check(contract.get("department_id") == "aura3" and contract.get("authority", {}).get("supreme") == "Founder", "constitutional_contract", "AURA3 is Founder-governed and standalone"),
        check(authority.get("rules", {}).get("instagram_publish") == "FOUNDER_ONLY", "public_action_gate", "Instagram publish remains Founder-only"),
        check(heartbeat_policy.get("approved_ladder_minutes") == [60,30,15,10,5,3,2] and heartbeat_policy.get("minimum_minutes") == 2, "heartbeat_policy", "approved adaptive ladder"),
        check(hb.get("runtime_verified") is True, "heartbeat_runtime", hb.get("status", "UNKNOWN")),
        check(providers.get("all_required_qualified") is True, "provider_qualification", providers.get("status", "UNKNOWN")),
        check(capabilities.get("all_required_qualified") is True, "capability_qualification", capabilities.get("status", "UNKNOWN")),
        check(contract.get("future_integrations", {}).get("victor", {}).get("status") == "INACTIVE" and contract.get("future_integrations", {}).get("victor", {}).get("role") == "CREATIVE_BENCH_IDEA_PROMPT_ONLY", "victor_scope", "Victor inactive; future Creative Bench prompt only"),
        check(state.get("constitutional_binding") in {"VERIFIED", "STANDALONE_PHASE_1"}, "runtime_constitutional_binding", state.get("constitutional_binding", "UNKNOWN")),
        check(control.get("kill_switch") is False, "production_activation_gate", "Founder kill switch must be explicitly OFF for LIVE business execution"),
        check(fresh(hb), "heartbeat_evidence_fresh", "heartbeat evidence must be observed within 24 hours"),
        check(fresh(providers), "provider_evidence_fresh", "provider evidence must be observed within 24 hours"),
        check(fresh(capabilities), "capability_evidence_fresh", "capability evidence must be observed within 24 hours"),
    ]

    passed = all(x["pass"] for x in checks)
    result = {
        "department_id": "aura3",
        "certification": "VERIFIED" if passed else "NOT_VERIFIED",
        "live": passed,
        "observed_at": now,
        "truth_rule": "No LIVE claim unless every certification gate passes with fresh runtime evidence.",
        "checks": checks,
    }
    result["release_code_sha256"] = release_guard.release_code_sha256(ROOT)
    print(json.dumps(result, indent=2))
    if not passed:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
