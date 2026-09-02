#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

EXPECTED_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
EXPECTED_REVISION = "e8f8c211226b894fcb81acc59f3b34ba3efd5f42"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    args = parser.parse_args()
    path = Path(args.input)
    data = json.loads(path.read_text(encoding="utf-8"))
    raw = path.read_text(encoding="utf-8")

    checks = {
        "capability_verified": data.get("status") == "CAPABILITY_VERIFIED",
        "shadow_only": data.get("mode") == "SHADOW_ONLY",
        "decision_authority_false": data.get("decision_authority") is False,
        "production_effect_none": data.get("production_effect") == "NONE",
        "public_action_false": data.get("public_action_performed") is False,
        "business_outcome_false": data.get("business_outcome_claim") is False,
        "model_exact": (data.get("model") or {}).get("model_id") == EXPECTED_MODEL,
        "revision_exact": (data.get("model") or {}).get("revision") == EXPECTED_REVISION,
        "fixture_all_passed": (data.get("fixture_validation") or {}).get("passed") == (data.get("fixture_validation") or {}).get("total"),
        "corpus_ten_items": (data.get("aura3_corpus_scan") or {}).get("items") == 10,
        "raw_text_not_persisted": (data.get("privacy") or {}).get("raw_text_persisted") is False,
        "embeddings_not_persisted": (data.get("privacy") or {}).get("embedding_vectors_persisted") is False,
        "no_caption_payload_key": '"caption_hi"' not in raw and '"text"' not in raw,
        "no_image_url": "images.unsplash.com" not in raw and '"image"' not in raw,
    }
    failures = [name for name, passed in checks.items() if not passed]
    print(json.dumps({"checks": checks, "failures": failures}, indent=2))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
