#!/usr/bin/env python3
import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LADDER = [60, 30, 15, 10, 5, 3, 2]


def load(path):
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def choose_minutes(score, state):
    if state == "PAUSED":
        return 60
    if state == "CRITICAL":
        return 2
    score = max(0, min(100, int(score)))
    if score <= 20: return 60
    if score <= 35: return 30
    if score <= 50: return 15
    if score <= 65: return 10
    if score <= 80: return 5
    if score <= 90: return 3
    return 2


def heartbeat(priority_score=0):
    policy = load("governance/heartbeat_policy.json")
    contract = load("governance/department_contract.json")
    control = load("state/control.json")
    state = load("state/department_state.json")
    binding_ok = (
        contract.get("department_id") == "aura3"
        and contract.get("organizational_orchestrator") == "victor"
        and policy.get("approved_ladder_minutes") == LADDER
        and policy.get("minimum_minutes") == 2
    )
    business_eligible = binding_ok and not control.get("kill_switch", True) and control.get("business_execution_enabled") is True
    now = datetime.now(timezone.utc).isoformat()
    return {
        "department_id": "aura3",
        "observed_at": now,
        "cycle": "HEARTBEAT_DIAGNOSTIC",
        "constitutional_binding": "VALID" if binding_ok else "INVALID",
        "department_state": state.get("department_state", "UNKNOWN"),
        "kill_switch": bool(control.get("kill_switch", True)),
        "business_execution_eligible": business_eligible,
        "execution_mode": "BUSINESS_ELIGIBLE" if business_eligible else "DIAGNOSTIC_ONLY",
        "priority_score": int(priority_score),
        "next_wake_minutes": choose_minutes(priority_score, state.get("department_state", "PAUSED")),
        "live_certification": "NOT_VERIFIED"
    }


if __name__ == "__main__":
    print(json.dumps(heartbeat(), separators=(",", ":")))
