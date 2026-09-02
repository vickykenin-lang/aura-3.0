from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import run_approval_queue as runner


class QueueTimeoutResilienceTests(unittest.TestCase):
    def setUp(self):
        self.old_sleep = runner.time.sleep
        runner.time.sleep = lambda _seconds: None

    def tearDown(self):
        runner.time.sleep = self.old_sleep

    def test_generation_recovers_after_one_raw_timeout(self):
        calls = {"n": 0}
        original = runner._ORIGINAL_GENERATOR_REQUEST_JSON
        def fake(_request, timeout=0):
            calls["n"] += 1
            if calls["n"] == 1:
                raise TimeoutError("timed out")
            return {"ok": True, "timeout": timeout}
        runner._ORIGINAL_GENERATOR_REQUEST_JSON = fake
        try:
            result = runner.resilient_generator_request_json(object())
        finally:
            runner._ORIGINAL_GENERATOR_REQUEST_JSON = original
        self.assertTrue(result["ok"])
        self.assertEqual(calls["n"], 2)
        self.assertLessEqual(result["timeout"], runner.TIMEOUT_SECONDS)

    def test_generation_exhaustion_becomes_network_error(self):
        original = runner._ORIGINAL_GENERATOR_REQUEST_JSON
        runner._ORIGINAL_GENERATOR_REQUEST_JSON = lambda _request, timeout=0: (_ for _ in ()).throw(TimeoutError("timed out"))
        try:
            with self.assertRaisesRegex(RuntimeError, "Gemini network error: timeout"):
                runner.resilient_generator_request_json(object())
        finally:
            runner._ORIGINAL_GENERATOR_REQUEST_JSON = original

    def test_qualification_recovers_after_one_raw_timeout(self):
        calls = {"n": 0}
        original = runner._ORIGINAL_GATE_POST_JSON
        def fake(_request, provider, timeout=0):
            calls["n"] += 1
            if calls["n"] == 1:
                raise TimeoutError("timed out")
            return {"provider": provider, "timeout": timeout}
        runner._ORIGINAL_GATE_POST_JSON = fake
        try:
            result = runner.resilient_gate_post_json(object(), "Gemini")
        finally:
            runner._ORIGINAL_GATE_POST_JSON = original
        self.assertEqual(result["provider"], "Gemini")
        self.assertEqual(calls["n"], 2)

    def test_qualification_exhaustion_is_provider_network_error(self):
        original = runner._ORIGINAL_GATE_POST_JSON
        runner._ORIGINAL_GATE_POST_JSON = lambda _request, provider, timeout=0: (_ for _ in ()).throw(TimeoutError("timed out"))
        try:
            with self.assertRaisesRegex(RuntimeError, "DeepSeek network error: timeout"):
                runner.resilient_gate_post_json(object(), "DeepSeek")
        finally:
            runner._ORIGINAL_GATE_POST_JSON = original


if __name__ == "__main__":
    unittest.main()
