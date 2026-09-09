import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from queue_retry_controller import decide
from run_approval_queue import is_gemini_project_billing_denied_text


class QueueRetryControllerTests(unittest.TestCase):
    def test_target_reached_stops_chain(self):
        result = decide(
            {"status": "QUEUE_REFILLED_UNIQUE_IMAGES", "target": 20, "approval_ready": 20},
            attempt=0,
            max_chain_attempts=3,
            maintain_exit_code=0,
        )
        self.assertFalse(result["should_retry"])
        self.assertEqual(result["reason"], "TARGET_REACHED")

    def test_transient_errors_do_not_self_retry(self):
        result = decide(
            {
                "status": "QUEUE_WAITING_FOR_UNIQUE_IMAGES",
                "target": 20,
                "approval_ready": 8,
                "generated_this_run": 30,
                "unique_pool_available": 0,
                "technical_errors": [{"type": "ValueError"}] * 7,
            },
            attempt=0,
            max_chain_attempts=3,
            maintain_exit_code=0,
        )
        self.assertFalse(result["should_retry"])
        self.assertEqual(result["cooldown_seconds"], 0)
        self.assertEqual(result["next_chain_attempt"], 0)
        self.assertEqual(result["reason"], "EVENT_DRIVEN_WAIT_FOR_TRIGGER")

    def test_empty_pool_waits_for_real_event_not_retry_loop(self):
        result = decide(
            {
                "status": "QUEUE_WAITING_FOR_UNIQUE_IMAGES",
                "target": 20,
                "approval_ready": 8,
                "generated_this_run": 0,
                "unique_pool_available": 0,
                "technical_errors": [],
            },
            attempt=1,
            max_chain_attempts=3,
            maintain_exit_code=0,
        )
        self.assertFalse(result["should_retry"])
        self.assertEqual(result["cooldown_seconds"], 0)
        self.assertEqual(result["next_chain_attempt"], 1)
        self.assertEqual(result["reason"], "EVENT_DRIVEN_WAIT_FOR_TRIGGER")

    def test_provider_preflight_block_stops_chain(self):
        result = decide(
            {
                "status": "REFILL_BLOCKED_PROVIDER_PREFLIGHT",
                "target": 20,
                "approval_ready": 8,
            },
            attempt=0,
            max_chain_attempts=3,
            maintain_exit_code=1,
        )
        self.assertFalse(result["should_retry"])
        self.assertEqual(result["reason"], "HARD_BLOCK_STATUS")

    def test_gemini_project_billing_block_stops_chain(self):
        result = decide(
            {
                "status": "REFILL_BLOCKED_GEMINI_PROJECT_BILLING",
                "target": 20,
                "approval_ready": 13,
                "unique_pool_available": 60,
                "technical_errors": [{"type": "GeminiProjectBillingDenied"}],
            },
            attempt=1,
            max_chain_attempts=3,
            maintain_exit_code=1,
        )
        self.assertFalse(result["should_retry"])
        self.assertEqual(result["reason"], "GEMINI_PROJECT_BILLING_HARD_BLOCK")
        self.assertEqual(result["cooldown_seconds"], 0)

    def test_provider_error_classifier_recognizes_dunning_denial(self):
        self.assertTrue(
            is_gemini_project_billing_denied_text(
                "Gemini HTTP 403: status PERMISSION_DENIED; dunning decision is deny"
            )
        )
        self.assertFalse(is_gemini_project_billing_denied_text("Gemini HTTP 429: rate limited"))

    def test_maintainer_failure_waits_for_event_or_manual_repair(self):
        result = decide(
            {
                "status": "QUEUE_WAITING_FOR_UNIQUE_IMAGES",
                "target": 20,
                "approval_ready": 8,
            },
            attempt=0,
            max_chain_attempts=3,
            maintain_exit_code=1,
        )
        self.assertFalse(result["should_retry"])
        self.assertEqual(result["reason"], "MAINTAINER_FAILURE_WAIT_FOR_EVENT_OR_MANUAL_REPAIR")


if __name__ == "__main__":
    unittest.main()
