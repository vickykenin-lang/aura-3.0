#!/usr/bin/env python3
import json
import os
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load(path):
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def qualify():
    cfg = load("governance/providers.json")
    results = {}
    for slot, item in cfg["slots"].items():
        secret_name = item["secret_ref"]
        credential_present = bool(os.getenv(secret_name))
        # Credential presence is intentionally not connectivity/model/capability proof.
        results[slot] = {
            "provider": item.get("current_provider"),
            "credential_present": credential_present,
            "connectivity": "NOT_TESTED",
            "model_configured": "NOT_TESTED",
            "capability_tested": "NOT_TESTED",
            "cost_policy": "REQUIRES_CHECK",
            "qualification": "NOT_VERIFIED"
        }
    return {
        "department_id": "aura3",
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "providers": results,
        "live_claim": "NOT_VERIFIED"
    }


if __name__ == "__main__":
    print(json.dumps(qualify(), separators=(",", ":")))
