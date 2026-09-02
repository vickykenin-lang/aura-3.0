#!/usr/bin/env python3
import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load(path: str):
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def main():
    phase7 = load("evaluation/HF_PHASE7_LIVE_STATUS.json")
    phase9 = load("evaluation/HF_PHASE9_SEMANTIC_DEPLOYMENT_STATUS.json")
    phase10 = load("evaluation/HF_PHASE10_BUSINESS_OUTCOME_STATUS.json")
    providers = load("governance/providers.json")
    models = load("hf/model_registry.json")
    semantic_models = load("hf/semantic_model_registry.json")

    siglip_live = phase7.get("status") == "LIVE_VERIFIED"
    semantic_live = phase9.get("status") == "LIVE_SHADOW_VERIFIED_AND_INSTRUMENTED"
    business_verified = bool(phase10.get("business_outcome_verified"))

    siglip_slot = providers["slots"]["HF_EVALUATION_PROVIDER"]
    semantic_slot = providers["slots"]["HF_SEMANTIC_PROVIDER"]

    siglip_safe_shadow = (
        siglip_live
        and siglip_slot.get("production_authority") is False
        and siglip_slot.get("required_for_business_execution") is False
        and phase7.get("verified_controls", {}).get("production_effect_none") is True
        and phase7.get("verified_controls", {}).get("public_action_performed") is False
    )
    semantic_safe_shadow = (
        semantic_live
        and semantic_slot.get("production_authority") is False
        and semantic_slot.get("required_for_business_execution") is False
        and phase9.get("privacy_and_authority", {}).get("production_effect") == "NONE"
        and phase9.get("privacy_and_authority", {}).get("public_action_performed") is False
    )

    siglip_disposition = "RETAIN_SHADOW_SPECIALIST" if siglip_safe_shadow and not business_verified else "REVIEW_REQUIRED"
    semantic_disposition = "RETAIN_SHADOW_SPECIALIST" if semantic_safe_shadow and not business_verified else "REVIEW_REQUIRED"

    blip = models["models"]["blip_caption_candidate"]
    blip_disposition = (
        "KEEP_DISABLED_CANDIDATE"
        if blip.get("enabled_for_shadow") is False and blip.get("production_authority") is False
        else "REVIEW_REQUIRED"
    )

    promote = business_verified and siglip_live and semantic_live
    qualify_fallback = False
    replace_existing = False
    remove_hf = False

    result = {
        "schema_version": 1,
        "department_id": "aura3",
        "phase": "HF_PHASE11_FINAL_DISPOSITION",
        "evaluated_at": datetime.now(timezone.utc).isoformat(),
        "status": "FINAL_DISPOSITION_VERIFIED" if all(
            x != "REVIEW_REQUIRED" for x in [siglip_disposition, semantic_disposition, blip_disposition]
        ) else "REVIEW_REQUIRED",
        "overall_decision": "RETAIN_HF_AS_NON_AUTHORITATIVE_SPECIALIST_LAYER",
        "business_outcome_verified": business_verified,
        "capability_decisions": {
            "siglip_image_relevance": {
                "model_id": models["models"]["siglip_primary"]["model_id"],
                "disposition": siglip_disposition,
                "live_verified": siglip_live,
                "production_authority": False,
                "qualified_scope": models["models"]["siglip_primary"]["qualified_scope"],
                "reason": "Live shadow value is verified and isolated; business outcome is not verified, so promotion/fallback/replacement is not justified."
            },
            "multilingual_semantic_memory": {
                "model_id": semantic_models["models"]["multilingual_minilm_primary"]["model_id"],
                "disposition": semantic_disposition,
                "live_verified": semantic_live,
                "production_authority": False,
                "qualified_scope": semantic_models["models"]["multilingual_minilm_primary"]["qualified_scope"],
                "reason": "Live semantic warning/diversity signals are verified and non-blocking; real attributable business value is not yet verified."
            },
            "blip_caption_candidate": {
                "model_id": blip["model_id"],
                "disposition": blip_disposition,
                "live_verified": False,
                "production_authority": False,
                "reason": "Candidate remains untested and outside the active execution path; no reason to introduce it now."
            }
        },
        "strategic_actions": {
            "promote_to_production_decision_authority": promote,
            "qualify_as_production_fallback": qualify_fallback,
            "replace_gemini_or_deepseek": replace_existing,
            "remove_hf_layer": remove_hf,
            "retain_shadow_specialists": True,
            "continue_business_outcome_measurement": True
        },
        "evidence_basis": {
            "siglip_live_verified": siglip_live,
            "semantic_live_verified": semantic_live,
            "phase10_gate_operational": phase10.get("status") == "GATE_OPERATIONAL_OUTCOME_NOT_VERIFIED",
            "phase10_business_outcome_verdict": phase10.get("business_outcome_verdict"),
            "business_outcome_verified": business_verified,
            "canonical_published_items": phase10.get("current_real_world_evidence", {}).get("canonical_published_items"),
            "qualified_leads": phase10.get("current_real_world_evidence", {}).get("department_qualified_leads"),
            "verified_outcome_records": phase10.get("current_real_world_evidence", {}).get("verified_outcome_records"),
            "siglip_safe_shadow": siglip_safe_shadow,
            "semantic_safe_shadow": semantic_safe_shadow
        },
        "future_reconsideration": {
            "automatic_promotion": False,
            "reopen_decision_when": [
                "PHASE10_BUSINESS_OUTCOME_VERIFIED",
                "SECURITY_OR_LICENCE_POSTURE_CHANGES",
                "MATERIAL_COST_CHANGE",
                "MODEL_OR_PROVIDER_DEPRECATION",
                "PROVEN_NEGATIVE_BUSINESS_IMPACT"
            ],
            "rule": "New evidence may reopen the decision, but cannot silently grant authority or replace an existing provider."
        },
        "truth_note": "Phase 11 formalizes current disposition. RETAIN is not PROMOTE: Hugging Face remains a replaceable, non-authoritative specialist layer while Gemini/DeepSeek production authority is unchanged."
    }

    out = ROOT / "evaluation/results/hf-phase11-final-disposition.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
