from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import maintain_approval_queue as queue


class ApprovalQueueContractTests(unittest.TestCase):
    def setUp(self):
        self.gates = {
            "posts": {
                "p1": {"pass": True, "visual_ok": True, "score": 8},
                "p2": {"pass": True, "visual_ok": True, "score": 9},
                "p3": {"pass": True, "visual_ok": True, "score": 7},
                "p4": {"pass": False, "visual_ok": True, "score": 6},
                "p5": {"pass": True, "visual_ok": True, "score": 8},
            }
        }
        self.calendar = {"days": [{"id": f"p{i}"} for i in range(1, 6)]}

    def test_only_pending_dual_gate_pass_counts(self):
        approvals = {"p2": "approved_manual", "p3": "rejected"}
        published = {}
        self.assertEqual(queue.approval_ready_ids(self.calendar, self.gates, approvals, published), ["p1", "p5"])

    def test_published_never_counts(self):
        approvals = {}
        published = {"p1": {"instagram": {"id": "media-1"}}}
        ready = queue.approval_ready_ids(self.calendar, self.gates, approvals, published)
        self.assertNotIn("p1", ready)

    def test_target_is_hard_capped_at_twenty(self):
        self.assertEqual(queue.queue_target(), 20)

    def test_disclosure_policy_is_exact(self):
        rules = json.loads((ROOT / "data" / "queue_rules.json").read_text(encoding="utf-8"))
        self.assertEqual(rules["disclosure_standard"], "Inspiration reference")
        self.assertEqual(rules["max_pending_on_dashboard"], 20)


if __name__ == "__main__":
    unittest.main()
