#!/usr/bin/env python3
import argparse
import json
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    args = parser.parse_args()

    data = json.loads(Path(args.input).read_text(encoding="utf-8"))
    caps = data.get("capability_decisions", {})
    actions = data.get("strategic_actions", {})

    checks = {
        "final_disposition_verified": data.get("status") == "FINAL_DISPOSITION_VERIFIED",
        "overall_retain_non_authoritative": data.get("overall_decision") == "RETAIN_HF_AS_NON_AUTHORITATIVE_SPECIALIST_LAYER",
        "business_outcome_not_fabricated": data.get("business_outcome_verified") is False,
        "siglip_retained_shadow": caps.get("siglip_image_relevance", {}).get("disposition") == "RETAIN_SHADOW_SPECIALIST",
        "semantic_retained_shadow": caps.get("multilingual_semantic_memory", {}).get("disposition") == "RETAIN_SHADOW_SPECIALIST",
        "blip_kept_disabled": caps.get("blip_caption_candidate", {}).get("disposition") == "KEEP_DISABLED_CANDIDATE",
        "no_promotion": actions.get("promote_to_production_decision_authority") is False,
        "no_production_fallback": actions.get("qualify_as_production_fallback") is False,
        "no_provider_replacement": actions.get("replace_gemini_or_deepseek") is False,
        "no_removal": actions.get("remove_hf_layer") is False,
        "retain_shadow_specialists": actions.get("retain_shadow_specialists") is True,
        "continue_measurement": actions.get("continue_business_outcome_measurement") is True,
        "no_automatic_future_promotion": data.get("future_reconsideration", {}).get("automatic_promotion") is False,
    }
    failures = [name for name, passed in checks.items() if not passed]
    print(json.dumps({"checks": checks, "failures": failures}, indent=2))
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
