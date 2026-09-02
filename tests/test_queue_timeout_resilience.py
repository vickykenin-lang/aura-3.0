from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import run_approval_queue as runner


class QueueTimeoutResilienceTests(unittest.TestCase):
    def tearDown(self):
        runner._ORIGINAL_REQUEST_JSON = runner.generator.request_json

    def test_recovers_after_one_raw_timeout(self):
        calls = {"n": 0}
        def fake(_request, timeout=0):
            calls["n"] += 1
            if calls["n"] == 1:
                raise TimeoutError("timed out")
            return {"ok": True, "timeout": timeout}
        runner._ORIGINAL_REQUEST_JSON = fake
        old_sleep = runner.time.sleep
        runner.time.sleep = lambda _seconds: None
        try:
            result = runner.resilient_request_json(object())
        finally:
            runner.time.sleep = old_sleep
        self.assertTrue(result["ok"])
        self.assertEqual(calls["n"], 2)
        self.assertLessEqual(result["timeout"], runner.TIMEOUT_SECONDS)

    def test_exhausted_raw_timeouts_become_generator_network_error(self):
        def fake(_request, timeout=0):
            raise TimeoutError("timed out")
        runner._ORIGINAL_REQUEST_JSON = fake
        old_sleep = runner.time.sleep
        runner.time.sleep = lambda _seconds: None
        try:
            with self.assertRaisesRegex(RuntimeError, "Gemini network error: timeout"):
                runner.resilient_request_json(object())
        finally:
            runner.time.sleep = old_sleep


if __name__ == "__main__":
    unittest.main()
