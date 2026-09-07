from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

from botocore.exceptions import ClientError, EndpointConnectionError, NoCredentialsError

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import ai_provider


def converse_response(text: str) -> dict:
    return {"output": {"message": {"content": [{"text": text}]}}, "stopReason": "end_turn"}


def client_error(code: str, message: str = "boom") -> ClientError:
    return ClientError({"Error": {"Code": code, "Message": message}}, "Converse")


class GenerateContentTests(unittest.TestCase):
    def setUp(self):
        patcher = patch.dict(
            "os.environ",
            {"PRIMARY_PROVIDER": "aws_bedrock_nova", "AI_FALLBACK_PROVIDER": "none"},
            clear=False,
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        self.selected = [
            {"photo_tag": "living-room", "angle": "budget"},
            {"photo_tag": "kitchen", "angle": "timeline"},
        ]

    @patch("ai_provider._generator_module")
    @patch("ai_provider.boto3")
    def test_happy_path_returns_exact_slot_count(self, mock_boto3, mock_generator_module):
        mock_generator_module.return_value.SYSTEM_PROMPT = "SYSTEM"
        client = MagicMock()
        client.converse.return_value = converse_response(
            '[{"slot":1,"hook_en":"a","caption_hi":"b","hashtags":"#x"},'
            '{"slot":2,"hook_en":"c","caption_hi":"d","hashtags":"#y"}]'
        )
        mock_boto3.client.return_value = client

        generated, used_model = ai_provider.generate_content(self.selected)

        self.assertEqual(len(generated), 2)
        self.assertEqual(generated[0]["slot"], 1)
        self.assertEqual(used_model, ai_provider.DEFAULT_AWS_MODEL_ID)

    @patch("ai_provider._generator_module")
    @patch("ai_provider.boto3")
    def test_strips_markdown_fences(self, mock_boto3, mock_generator_module):
        mock_generator_module.return_value.SYSTEM_PROMPT = "SYSTEM"
        client = MagicMock()
        client.converse.return_value = converse_response(
            '```json\n[{"slot":1,"hook_en":"a","caption_hi":"b","hashtags":"#x"},'
            '{"slot":2,"hook_en":"c","caption_hi":"d","hashtags":"#y"}]\n```'
        )
        mock_boto3.client.return_value = client

        generated, _ = ai_provider.generate_content(self.selected)
        self.assertEqual(len(generated), 2)

    @patch("ai_provider._generator_module")
    @patch("ai_provider.boto3")
    def test_wrong_slot_count_raises(self, mock_boto3, mock_generator_module):
        mock_generator_module.return_value.SYSTEM_PROMPT = "SYSTEM"
        client = MagicMock()
        client.converse.return_value = converse_response(
            '[{"slot":1,"hook_en":"a","caption_hi":"b","hashtags":"#x"}]'
        )
        mock_boto3.client.return_value = client

        with self.assertRaises(ValueError):
            ai_provider.generate_content(self.selected)

    @patch("ai_provider.boto3")
    def test_throttling_is_transient(self, mock_boto3):
        client = MagicMock()
        client.converse.side_effect = client_error("ThrottlingException")
        mock_boto3.client.return_value = client

        with self.assertRaises(ai_provider.ProviderTransientError):
            ai_provider.generate_content(self.selected)

    @patch("ai_provider.boto3")
    def test_access_denied_is_hard(self, mock_boto3):
        client = MagicMock()
        client.converse.side_effect = client_error("AccessDeniedException", "not authorized to invoke model")
        mock_boto3.client.return_value = client

        with self.assertRaises(ai_provider.ProviderHardError):
            ai_provider.generate_content(self.selected)

    @patch("ai_provider.boto3")
    def test_missing_credentials_is_hard(self, mock_boto3):
        client = MagicMock()
        client.converse.side_effect = NoCredentialsError()
        mock_boto3.client.return_value = client

        with self.assertRaises(ai_provider.ProviderHardError):
            ai_provider.generate_content(self.selected)

    @patch("ai_provider.boto3")
    def test_network_error_is_transient(self, mock_boto3):
        client = MagicMock()
        client.converse.side_effect = EndpointConnectionError(endpoint_url="https://bedrock")
        mock_boto3.client.return_value = client

        with self.assertRaises(ai_provider.ProviderTransientError):
            ai_provider.generate_content(self.selected)

    @patch.dict("os.environ", {"AI_FALLBACK_PROVIDER": "gemini", "GEMINI_API_KEY": "gk"})
    @patch("ai_provider._generator_module")
    @patch("ai_provider.boto3")
    def test_hard_error_falls_back_to_gemini_when_enabled(self, mock_boto3, mock_generator_module):
        client = MagicMock()
        client.converse.side_effect = client_error("AccessDeniedException")
        mock_boto3.client.return_value = client
        mock_generator_module.return_value.gemini_generate.return_value = ([{"slot": 1}], "gemini-3.5-flash")

        generated, used_model = ai_provider.generate_content(self.selected[:1])

        self.assertEqual(generated, [{"slot": 1}])
        self.assertEqual(used_model, "gemini-fallback:gemini-3.5-flash")

    @patch("ai_provider.boto3")
    def test_hard_error_without_fallback_enabled_raises(self, mock_boto3):
        client = MagicMock()
        client.converse.side_effect = client_error("AccessDeniedException")
        mock_boto3.client.return_value = client

        with self.assertRaises(ai_provider.ProviderHardError):
            ai_provider.generate_content(self.selected)


class AnalyzeImageTests(unittest.TestCase):
    def setUp(self):
        patcher = patch.dict(
            "os.environ",
            {"PRIMARY_PROVIDER": "aws_bedrock_nova", "AI_FALLBACK_PROVIDER": "none"},
            clear=False,
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    @patch("ai_provider._score_module")
    @patch("ai_provider.boto3")
    def test_vision_contract_matches_gemini_shape(self, mock_boto3, mock_score_module):
        mock_score_module.return_value.download_image.return_value = ("image/jpeg", b"bytes")
        mock_score_module.return_value.VISION_PROMPT = "VISION"
        client = MagicMock()
        client.converse.return_value = converse_response(
            '{"visual_ok":true,"room_type":"living","quality":8,"reasons":["clean"]}'
        )
        mock_boto3.client.return_value = client

        result = ai_provider.analyze_image("https://example.com/img.jpg")

        self.assertEqual(
            set(result.keys()), {"visual_ok", "room_type", "quality", "reasons", "model"}
        )
        self.assertTrue(result["visual_ok"])
        self.assertEqual(result["room_type"], "living")
        self.assertEqual(result["quality"], 8)

    @patch("ai_provider._score_module")
    @patch("ai_provider.boto3")
    def test_low_quality_forces_visual_not_ok(self, mock_boto3, mock_score_module):
        mock_score_module.return_value.download_image.return_value = ("image/jpeg", b"bytes")
        mock_score_module.return_value.VISION_PROMPT = "VISION"
        client = MagicMock()
        client.converse.return_value = converse_response(
            '{"visual_ok":true,"room_type":"living","quality":3,"reasons":["blurry"]}'
        )
        mock_boto3.client.return_value = client

        result = ai_provider.analyze_image("https://example.com/img.jpg")
        self.assertFalse(result["visual_ok"])

    @patch("ai_provider._score_module")
    def test_unsupported_mime_type_raises(self, mock_score_module):
        mock_score_module.return_value.download_image.return_value = ("image/gif", b"bytes")
        with self.assertRaises(ValueError):
            ai_provider.analyze_image("https://example.com/img.gif")


class EvaluateBusinessTests(unittest.TestCase):
    def setUp(self):
        patcher = patch.dict("os.environ", {"PRIMARY_PROVIDER": "aws_bedrock_nova"}, clear=False)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.post = {
            "id": "20260907-01",
            "photo_tag": "living-room",
            "disclosure": "Inspiration reference",
            "ig": {"hook_en": "hook", "caption_hi": "caption", "hashtags": "#x"},
        }
        self.vision = {"room_type": "living", "quality": 8}

    @patch("ai_provider.boto3")
    def test_happy_path_pass(self, mock_boto3):
        client = MagicMock()
        client.converse.return_value = converse_response(
            '{"score":8,"pass":true,"reasons":["good"],"caption_match":true,'
            '"cta_ok":true,"conversion_ok":true}'
        )
        mock_boto3.client.return_value = client

        result = ai_provider.evaluate_business(self.post, self.vision)

        self.assertEqual(
            set(result.keys()),
            {"score", "pass", "reasons", "caption_match", "cta_ok", "conversion_ok", "model"},
        )
        self.assertTrue(result["pass"])
        self.assertEqual(result["score"], 8)

    @patch("ai_provider.boto3")
    def test_low_score_fails_even_if_pass_flag_true(self, mock_boto3):
        client = MagicMock()
        client.converse.return_value = converse_response(
            '{"score":5,"pass":true,"reasons":[],"caption_match":true,'
            '"cta_ok":true,"conversion_ok":true}'
        )
        mock_boto3.client.return_value = client

        result = ai_provider.evaluate_business(self.post, self.vision)
        self.assertFalse(result["pass"])

    @patch("ai_provider.boto3")
    def test_missing_cta_fails_regardless_of_score(self, mock_boto3):
        client = MagicMock()
        client.converse.return_value = converse_response(
            '{"score":9,"pass":true,"reasons":[],"caption_match":true,'
            '"cta_ok":false,"conversion_ok":true}'
        )
        mock_boto3.client.return_value = client

        result = ai_provider.evaluate_business(self.post, self.vision)
        self.assertFalse(result["pass"])

    @patch("ai_provider.boto3")
    def test_access_denied_is_hard_error(self, mock_boto3):
        client = MagicMock()
        client.converse.side_effect = client_error("AccessDeniedException")
        mock_boto3.client.return_value = client

        with self.assertRaises(ai_provider.ProviderHardError):
            ai_provider.evaluate_business(self.post, self.vision)

    @patch.dict("os.environ", {"PRIMARY_PROVIDER": "gemini"})
    def test_business_gate_unimplemented_for_gemini(self):
        with self.assertRaises(ai_provider.ProviderHardError):
            ai_provider.evaluate_business(self.post, self.vision)


class UnknownProviderTests(unittest.TestCase):
    @patch.dict("os.environ", {"PRIMARY_PROVIDER": "not_a_real_provider"})
    def test_unknown_primary_provider_is_hard_error(self):
        with self.assertRaises(ai_provider.ProviderHardError):
            ai_provider.generate_content([{"photo_tag": "x", "angle": "y"}])


if __name__ == "__main__":
    unittest.main()
