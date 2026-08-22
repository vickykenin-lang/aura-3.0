import importlib.util
import pathlib
import unittest
from unittest import mock


MODULE_PATH = pathlib.Path(__file__).parents[1] / "scripts" / "score_with_deepseek.py"
SPEC = importlib.util.spec_from_file_location("score_with_deepseek", MODULE_PATH)
gate = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(gate)


class GeminiResponseTests(unittest.TestCase):
    def test_extracts_text_parts(self):
        data = {
            "candidates": [
                {"content": {"parts": [{"text": "{\"visual_ok\":"}, {"text": "true}"}]}}
            ]
        }
        self.assertEqual(gate.gemini_response_text(data), '{"visual_ok":true}')

    def test_reports_missing_parts_without_key_error(self):
        with self.assertRaisesRegex(RuntimeError, "finish_reason=SAFETY"):
            gate.gemini_response_text({"candidates": [{"finishReason": "SAFETY"}]})

    def test_reports_prompt_block(self):
        with self.assertRaisesRegex(RuntimeError, "block_reason=PROHIBITED_CONTENT"):
            gate.gemini_response_text(
                {"promptFeedback": {"blockReason": "PROHIBITED_CONTENT"}}
            )

    @mock.patch.object(gate, "download_image", return_value=("image/jpeg", b"image"))
    @mock.patch.object(gate, "post_json")
    def test_vision_retries_same_model_after_unusable_response(self, post_json, _download):
        post_json.side_effect = [
            {"candidates": [{"finishReason": "OTHER"}]},
            {
                "candidates": [
                    {
                        "content": {
                            "parts": [
                                {
                                    "text": (
                                        '{"visual_ok":true,"room_type":"living",'
                                        '"quality":8,"reasons":[]}'
                                    )
                                }
                            ]
                        }
                    }
                ]
            },
        ]
        with mock.patch.object(gate, "GEMINI_MODELS", ("model-a", "model-b")):
            gate.ACTIVE_GEMINI_MODEL = ""
            result = gate.gemini_vision("key", "https://example.com/image.jpg")

        self.assertEqual(result["model"], "model-a")
        self.assertTrue(result["visual_ok"])
        self.assertEqual(post_json.call_count, 2)

    @mock.patch.object(gate.time, "sleep")
    @mock.patch.object(gate, "download_image", return_value=("image/jpeg", b"image"))
    @mock.patch.object(gate, "post_json")
    def test_vision_falls_back_after_semantic_retries(self, post_json, _download, _sleep):
        malformed = {"candidates": [{"content": {"parts": [{"text": "not json"}]}}]}
        valid = {
            "candidates": [
                {
                    "content": {
                        "parts": [
                            {
                                "text": (
                                    '{"visual_ok":true,"room_type":"kitchen",'
                                    '"quality":9,"reasons":[]}'
                                )
                            }
                        ]
                    }
                }
            ]
        }
        post_json.side_effect = [malformed, malformed, malformed, malformed, malformed, valid]
        with mock.patch.object(gate, "GEMINI_MODELS", ("model-a", "model-b")):
            gate.ACTIVE_GEMINI_MODEL = ""
            result = gate.gemini_vision("key", "https://example.com/image.jpg")

        self.assertEqual(result["model"], "model-b")
        self.assertEqual(post_json.call_count, 6)


class DeepSeekPreflightTests(unittest.TestCase):
    @mock.patch.object(gate, "post_json")
    def test_accepts_configured_model(self, post_json):
        post_json.return_value = {
            "data": [{"id": gate.DEEPSEEK_MODEL, "object": "model"}]
        }
        gate.deepseek_preflight("key")

    @mock.patch.object(gate, "post_json")
    def test_rejects_unavailable_model(self, post_json):
        post_json.return_value = {"data": [{"id": "another-model"}]}
        with self.assertRaisesRegex(RuntimeError, "is unavailable"):
            gate.deepseek_preflight("key")


class ModelFallbackTests(unittest.TestCase):
    def test_uses_current_flash_lite_fallback(self):
        self.assertIn("gemini-3.5-flash-lite", gate.GEMINI_MODELS)
        self.assertNotIn("gemini-2.5-flash-lite", gate.GEMINI_MODELS)


if __name__ == "__main__":
    unittest.main()
