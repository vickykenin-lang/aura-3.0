import importlib.util
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "telegram_management_reply.py"
SPEC = importlib.util.spec_from_file_location("telegram_management_reply", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class TelegramManagementReplyTests(unittest.TestCase):
    def test_build_reply_uses_verified_aura3_fields(self):
        text = MODULE.build_reply(
            {
                "task_id": "victor-aura3-test-1",
                "execution_status": "COMPLETED",
                "strict_supervision": {
                    "status": "LIVE_CERTIFIED",
                    "objective_alignment": "ALIGNED",
                    "solution": "Continue governed execution",
                    "next_action": "Run next cycle",
                    "evidence": ["integration/results/latest.json"],
                },
            }
        )
        self.assertIn("AURA3 management-group revert", text)
        self.assertIn("Status: LIVE_CERTIFIED", text)
        self.assertIn("Task ID: victor-aura3-test-1", text)


if __name__ == "__main__":
    unittest.main()
