import unittest

from scripts.queue_retry_controller import decide


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

    def test_transient_errors_get_cooldown_and_retry(self):
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
        self.assertTrue(result["should_retry"])
        self.assertEqual(result["cooldown_seconds"], 240)
        self.assertEqual(result["next_chain_attempt"], 1)
        self.assertEqual(result["reason"], "TRANSIENT_QUALIFICATION_COOLDOWN")

    def test_empty_pool_without_errors_retries_after_visual_refresh_cooldown(self):
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
        self.assertTrue(result["should_retry"])
        self.assertEqual(result["cooldown_seconds"], 90)
        self.assertEqual(result["next_chain_attempt"], 2)
        self.assertEqual(result["reason"], "REFRESH_VISUAL_POOL_AND_RETRY")

    def test_chain_limit_stops_infinite_loop(self):
        result = decide(
            {
                "status": "QUEUE_WAITING_FOR_UNIQUE_IMAGES",
                "target": 20,
                "approval_ready": 8,
                "generated_this_run": 0,
                "unique_pool_available": 0,
            },
            attempt=3,
            max_chain_attempts=3,
            maintain_exit_code=0,
        )
        self.assertFalse(result["should_retry"])
        self.assertEqual(result["reason"], "CHAIN_CIRCUIT_BREAKER")

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

    def test_non_transient_exit_code_stops_chain(self):
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
        self.assertEqual(result["reason"], "NON_TRANSIENT_MAINTAINER_FAILURE")


if __name__ == "__main__":
    unittest.main()
