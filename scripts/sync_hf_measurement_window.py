#!/usr/bin/env python3
"""Synchronize the HF Phase 10 measurement window from canonical publication evidence.

This script records only observable publication facts. It never fabricates engagement,
enquiries, qualified leads, revenue, or HF-attributed business outcomes.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PUBLISHED = ROOT / "content/published.json"
LEDGER = ROOT / "data/hf_business_outcomes.json"


def load(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def save(path: Path, value) -> None:
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def published_records(payload) -> list[dict]:
    if isinstance(payload, dict):
        return [item for item in payload.values() if isinstance(item, dict)]
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    return []


def published_at(item: dict) -> str | None:
    ig = item.get("instagram") or {}
    value = ig.get("at") or ig.get("published_at") or item.get("published_at")
    return str(value).strip() if value else None


def main() -> int:
    published = load(PUBLISHED, {})
    ledger = load(LEDGER, {})
    records = published_records(published)
    timestamps = sorted(ts for ts in (published_at(item) for item in records) if ts)

    window = ledger.setdefault("measurement_window", {})
    if records:
        window["status"] = "ESTABLISHED"
        if timestamps:
            current_start = window.get("start")
            window["start"] = min([str(current_start)] + timestamps) if current_start else timestamps[0]
        window.setdefault("end", None)
        window["published_items_observed"] = len(records)
        window.setdefault("hf_warning_interventions_observed", 0)
        ledger["ledger_state"] = (
            "VERIFIED_OUTCOMES_RECORDED"
            if ledger.get("verified_outcomes")
            else "MEASUREMENT_ACTIVE_NO_VERIFIED_OUTCOMES"
        )
    else:
        window.setdefault("status", "NOT_ESTABLISHED")
        window.setdefault("start", None)
        window.setdefault("end", None)
        window["published_items_observed"] = 0
        window.setdefault("hf_warning_interventions_observed", 0)

    ledger["last_measurement_sync_at"] = datetime.now(timezone.utc).isoformat()
    ledger["measurement_sync_source"] = "content/published.json"
    ledger["truth_note"] = (
        "Publication establishes a measurement window only. Pending metrics remain NOT_MEASURED "
        "until real observations are recorded; publication does not prove engagement, enquiries, "
        "qualified leads, revenue, or an HF-attributed business outcome."
    )
    save(LEDGER, ledger)

    print(json.dumps({
        "status": window.get("status"),
        "published_items_observed": window.get("published_items_observed"),
        "measurement_start": window.get("start"),
        "verified_outcomes": len(ledger.get("verified_outcomes") or []),
        "business_outcome_claim": False,
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
