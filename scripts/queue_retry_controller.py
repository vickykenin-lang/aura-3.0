#!/usr/bin/env python3
"""Compatibility controller for the retired AURA3 self-retry chain.

AURA3 queue production is event-driven. This module remains only so older
callers/tests fail safe: it never authorizes an autonomous chained refill.
Founder rejection and verified Instagram publication are the only normal
refill triggers. The hourly watchdog is health-only and does not generate.
"""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
IST = timezone(timedelta(hours=5, minutes=30))
STATUS_PATH = ROOT / "data/approval_queue_status.json"
STATE_PATH = ROOT / "data/queue_retry_state.json"

HARD_BLOCK_STATUSES = {
    "REFILL_BLOCKED_PROVIDER_PREFLIGHT",
    "REFILL_BLOCKED_CONFIGURATION",
    "REFILL_BLOCKED_GOVERNANCE",
    "REFILL_BLOCKED_GEMINI_PROJECT_BILLING",
}


def load_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def save_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def as_int(value, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def decide(status: dict, attempt: int, max_chain_attempts: int, maintain_exit_code: int) -> dict:
    """Return a fail-safe no-self-retry decision for all current states."""
    target = max(1, as_int(status.get("target"), 20))
    ready = max(0, as_int(status.get("approval_ready"), 0))
    deficit = max(0, target - ready)
    queue_status = str(status.get("status") or "UNKNOWN").strip().upper()
    errors = list(status.get("technical_errors") or [])
    generated = max(0, as_int(status.get("generated_this_run"), 0))
    unique_pool_available = max(0, as_int(status.get("unique_pool_available"), 0))

    if deficit == 0 or ready >= target:
        reason = "TARGET_REACHED"
    elif queue_status in HARD_BLOCK_STATUSES:
        reason = (
            "GEMINI_PROJECT_BILLING_HARD_BLOCK"
            if queue_status == "REFILL_BLOCKED_GEMINI_PROJECT_BILLING"
            else "HARD_BLOCK_STATUS"
        )
    elif maintain_exit_code != 0:
        reason = "MAINTAINER_FAILURE_WAIT_FOR_EVENT_OR_MANUAL_REPAIR"
    else:
        reason = "EVENT_DRIVEN_WAIT_FOR_TRIGGER"

    return {
        "schema_version": 2,
        "department_id": "aura3",
        "queue_status": queue_status,
        "approval_ready": ready,
        "target": target,
        "deficit": deficit,
        "chain_attempt": max(0, attempt),
        "max_chain_attempts": max(0, max_chain_attempts),
        "next_chain_attempt": max(0, attempt),
        "maintainer_exit_code": maintain_exit_code,
        "technical_error_count": len(errors),
        "generated_this_run": generated,
        "unique_pool_available": unique_pool_available,
        "should_retry": False,
        "cooldown_seconds": 0,
        "reason": reason,
        "fallback": "EVENT_DRIVEN_REFILL_PLUS_READ_ONLY_HOURLY_WATCHDOG",
        "observed_at": datetime.now(IST).isoformat(),
        "truth_note": "Autonomous chained queue retries are disabled. AURA3 refills only after Founder rejection or verified Instagram publication, or by an explicit Founder/manual dispatch. The hourly watchdog performs health inspection only and never calls image/provider generation.",
    }


def write_github_outputs(decision: dict) -> None:
    output_path = os.environ.get("GITHUB_OUTPUT")
    if not output_path:
        return
    pairs = {
        "should_retry": "false",
        "cooldown_seconds": "0",
        "next_chain_attempt": str(decision["next_chain_attempt"]),
        "reason": str(decision["reason"]),
        "approval_ready": str(decision["approval_ready"]),
        "target": str(decision["target"]),
        "deficit": str(decision["deficit"]),
    }
    with open(output_path, "a", encoding="utf-8") as handle:
        for key, value in pairs.items():
            handle.write(f"{key}={value}\n")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--attempt", type=int, default=0)
    parser.add_argument("--max-chain-attempts", type=int, default=3)
    parser.add_argument("--maintain-exit-code", type=int, default=0)
    args = parser.parse_args()

    status = load_json(STATUS_PATH, {})
    decision = decide(
        status=status,
        attempt=max(0, args.attempt),
        max_chain_attempts=max(0, args.max_chain_attempts),
        maintain_exit_code=args.maintain_exit_code,
    )
    save_json(STATE_PATH, decision)
    write_github_outputs(decision)
    print(json.dumps(decision, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
