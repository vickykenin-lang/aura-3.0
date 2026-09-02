import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class Phase11DispositionTests(unittest.TestCase):
    def test_phase10_business_outcome_is_not_verified(self):
        data = json.loads((ROOT / "evaluation/HF_PHASE10_BUSINESS_OUTCOME_STATUS.json").read_text())
        self.assertFalse(data["business_outcome_verified"])
        self.assertEqual(data["business_outcome_verdict"], "INSUFFICIENT_REAL_WORLD_EVIDENCE")

    def test_live_shadow_capabilities_are_non_authoritative(self):
        providers = json.loads((ROOT / "governance/providers.json").read_text())
        for slot in ("HF_EVALUATION_PROVIDER", "HF_SEMANTIC_PROVIDER"):
            self.assertFalse(providers["slots"][slot]["production_authority"])
            self.assertFalse(providers["slots"][slot]["required_for_business_execution"])

    def test_siglip_live_evidence_exists(self):
        phase7 = json.loads((ROOT / "evaluation/HF_PHASE7_LIVE_STATUS.json").read_text())
        self.assertEqual(phase7["status"], "LIVE_VERIFIED")
        self.assertTrue(phase7["lifecycle"]["live_verified"])

    def test_semantic_live_evidence_exists(self):
        phase9 = json.loads((ROOT / "evaluation/HF_PHASE9_SEMANTIC_DEPLOYMENT_STATUS.json").read_text())
        self.assertEqual(phase9["status"], "LIVE_SHADOW_VERIFIED_AND_INSTRUMENTED")
        self.assertTrue(phase9["lifecycle"]["live_verified"])

    def test_blip_remains_disabled_candidate(self):
        models = json.loads((ROOT / "hf/model_registry.json").read_text())
        blip = models["models"]["blip_caption_candidate"]
        self.assertFalse(blip["enabled_for_shadow"])
        self.assertFalse(blip["production_authority"])
        self.assertEqual(blip["qualification"], "CANDIDATE_NOT_TESTED")


if __name__ == "__main__":
    unittest.main()
