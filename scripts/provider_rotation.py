#!/usr/bin/env python3
"""Alternate AURA3 production cycles between DeepSeek and Amazon Nova.

Odd cycles: DeepSeek. Even cycles: Amazon Nova 2 Lite.
The same queue, image rulebook, caption grounding, business gate thresholds,
Founder approval and publishing controls remain in force.
"""
from __future__ import annotations

import json
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import aura3_resilient_queue as resilient

ROOT = Path(__file__).resolve().parents[1]
STATE_PATH = ROOT / "data/provider_rotation_state.json"
METRICS_PATH = ROOT / "data/provider_comparison.json"
IST = timezone(timedelta(hours=5, minutes=30))
PROVIDERS = ("deepseek", "nova")


def _load(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def _save(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _state() -> dict:
    state = _load(STATE_PATH, {})
    next_provider = str(state.get("next_provider") or "deepseek").lower()
    if next_provider not in PROVIDERS:
        next_provider = "deepseek"
    return {
        "schema_version": 1,
        "department_id": "aura3",
        "mode": "ALTERNATING_DEEPSEEK_NOVA",
        "next_provider": next_provider,
        "completed_cycles": int(state.get("completed_cycles", 0) or 0),
        "last_provider": state.get("last_provider"),
        "last_run_id": state.get("last_run_id"),
        "updated_at": state.get("updated_at"),
    }


def _install(provider: str) -> tuple[str, str]:
    if provider == "nova":
        import aura3_nova_runtime as nova
        nova.install_into_resilient_runtime()
        return "aws_bedrock_nova", nova.model_id()
    return "deepseek", os.environ.get("DEEPSEEK_MODEL", "deepseek-v4-flash")


def _append_metrics(provider: str, provider_label: str, model: str, exit_code: int, elapsed: float, started_at: str) -> None:
    status = _load(ROOT / "data/approval_queue_status.json", {})
    gates = _load(ROOT / "data/gate_results.json", {})
    metrics = _load(METRICS_PATH, {"schema_version": 1, "department_id": "aura3", "mode": "ALTERNATING_DEEPSEEK_NOVA", "cycles": []})
    cycles = list(metrics.get("cycles") or [])
    cycles.append({
        "cycle_index": len(cycles) + 1,
        "started_at": started_at,
        "completed_at": datetime.now(IST).isoformat(),
        "github_run_id": os.environ.get("GITHUB_RUN_ID", ""),
        "provider": provider,
        "provider_label": provider_label,
        "model": model,
        "exit_code": int(exit_code),
        "elapsed_seconds": round(elapsed, 2),
        "queue_status": status.get("status"),
        "approval_ready": int(status.get("approval_ready", 0) or 0),
        "target": int(status.get("target", 20) or 20),
        "generated": int(status.get("generated_this_run", 0) or 0),
        "gate_pass_count": len(status.get("gate_pass_ids") or []),
        "gate_reject_count": len(status.get("gate_reject_ids") or []),
        "technical_error_count": len(status.get("technical_errors") or []),
        "pipeline": gates.get("pipeline"),
        "vision_models": gates.get("vision_models") or [],
        "business_model": gates.get("business_model"),
        "truth_note": "Provider comparison evidence only; Founder approval and publishing authority are unchanged.",
    })
    metrics["cycles"] = cycles[-100:]
    summary = {}
    for name in PROVIDERS:
        rows = [row for row in metrics["cycles"] if row.get("provider") == name]
        if not rows:
            continue
        summary[name] = {
            "cycles": len(rows),
            "successful_cycles": sum(1 for row in rows if int(row.get("exit_code", 1)) == 0),
            "generated_total": sum(int(row.get("generated", 0) or 0) for row in rows),
            "gate_pass_total": sum(int(row.get("gate_pass_count", 0) or 0) for row in rows),
            "gate_reject_total": sum(int(row.get("gate_reject_count", 0) or 0) for row in rows),
            "technical_errors_total": sum(int(row.get("technical_error_count", 0) or 0) for row in rows),
            "average_elapsed_seconds": round(sum(float(row.get("elapsed_seconds", 0) or 0) for row in rows) / len(rows), 2),
        }
    metrics["summary"] = summary
    metrics["updated_at"] = datetime.now(IST).isoformat()
    _save(METRICS_PATH, metrics)


def main() -> int:
    state = _state()
    scheduled_provider = state["next_provider"]
    provider = scheduled_provider
    started_at = datetime.now(IST).isoformat()
    start = time.monotonic()

    # Nova is allowed to fail over to DeepSeek if AWS credentials are absent. The
    # event is recorded, but production does not stop solely because the alternate
    # provider is unavailable.
    if provider == "nova":
        aws_ready = bool((os.environ.get("AWS_ACCESS_KEY_ID") or "").strip() and (os.environ.get("AWS_SECRET_ACCESS_KEY") or "").strip())
        if not aws_ready:
            resilient._record_incident("NOVA_CREDENTIALS_UNAVAILABLE_FALLBACK", "provider_rotation", "falling back to DeepSeek for this cycle")
            provider = "deepseek"

    provider_label, model = _install(provider)
    os.environ["AURA3_ACTIVE_PROVIDER"] = provider_label
    print(json.dumps({
        "provider_rotation": "SELECTED",
        "scheduled_provider": scheduled_provider,
        "active_provider": provider,
        "model": model,
        "completed_cycles_before": state["completed_cycles"],
    }))

    exit_code = resilient.main()
    elapsed = time.monotonic() - start
    _append_metrics(provider, provider_label, model, exit_code, elapsed, started_at)

    # Rotation advances after every completed attempt so the next event tests the
    # other provider. This remains independent of publishing approval.
    next_provider = "nova" if scheduled_provider == "deepseek" else "deepseek"
    state.update({
        "next_provider": next_provider,
        "completed_cycles": state["completed_cycles"] + 1,
        "last_provider": provider,
        "last_scheduled_provider": scheduled_provider,
        "last_model": model,
        "last_exit_code": int(exit_code),
        "last_run_id": os.environ.get("GITHUB_RUN_ID", ""),
        "updated_at": datetime.now(IST).isoformat(),
    })
    _save(STATE_PATH, state)
    print(json.dumps({
        "provider_rotation": "COMPLETED",
        "active_provider": provider,
        "exit_code": int(exit_code),
        "next_provider": next_provider,
    }))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
