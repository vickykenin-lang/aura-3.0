import importlib.util
import pathlib
import unittest
from unittest import mock


MODULE_PATH = pathlib.Path(__file__).parents[1] / "scripts" / "approve_manual.py"
SPEC = importlib.util.spec_from_file_location("approve_manual", MODULE_PATH)
approve = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(approve)


class ApprovalBatchSafetyTests(unittest.TestCase):
    @mock.patch.object(approve, "load_json")
    def test_refuses_incomplete_batch(self, load_json):
        approve.POST_ID = "post-1"
        load_json.side_effect = [
            {"kill_switch": False},
            {"post-1": "pending"},
            {"days": [{"id": "post-1"}]},
            {
                "batch_complete": False,
                "posts": {"post-1": {"pass": True, "score": 9, "visual_ok": True}},
            },
        ]

        self.assertEqual(approve.main(), 1)


if __name__ == "__main__":
    unittest.main()
