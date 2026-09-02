#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from runtime.hf_shadow import HFShadowEvaluator

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_LABELS = [
    "premium interior design",
    "living room interior",
    "kitchen interior",
    "bedroom interior",
    "bathroom interior",
    "office interior",
    "people-dominated lifestyle photo",
    "outdoor landscape",
    "animal or wildlife",
    "unrelated stock image",
]


def load_calendar() -> list[dict]:
    data = json.loads((ROOT / "content/calendar.json").read_text(encoding="utf-8"))
    return data.get("days") or []


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--execute", action="store_true", help="run local HF shadow inference")
    parser.add_argument("--limit", type=int, default=3)
    parser.add_argument("--post-id", default="")
    parser.add_argument("--output", default="")
    args = parser.parse_args()

    if not args.execute:
        print(json.dumps({
            "department_id": "aura3",
            "status": "SOURCE_READY_EXECUTION_NOT_REQUESTED",
            "mode": "SHADOW_ONLY",
            "production_effect": "NONE",
        }, indent=2))
        return 0

    if os.getenv("AURA3_HF_SHADOW_ALLOW_EXECUTION", "").lower() != "true":
        print("HF shadow execution requires explicit AURA3_HF_SHADOW_ALLOW_EXECUTION=true")
        return 2

    posts = load_calendar()
    if args.post_id:
        posts = [p for p in posts if str(p.get("id")) == args.post_id]
    posts = posts[: max(1, min(args.limit, 10))]
    if not posts:
        print("No eligible posts selected")
        return 2

    evaluator = HFShadowEvaluator()
    results = []
    for post in posts:
        image_url = str(post.get("image") or "")
        row = evaluator.evaluate_url(image_url, DEFAULT_LABELS, force_shadow=True)
        row["post_id"] = post.get("id")
        row["input_classification"] = "NON_SENSITIVE_REFERENCE_IMAGE_ONLY"
        results.append(row)

    evidence = {
        "schema_version": 1,
        "department_id": "aura3",
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "phase": "HF_PHASE1_SHADOW",
        "execution_mode": "SHADOW_ONLY",
        "production_effect": "NONE",
        "public_action_performed": False,
        "business_outcome_claim": False,
        "results": results,
    }
    output = Path(args.output) if args.output else ROOT / "evaluation/results/hf-shadow-latest.json"
    if not output.is_absolute():
        output = ROOT / output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    print(json.dumps(evidence, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
