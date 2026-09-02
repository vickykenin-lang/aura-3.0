import copy
import unittest

from runtime.hf_observability import (
    assert_privacy_minimized,
    build_observation,
    summarize,
    verify_source_integrity,
)


class FakeEvaluator:
    def __init__(self, room_label="a kitchen interior", relevance_label="a kitchen interior"):
        self.room_label = room_label
        self.relevance_label = relevance_label
        self.calls = 0

    def evaluate_url(self, image_url, candidate_labels, force_shadow=False):
        self.calls += 1
        label = self.room_label if self.calls % 2 == 1 else self.relevance_label
        return {
            "status": "SHADOW_RESULT",
            "decision_authority": False,
            "production_effect": "NONE",
            "latency_ms": 25.0 + self.calls,
            "result": {
                "model_id": "google/siglip-base-patch16-224",
                "revision": "pinned-test-revision",
                "top_label": label,
                "top_score": 0.8,
            },
        }


class UnavailableEvaluator:
    def evaluate_url(self, image_url, candidate_labels, force_shadow=False):
        return {
            "status": "EVALUATOR_UNAVAILABLE",
            "decision_authority": False,
            "production_effect": "NONE",
            "reason": "TimeoutError",
        }


class HFPhase4ObservabilityTests(unittest.TestCase):
    def setUp(self):
        self.post = {
            "id": "case-1",
            "photo_tag": "kitchen",
            "image": "https://images.example.com/kitchen.jpg",
            "ig": {
                "hook_en": "Private marketing copy that must not be stored",
                "caption_hi": "Private caption text that must not be stored",
            },
        }
        self.historical = {
            "visual_ok": True,
            "vision": {"room_type": "kitchen"},
        }

    def test_observation_is_non_authoritative_and_privacy_minimized(self):
        row = build_observation(self.post, self.historical, FakeEvaluator())
        self.assertEqual(row["status"], "OBSERVED")
        self.assertFalse(row["decision_authority"])
        self.assertEqual(row["production_effect"], "NONE")
        self.assertNotIn("image", row)
        self.assertNotIn("image_url", row)
        self.assertNotIn("caption_hi", row)
        assert_privacy_minimized(row)

    def test_observer_does_not_mutate_input_artifacts(self):
        post_before = copy.deepcopy(self.post)
        historical_before = copy.deepcopy(self.historical)
        build_observation(self.post, self.historical, FakeEvaluator())
        self.assertEqual(self.post, post_before)
        self.assertEqual(self.historical, historical_before)

    def test_matching_reference_produces_no_disagreement(self):
        row = build_observation(self.post, self.historical, FakeEvaluator())
        self.assertFalse(row["room_disagreement"])
        self.assertFalse(row["relevance_disagreement"])
        summary = summarize([row])
        self.assertEqual(summary["room_disagreements"], 0)
        self.assertEqual(summary["relevance_disagreements"], 0)
        self.assertEqual(summary["observer_availability_rate"], 1.0)

    def test_disagreement_is_reported_but_has_no_production_effect(self):
        row = build_observation(
            self.post,
            self.historical,
            FakeEvaluator(room_label="a bedroom interior", relevance_label="an outdoor landscape photograph without an interior space"),
        )
        self.assertTrue(row["room_disagreement"])
        self.assertTrue(row["relevance_disagreement"])
        self.assertEqual(row["production_effect"], "NONE")
        summary = summarize([row])
        self.assertEqual(summary["room_disagreements"], 1)
        self.assertEqual(summary["relevance_disagreements"], 1)

    def test_observer_unavailability_is_visible_and_non_blocking(self):
        row = build_observation(self.post, self.historical, UnavailableEvaluator())
        self.assertEqual(row["status"], "OBSERVER_UNAVAILABLE")
        self.assertEqual(row["production_effect"], "NONE")
        self.assertIsNone(row["room_disagreement"])
        self.assertIsNone(row["relevance_disagreement"])

    def test_source_integrity_requires_exact_hash_match(self):
        before = {"calendar": "abc", "gates": "def"}
        self.assertTrue(verify_source_integrity(before, dict(before)))
        self.assertFalse(verify_source_integrity(before, {"calendar": "abc", "gates": "xyz"}))


if __name__ == "__main__":
    unittest.main()
