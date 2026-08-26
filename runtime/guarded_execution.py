#!/usr/bin/env python3
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load(path):
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def authorize(action, actor="runtime"):
    authority = load("governance/authority_policy.json")["rules"].get(action, "PROHIBITED")
    control = load("state/control.json")
    if authority == "PROHIBITED":
        return {"authorized": False, "reason": "PROHIBITED"}
    if control.get("kill_switch", True) and action not in {"analyze_and_report","persist_internal_runtime_state"}:
        return {"authorized": False, "reason": "KILL_SWITCH_DIAGNOSTIC_ONLY", "authority": authority}
    if authority == "FOUNDER_ONLY" and actor != "founder":
        return {"authorized": False, "reason": "FOUNDER_APPROVAL_REQUIRED", "authority": authority}
    if authority == "VICTOR_AUTHORIZATION" and actor not in {"victor","founder"}:
        return {"authorized": False, "reason": "VICTOR_AUTHORIZATION_REQUIRED", "authority": authority}
    return {"authorized": True, "authority": authority}


if __name__ == "__main__":
    print(json.dumps(authorize("instagram_publish"), separators=(",", ":")))
