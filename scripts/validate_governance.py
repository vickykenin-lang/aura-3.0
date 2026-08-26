#!/usr/bin/env python3
import json
from pathlib import Path

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
]

def load(path):
    return json.loads((ROOT / path).read_text(encoding="utf-8"))

def main():
    missing = [p for p in REQUIRED if not (ROOT / p).exists()]
    if missing:
        raise SystemExit("INVALID_CONSTITUTIONAL_BINDING missing=" + ",".join(missing))
    contract = load("governance/department_contract.json")
    authority = load("governance/authority_policy.json")
    heartbeat = load("governance/heartbeat_policy.json")
    control = load("state/control.json")
    if contract.get("department_id") != "aura3" or contract.get("organizational_orchestrator") != "victor":
        raise SystemExit("INVALID_CONSTITUTIONAL_BINDING contract")
    if authority.get("rules", {}).get("instagram_publish") != "FOUNDER_ONLY":
        raise SystemExit("INVALID_AUTHORITY_BOUNDARY instagram_publish")
    if heartbeat.get("approved_ladder_minutes") != [60,30,15,10,5,3,2] or heartbeat.get("minimum_minutes") != 2:
        raise SystemExit("INVALID_HEARTBEAT_POLICY")
    result = {
        "department_id": "aura3",
        "constitutional_binding": "VERIFIED",
        "business_execution_eligible": not bool(control.get("kill_switch")),
        "kill_switch": bool(control.get("kill_switch")),
        "live_certification": "NOT_VERIFIED",
        "note": "Constitutional binding is verified; this alone does not prove LIVE."
    }
    print(json.dumps(result, separators=(",", ":")))

if __name__ == "__main__":
    main()
