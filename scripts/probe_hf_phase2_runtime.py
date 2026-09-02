#!/usr/bin/env python3
from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.hf_shadow import HFShadowEvaluator, load_json

OUT = ROOT / "evaluation/results/hf-phase2-runtime-probe.json"


def main() -> int:
    calendar = json.loads((ROOT / "content/calendar.json").read_text(encoding="utf-8"))
    post = (calendar.get("days") or [])[0]
    config = copy.deepcopy(load_json("hf/config.json"))
    config["execution"]["transient_retries"] = 0
    config["execution"]["circuit_breaker"]["failure_threshold"] = 10
    evaluator = HFShadowEvaluator(config=config)
    result = evaluator.evaluate_url(
        str(post.get("image") or ""),
        ["a living room interior", "a kitchen interior", "a bedroom interior"],
        force_shadow=True,
    )
    evidence = {
        "schema_version": 1,
        "department_id": "aura3",
        "phase": "HF_PHASE2_RUNTIME_PROBE",
        "post_id": post.get("id"),
        "input_classification": "PUBLIC_NON_SENSITIVE_REFERENCE_IMAGE",
        "production_effect": "NONE",
        "result": result,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    print(json.dumps(evidence, indent=2))
    return 0 if result.get("status") == "SHADOW_RESULT" else 2


if __name__ == "__main__":
    raise SystemExit(main())
