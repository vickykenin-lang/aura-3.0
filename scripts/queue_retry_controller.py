#!/usr/bin/env python3
"""Decide whether AURA3 should self-trigger another approval-queue cycle.

The controller is deliberately bounded: it can request only a small number of
chained retries, applies cooldowns for transient provider/qualification issues,
and falls back to the existing hourly/event triggers after the circuit breaker.
It never grants approval or publishing authority.
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
    target = max(1, as_int(status.get("target"), 20))
    ready = max(0, as_int(status.get("approval_ready"), 0))
    deficit = max(0, target - ready)
    queue_status = str(status.get("status") or "UNKNOWN").strip().upper()
    errors = list(status.get("technical_errors") or [])
    generated = max(0, as_int(status.get("generated_this_run"), 0))
    unique_pool_available = max(0, as_int(status.get("unique_pool_available"), 0))

    should_retry = False
    cooldown_seconds = 0
    reason = "NO_RETRY"

    if deficit == 0 or ready >= target:
        reason = "TARGET_REACHED"
    elif queue_status in HARD_BLOCK_STATUSES:
        reason = "HARD_BLOCK_STATUS"
    elif maintain_exit_code != 0 and queue_status != "QUEUE_PARTIAL_TECHNICAL_ERROR":
        reason = "NON_TRANSIENT_MAINTAINER_FAILURE"
    elif attempt >= max_chain_attempts:
        reason = "CHAIN_CIRCUIT_BREAKER"
    else:
        should_retry = True
        if errors:
            cooldown_seconds = min(240, 60 + (30 * len(errors)))
            reason = "TRANSIENT_QUALIFICATION_COOLDOWN"
        elif generated == 0 and unique_pool_available == 0:
            cooldown_seconds = 90
            reason = "REFRESH_VISUAL_POOL_AND_RETRY"
        else:
            cooldown_seconds = 30
            reason = "DEFICIT_REMAINS"

    return {
        "schema_version": 1,
        "department_id": "aura3",
        "queue_status": queue_status,
        "approval_ready": ready,
        "target": target,
        "deficit": deficit,
        "chain_attempt": attempt,
        "max_chain_attempts": max_chain_attempts,
        "next_chain_attempt": attempt + 1 if should_retry else attempt,
        "maintainer_exit_code": maintain_exit_code,
        "technical_error_count": len(errors),
        "generated_this_run": generated,
        "unique_pool_available": unique_pool_available,
        "should_retry": should_retry,
        "cooldown_seconds": cooldown_seconds,
        "reason": reason,
        "fallback": "EXISTING_HOURLY_AND_EVENT_TRIGGERS_REMAIN_ACTIVE",
        "observed_at": datetime.now(IST).isoformat(),
        "truth_note": "AURA3 may self-trigger only while the Founder approval queue is below target, within the bounded chain limit. Provider/qualification issues receive cooldown. Founder approval and Instagram publishing authority remain unchanged.",
    }


def write_github_outputs(decision: dict) -> None:
    output_path = os.environ.get("GITHUB_OUTPUT")
    if not output_path:
        return
    pairs = {
        "should_retry": str(bool(decision["should_retry"])).lower(),
        "cooldown_seconds": str(decision["cooldown_seconds"]),
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
