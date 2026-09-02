import copy
import json
import unittest
from pathlib import Path
from unittest.mock import patch

from runtime.hf_shadow import CircuitBreaker, HFShadowEvaluator

ROOT = Path(__file__).resolve().parents[1]


def load(path):
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def test_config(retries=1, threshold=3, cooldown=10):
    config = copy.deepcopy(load("hf/config.json"))
    config["execution"]["transient_retries"] = retries
    config["execution"]["retry_delay_seconds"] = 0
    config["execution"]["circuit_breaker"]["failure_threshold"] = threshold
    config["execution"]["circuit_breaker"]["cooldown_seconds"] = cooldown
    return config


class SuccessAdapter:
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


class ImportFailureAdapter:
    def __init__(self, model, config):
        pass

    def evaluate(self, image_bytes, candidate_labels):
        raise ImportError("simulated local runtime dependency failure")


class CorruptInputAdapter:
    def __init__(self, model, config):
        pass

    def evaluate(self, image_bytes, candidate_labels):
        raise ValueError("simulated corrupt image payload")


class HFPhase3ReliabilityTests(unittest.TestCase):
    def assert_non_authoritative(self, result):
        self.assertEqual(result["production_effect"], "NONE")
        self.assertFalse(result["decision_authority"])
        self.assertFalse(result["business_outcome_claim"])
        self.assertEqual(result["mode"], "SHADOW_ONLY")

    def test_transient_timeout_retries_once_then_recovers(self):
        evaluator = HFShadowEvaluator(config=test_config(retries=1), adapter_factory=SuccessAdapter)
        with patch("runtime.hf_shadow.download_image", side_effect=[TimeoutError("simulated timeout"), b"image"]), patch(
            "runtime.hf_shadow.time.sleep"
        ) as sleeper:
            result = evaluator.evaluate_url("https://example.com/test.jpg", ["interior"], force_shadow=True)
        self.assertEqual(result["status"], "SHADOW_RESULT")
        self.assertEqual(result["attempt"], 2)
        self.assertEqual(evaluator.breaker.consecutive_failures, 0)
        sleeper.assert_called_once()
        self.assert_non_authoritative(result)

    def test_timeout_exhaustion_counts_one_failed_evaluation(self):
        evaluator = HFShadowEvaluator(config=test_config(retries=1), adapter_factory=SuccessAdapter)
        with patch("runtime.hf_shadow.download_image", side_effect=TimeoutError("simulated timeout")), patch(
            "runtime.hf_shadow.time.sleep"
        ):
            result = evaluator.evaluate_url("https://example.com/test.jpg", ["interior"], force_shadow=True)
        self.assertEqual(result["status"], "EVALUATOR_UNAVAILABLE")
        self.assertTrue(result["retryable"])
        self.assertEqual(result["attempts_used"], 2)
        self.assertEqual(evaluator.breaker.consecutive_failures, 1)
        self.assert_non_authoritative(result)

    def test_nonretryable_runtime_failure_does_not_waste_retry(self):
        evaluator = HFShadowEvaluator(config=test_config(retries=1), adapter_factory=ImportFailureAdapter)
        with patch("runtime.hf_shadow.download_image", return_value=b"image"), patch(
            "runtime.hf_shadow.time.sleep"
        ) as sleeper:
            result = evaluator.evaluate_url("https://example.com/test.jpg", ["interior"], force_shadow=True)
        self.assertEqual(result["status"], "EVALUATOR_UNAVAILABLE")
        self.assertFalse(result["retryable"])
        self.assertEqual(result["attempts_used"], 1)
        self.assertEqual(evaluator.breaker.consecutive_failures, 1)
        sleeper.assert_not_called()
        self.assert_non_authoritative(result)

    def test_policy_rejection_never_advances_circuit_breaker(self):
        evaluator = HFShadowEvaluator(config=test_config(retries=1), adapter_factory=SuccessAdapter)
        for _ in range(5):
            result = evaluator.evaluate_url("http://example.com/not-allowed.jpg", ["interior"], force_shadow=True)
            self.assertEqual(result["status"], "EVALUATION_REJECTED")
            self.assert_non_authoritative(result)
        self.assertEqual(evaluator.breaker.consecutive_failures, 0)
        self.assertTrue(evaluator.breaker.allow())

    def test_corrupt_input_rejection_does_not_look_like_provider_outage(self):
        evaluator = HFShadowEvaluator(config=test_config(retries=1), adapter_factory=CorruptInputAdapter)
        with patch("runtime.hf_shadow.download_image", return_value=b"bad-image"):
            result = evaluator.evaluate_url("https://example.com/test.jpg", ["interior"], force_shadow=True)
        self.assertEqual(result["status"], "EVALUATION_REJECTED")
        self.assertEqual(evaluator.breaker.consecutive_failures, 0)
        self.assert_non_authoritative(result)

    def test_circuit_opens_after_three_failed_evaluations_and_short_circuits_next_call(self):
        evaluator = HFShadowEvaluator(config=test_config(retries=0, threshold=3), adapter_factory=SuccessAdapter)
        with patch("runtime.hf_shadow.download_image", side_effect=TimeoutError("simulated timeout")) as downloader:
            first = evaluator.evaluate_url("https://example.com/a.jpg", ["interior"], force_shadow=True)
            second = evaluator.evaluate_url("https://example.com/b.jpg", ["interior"], force_shadow=True)
            third = evaluator.evaluate_url("https://example.com/c.jpg", ["interior"], force_shadow=True)
            fourth = evaluator.evaluate_url("https://example.com/d.jpg", ["interior"], force_shadow=True)
        for result in (first, second, third, fourth):
            self.assert_non_authoritative(result)
        self.assertEqual(first["status"], "EVALUATOR_UNAVAILABLE")
        self.assertEqual(second["status"], "EVALUATOR_UNAVAILABLE")
        self.assertEqual(third["status"], "EVALUATOR_UNAVAILABLE")
        self.assertEqual(fourth["status"], "EVALUATOR_UNAVAILABLE")
        self.assertEqual(fourth["reason"], "CIRCUIT_OPEN")
        self.assertEqual(downloader.call_count, 3)

    def test_circuit_breaker_recovers_after_cooldown(self):
        breaker = CircuitBreaker(failure_threshold=3, cooldown_seconds=10)
        breaker.failure(now=1)
        breaker.failure(now=2)
        breaker.failure(now=3)
        self.assertFalse(breaker.allow(now=9))
        self.assertTrue(breaker.allow(now=13))
        self.assertEqual(breaker.consecutive_failures, 0)
        self.assertIsNone(breaker.opened_at)

    def test_success_resets_failure_streak(self):
        evaluator = HFShadowEvaluator(config=test_config(retries=0), adapter_factory=SuccessAdapter)
        with patch("runtime.hf_shadow.download_image", side_effect=TimeoutError("simulated timeout")):
            failed = evaluator.evaluate_url("https://example.com/a.jpg", ["interior"], force_shadow=True)
        self.assertEqual(failed["status"], "EVALUATOR_UNAVAILABLE")
        self.assertEqual(evaluator.breaker.consecutive_failures, 1)
        with patch("runtime.hf_shadow.download_image", return_value=b"image"):
            recovered = evaluator.evaluate_url("https://example.com/b.jpg", ["interior"], force_shadow=True)
        self.assertEqual(recovered["status"], "SHADOW_RESULT")
        self.assertEqual(evaluator.breaker.consecutive_failures, 0)
        self.assert_non_authoritative(recovered)

    def test_hf_remains_optional_for_business_execution(self):
        config = load("hf/config.json")
        self.assertFalse(config["enabled"])
        self.assertFalse(config["production_authority"])
        self.assertFalse(config["required_for_business_execution"])

        production_files = [
            "runtime/guarded_execution.py",
            "runtime/heartbeat.py",
            "scripts/publish_instagram.py",
        ]
        for relative in production_files:
            text = (ROOT / relative).read_text(encoding="utf-8")
            self.assertNotIn("runtime.hf_shadow", text)
            self.assertNotIn("HFShadowEvaluator", text)


if __name__ == "__main__":
    unittest.main()
