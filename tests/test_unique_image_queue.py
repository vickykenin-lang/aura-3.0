from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import generate_candidates as generator
import maintain_approval_queue as queue


class UniqueImageQueueTests(unittest.TestCase):
    def test_image_key_ignores_query_variants(self):
        a = "https://images.unsplash.com/photo-123?w=1200&q=85"
        b = "https://images.unsplash.com/photo-123?w=800&q=60"
        self.assertEqual(queue.image_key(a), queue.image_key(b))

    def test_ready_queue_keeps_one_pending_card_per_image(self):
        calendar = {"days": [
            {"id": "p1", "image": "https://img.test/a.jpg?x=1"},
            {"id": "p2", "image": "https://img.test/a.jpg?x=2"},
            {"id": "p3", "image": "https://img.test/b.jpg"},
        ]}
        gates = {"posts": {pid: {"pass": True, "visual_ok": True, "score": 8} for pid in ("p1", "p2", "p3")}}
        self.assertEqual(queue.approval_ready_ids(calendar, gates, {}, {}), ["p1", "p3"])

    def test_decided_image_cannot_reenter_pending_queue(self):
        calendar = {"days": [
            {"id": "approved", "image": "https://img.test/a.jpg"},
            {"id": "pending-copy", "image": "https://img.test/a.jpg?w=1200"},
            {"id": "pending-unique", "image": "https://img.test/b.jpg"},
        ]}
        gates = {"posts": {
            "approved": {"pass": True, "visual_ok": True, "score": 8},
            "pending-copy": {"pass": True, "visual_ok": True, "score": 8},
            "pending-unique": {"pass": True, "visual_ok": True, "score": 8},
        }}
        approvals = {"approved": "approved_manual"}
        removed = queue.reconcile_duplicate_pending_images(calendar, gates, approvals, {})
        self.assertEqual(removed, ["pending-copy"])
        self.assertEqual([p["id"] for p in calendar["days"]], ["approved", "pending-unique"])
        self.assertNotIn("pending-copy", gates["posts"])

    def test_gemini_generation_accepts_variable_unique_batch(self):
        selected = [
            {"photo_tag": "living", "angle": "a"},
            {"photo_tag": "kitchen", "angle": "b"},
            {"photo_tag": "bedroom", "angle": "c"},
        ]
        old_request = generator.request_json
        old_models = generator.GEMINI_MODELS
        captured = {}

        def fake_request(request, timeout=120):
            payload = json.loads(request.data.decode("utf-8"))
            captured["schema"] = payload["generationConfig"]["responseSchema"]
            items = [
                {"slot": i, "hook_en": f"Useful interior idea number {i}", "caption_hi": "Free consultation ke liye designinfra.in visit karein for a practical interior planning process.", "hashtags": "#DesignInfra #DelhiNCRInteriors #TurnkeyInteriors"}
                for i in range(1, 4)
            ]
            return {"candidates": [{"content": {"parts": [{"text": json.dumps(items)}]}}]}

        generator.request_json = fake_request
        generator.GEMINI_MODELS = ("test-model",)
        try:
            generated, model = generator.gemini_generate("secret", selected)
        finally:
            generator.request_json = old_request
            generator.GEMINI_MODELS = old_models
        self.assertEqual(model, "test-model")
        self.assertEqual(len(generated), 3)
        self.assertEqual(captured["schema"]["minItems"], 3)
        self.assertEqual(captured["schema"]["maxItems"], 3)
        self.assertEqual(captured["schema"]["items"]["properties"]["slot"]["maximum"], 3)


if __name__ == "__main__":
    unittest.main()
