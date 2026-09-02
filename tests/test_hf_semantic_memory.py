import json
import unittest
from pathlib import Path

from runtime.hf_semantic_memory import SimilarityPolicy, text_fingerprint

ROOT = Path(__file__).resolve().parents[1]


class SemanticMemoryContractTests(unittest.TestCase):
    def test_threshold_contract(self):
        policy = SimilarityPolicy(duplicate_min=0.90, repetitive_theme_min=0.75)
        self.assertEqual(policy.classify(0.95), "DUPLICATE")
        self.assertEqual(policy.classify(0.90), "DUPLICATE")
        self.assertEqual(policy.classify(0.80), "REPETITIVE_THEME")
        self.assertEqual(policy.classify(0.75), "REPETITIVE_THEME")
        self.assertEqual(policy.classify(0.7499), "DISTINCT")

    def test_fingerprint_normalizes_case_and_whitespace(self):
        self.assertEqual(
            text_fingerprint("  Modular   Kitchen "),
            text_fingerprint("modular kitchen"),
        )

    def test_semantic_layer_is_disabled_and_non_authoritative(self):
        cfg = json.loads((ROOT / "hf" / "semantic_config.json").read_text(encoding="utf-8"))
        self.assertFalse(cfg["enabled"])
        self.assertEqual(cfg["mode"], "SHADOW_ONLY")
        self.assertFalse(cfg["decision_authority"])
        self.assertEqual(cfg["production_effect"], "NONE")
        self.assertFalse(cfg["data_policy"]["confidential_client_text_allowed"])
        self.assertFalse(cfg["data_policy"]["lead_or_contact_data_allowed"])
        self.assertFalse(cfg["data_policy"]["raw_text_persisted_in_evidence"])
        self.assertFalse(cfg["data_policy"]["embedding_vectors_persisted_in_evidence"])

    def test_model_is_pinned_and_remote_code_blocked(self):
        reg = json.loads((ROOT / "hf" / "semantic_model_registry.json").read_text(encoding="utf-8"))
        model = reg["models"]["multilingual_minilm_primary"]
        self.assertEqual(model["model_id"], "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2")
        self.assertEqual(model["revision"], "e8f8c211226b894fcb81acc59f3b34ba3efd5f42")
        self.assertEqual(model["license"], "apache-2.0")
        self.assertFalse(model["trust_remote_code"])
        self.assertTrue(model["require_safetensors"])


if __name__ == "__main__":
    unittest.main()
