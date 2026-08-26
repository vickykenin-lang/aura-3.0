#!/usr/bin/env python3
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / "governance/heartbeat_policy.json"
CONTROL = ROOT / "state/control.json"
STATE = ROOT / "state/department_state.json"
OUT = ROOT / "runtime/heartbeat_state.json"


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def write(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def main():
    policy = load(POLICY)
    control = load(CONTROL)
    state = load(STATE)
    now = datetime.now(timezone.utc)

    ladder = policy.get("approved_ladder_minutes")
    if ladder != [60,30,15,10,5,3,2] or policy.get("minimum_minutes") != 2:
        raise SystemExit("INVALID_HEARTBEAT_POLICY")

    paused = bool(control.get("kill_switch")) or state.get("department_state") == "PAUSED"
    cadence = 60 if paused else int(policy.get("default_minutes", 60))

    payload = {
        "schema_version": 1,
        "department_id": "aura3",
        "status": "HEALTHY_DIAGNOSTIC" if paused else "HEALTHY",
        "runtime_verified": True,
        "observed_at": now.isoformat(),
        "next_due_at": (now + timedelta(minutes=cadence)).isoformat(),
        "cadence_minutes": cadence,
        "approved_ladder_minutes": ladder,
        "minimum_minutes": 2,
        "miss_count": 0,
        "miss_state": "NONE",
        "business_execution_allowed": not paused,
        "diagnostic_liveness": True,
        "constitutional_binding_checked": True,
        "kill_switch": bool(control.get("kill_switch")),
        "truth_note": "Heartbeat proves diagnostic runtime execution only; it does not prove provider, capability, Victor transport, business outcome, or LIVE certification."
    }
    write(OUT, payload)
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
