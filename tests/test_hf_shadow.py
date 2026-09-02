import json
import unittest
from pathlib import Path

from runtime.hf_shadow import CircuitBreaker, HFShadowEvaluator, validate_shadow_contract

ROOT = Path(__file__).resolve().parents[1]


def load(path):
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


class FakeAdapter:
    def __init__(self, model, config):
        self.model = model

    def evaluate(self, image_bytes, candidate_labels):
        return {
            "task": "zero-shot-image-classification",
            "model_id": self.model["model_id"],
            "revision": self.model["revision"],
            "ranked_labels": [{"label": candidate_labels[0], "score": 0.9}],
            "top_label": candidate_labels[0],
            "top_score": 0.9,
        }


class HFShadowContractTests(unittest.TestCase):
    def test_phase1_is_non_authoritative_and_disabled_by_default(self):
        config = load("hf/config.json")
        self.assertFalse(config["enabled"])
        self.assertEqual(config["mode"], "SHADOW_ONLY")
        self.assertFalse(config["production_authority"])
        self.assertFalse(config["required_for_business_execution"])

    def test_primary_model_is_pinned_and_remote_code_disabled(self):
        config = load("hf/config.json")
        models = load("hf/model_registry.json")
        licences = load("hf/licence_registry.json")
        model = models["models"][config["primary_model"]]
        key = f"{model['model_id']}@{model['revision']}"
        validate_shadow_contract(config, model, licences["entries"][key])
        self.assertTrue(model["revision"])
        self.assertFalse(model["trust_remote_code"])
        self.assertFalse(model["production_authority"])

    def test_disabled_evaluator_has_no_production_effect(self):
        evaluator = HFShadowEvaluator(adapter_factory=FakeAdapter)
        result = evaluator.evaluate_url("https://example.com/test.jpg", ["interior"])
        self.assertEqual(result["status"], "NOT_EXECUTED_DISABLED")
        self.assertEqual(result["production_effect"], "NONE")
        self.assertFalse(result["decision_authority"])
        self.assertFalse(result["business_outcome_claim"])

    def test_circuit_breaker_opens_after_threshold(self):
        breaker = CircuitBreaker(failure_threshold=3, cooldown_seconds=900)
        self.assertTrue(breaker.allow(now=0))
        breaker.failure(now=1)
        breaker.failure(now=2)
        self.assertTrue(breaker.allow(now=3))
        breaker.failure(now=3)
        self.assertFalse(breaker.allow(now=4))
        self.assertTrue(breaker.allow(now=904))


if __name__ == "__main__":
    unittest.main()
