from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import ai_provider
import run_approval_queue as runner


class AWSResilienceWrapperTests(unittest.TestCase):
    def setUp(self):
        self.old_sleep = runner.time.sleep
        runner.time.sleep = lambda _seconds: None
        self.old_generate = runner._ORIGINAL_GENERATE_CONTENT
        self.old_analyze = runner._ORIGINAL_ANALYZE_IMAGE

    def tearDown(self):
        runner.time.sleep = self.old_sleep
        runner._ORIGINAL_GENERATE_CONTENT = self.old_generate
        runner._ORIGINAL_ANALYZE_IMAGE = self.old_analyze

    def test_transient_error_recovers_on_retry(self):
        calls = {"n": 0}

        def fake(selected):
            calls["n"] += 1
            if calls["n"] == 1:
                raise ai_provider.ProviderTransientError("throttled")
            return [{"slot": 1}], "aws-model"

        runner._ORIGINAL_GENERATE_CONTENT = fake
        result = runner.resilient_generate_content([{"photo_tag": "x", "angle": "y"}])
        self.assertEqual(result, ([{"slot": 1}], "aws-model"))
        self.assertEqual(calls["n"], 2)

    def test_transient_error_exhaustion_raises_runtime_error(self):
        runner._ORIGINAL_GENERATE_CONTENT = lambda selected: (_ for _ in ()).throw(
            ai_provider.ProviderTransientError("still throttled")
        )
        with self.assertRaisesRegex(RuntimeError, "AI provider transient error"):
            runner.resilient_generate_content([{"photo_tag": "x", "angle": "y"}])

    def test_hard_error_is_promoted_to_aws_provider_hard_blocked(self):
        runner._ORIGINAL_GENERATE_CONTENT = lambda selected: (_ for _ in ()).throw(
            ai_provider.ProviderHardError("AWS Bedrock generation AccessDeniedException: not authorized")
        )
        with self.assertRaises(runner.AWSProviderHardBlocked):
            runner.resilient_generate_content([{"photo_tag": "x", "angle": "y"}])

    def test_analyze_image_hard_error_is_promoted(self):
        runner._ORIGINAL_ANALYZE_IMAGE = lambda url: (_ for _ in ()).throw(
            ai_provider.ProviderHardError("AWS Bedrock vision AccessDeniedException: not authorized")
        )
        with self.assertRaises(runner.AWSProviderHardBlocked):
            runner.resilient_analyze_image("https://example.com/img.jpg")


class PromoteAWSProviderBlockStatusTests(unittest.TestCase):
    def setUp(self):
        self.status_path = ROOT / "data" / "approval_queue_status.json"
        self.original_text = self.status_path.read_text(encoding="utf-8")

    def tearDown(self):
        self.status_path.write_text(self.original_text, encoding="utf-8")

    def test_aws_provider_hard_blocked_sets_dedicated_status(self):
        self.status_path.write_text(
            json.dumps(
                {
                    "status": "QUEUE_PARTIAL_TECHNICAL_ERROR",
                    "technical_errors": [{"stage": "generation", "type": "AWSProviderHardBlocked"}],
                }
            ),
            encoding="utf-8",
        )
        runner.promote_provider_block_status(1)
        updated = json.loads(self.status_path.read_text(encoding="utf-8"))
        self.assertEqual(updated["status"], "REFILL_BLOCKED_AWS_PROVIDER")
        self.assertEqual(updated["provider_blocker"], "AWS_PROVIDER_ACCESS_OR_CONFIG_DENIED")

    def test_gemini_billing_denied_still_takes_its_existing_path(self):
        self.status_path.write_text(
            json.dumps(
                {
                    "status": "QUEUE_PARTIAL_TECHNICAL_ERROR",
                    "technical_errors": [{"stage": "generation", "type": "GeminiProjectBillingDenied"}],
                }
            ),
            encoding="utf-8",
        )
        runner.promote_provider_block_status(1)
        updated = json.loads(self.status_path.read_text(encoding="utf-8"))
        self.assertEqual(updated["status"], "REFILL_BLOCKED_GEMINI_PROJECT_BILLING")

    def test_unrelated_error_type_leaves_status_untouched(self):
        self.status_path.write_text(
            json.dumps(
                {
                    "status": "QUEUE_PARTIAL_TECHNICAL_ERROR",
                    "technical_errors": [{"stage": "generation", "type": "ValueError"}],
                }
            ),
            encoding="utf-8",
        )
        runner.promote_provider_block_status(1)
        updated = json.loads(self.status_path.read_text(encoding="utf-8"))
        self.assertEqual(updated["status"], "QUEUE_PARTIAL_TECHNICAL_ERROR")


class QueueRetryControllerAWSBlockTests(unittest.TestCase):
    def test_aws_provider_hard_block_stops_chain(self):
        from queue_retry_controller import decide

        result = decide(
            {
                "status": "REFILL_BLOCKED_AWS_PROVIDER",
                "target": 20,
                "approval_ready": 13,
                "unique_pool_available": 80,
                "technical_errors": [{"type": "AWSProviderHardBlocked"}],
            },
            attempt=0,
            max_chain_attempts=3,
            maintain_exit_code=1,
        )
        self.assertFalse(result["should_retry"])
        self.assertEqual(result["reason"], "AWS_PROVIDER_HARD_BLOCK")


if __name__ == "__main__":
    unittest.main()
