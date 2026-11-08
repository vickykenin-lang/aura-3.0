import sys
import base64
import types
import json
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import check_first_post_readiness as probe


class FirstPostReadinessTests(unittest.TestCase):
    def test_reused_vision_must_match_exact_bytes_and_be_fresh(self):
        now = datetime.now(timezone.utc)
        candidate = {"image_sha256": "a" * 64,
                     "reuse_vision_evidence": "campaigns/r11/evidence/fixture.json"}
        record = {"image_sha256": "a" * 64, "vision_pass": True,
                  "provider": probe.MODEL, "observed_at": now.isoformat()}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / candidate["reuse_vision_evidence"]
            path.parent.mkdir(parents=True)
            path.write_text(json.dumps(record))
            with mock.patch.object(probe, "ROOT", root):
                self.assertEqual(probe.reusable_vision(candidate, now.isoformat()), record)
                with self.assertRaisesRegex(RuntimeError, "VISION_EVIDENCE_NOT_APPLICABLE"):
                    probe.reusable_vision(dict(candidate, image_sha256="b" * 64), now.isoformat())
                with self.assertRaisesRegex(RuntimeError, "VISION_EVIDENCE_NOT_APPLICABLE"):
                    probe.reusable_vision(candidate, (now + timedelta(days=2)).isoformat())

    def nova_modules(self, client):
        sdk = types.ModuleType("boto3")
        sdk.client = mock.Mock(return_value=client)
        config = types.ModuleType("botocore.config")
        config.Config = mock.Mock(return_value="OFFLINE_CONFIG")
        errors = types.ModuleType("botocore.exceptions")
        errors.ClientError = type("ClientError", (Exception,), {})
        errors.BotoCoreError = type("BotoCoreError", (Exception,), {})
        return sdk, config, errors

    def test_nova_receives_original_image_bytes_once_and_reuses_client(self):
        image = b"exact offline fixture bytes"
        client = mock.Mock()
        client.converse.return_value = {"output": {"message": {"content": [
            {"text": '{"visual_ok":true}'}
        ]}}}
        sdk, config, errors = self.nova_modules(client)
        with mock.patch.dict(sys.modules, {"boto3": sdk, "botocore.config": config,
                                          "botocore.exceptions": errors}), \
                mock.patch.object(probe, "NOVA_CLIENT", None):
            result = probe.nova_inference([
                {"type": "text", "text": "Inspect image"},
                {"type": "image_url", "image_url": {"url":
                 "data:image/png;base64," + base64.b64encode(image).decode()}},
            ])
            probe.nova_inference("Separate business check")
        self.assertTrue(result["visual_ok"])
        sdk.client.assert_called_once()
        self.assertEqual(client.converse.call_count, 2)
        parts = client.converse.call_args_list[0].kwargs["messages"][0]["content"]
        self.assertEqual(parts[1]["image"]["source"]["bytes"], image)
        self.assertEqual(config.Config.call_args.kwargs["retries"]["total_max_attempts"], 1)

    def test_nova_access_error_is_sanitized_without_retry(self):
        client = mock.Mock()
        sdk, config, errors = self.nova_modules(client)
        exc = errors.ClientError("sensitive provider detail")
        exc.response = {"Error": {"Code": "AccessDeniedException", "Message": "private"}}
        client.converse.side_effect = exc
        with mock.patch.dict(sys.modules, {"boto3": sdk, "botocore.config": config,
                                          "botocore.exceptions": errors}), \
                mock.patch.object(probe, "NOVA_CLIENT", None):
            with self.assertRaisesRegex(RuntimeError, "^NOVA_AccessDeniedException$"):
                probe.nova_inference("Test")
        client.converse.assert_called_once()

    @mock.patch.dict("os.environ", {"IG_TOKEN": "offline-test-token", "IG_ID": "professional"}, clear=False)
    def test_professional_user_id_and_read_only_limit_endpoint(self):
        with mock.patch.object(probe, "request_json", side_effect=[
            {"id": "scoped", "user_id": "professional", "username": "designinfra.interiors"},
            {"data": [{"quota_usage": 0, "config": {}}]},
        ]) as request:
            result = probe.meta_access()
        self.assertTrue(result["identity_match"])
        self.assertTrue(result["publishing_limit_readable"])
        self.assertFalse(result["actual_publish_tested"])
        self.assertEqual(request.call_count, 2)
        for call in request.call_args_list:
            self.assertNotIn("offline-test-token", call.args[0])
            self.assertEqual(len(call.args), 2)
        self.assertIn("/professional/content_publishing_limit?", request.call_args_list[1].args[0])

    @mock.patch.dict("os.environ", {"IG_TOKEN": "offline-test-token", "IG_ID": "professional"}, clear=False)
    def test_wrong_target_blocks_before_limit_probe(self):
        with mock.patch.object(probe, "request_json", return_value={
            "user_id": "professional", "username": "another_account"
        }) as request:
            self.assertEqual(probe.meta_access()["status"], "TARGET_MISMATCH")
            request.assert_called_once()

    @mock.patch.dict("os.environ", {"IG_TOKEN": "offline-test-token", "IG_ID": "professional"}, clear=False)
    def test_permission_error_is_not_success(self):
        with mock.patch.object(probe, "request_json", side_effect=[
            {"user_id": "professional", "username": "designinfra.interiors"},
            RuntimeError("HTTP_403"),
        ]):
            result = probe.meta_access()
        self.assertTrue(result["identity_match"])
        self.assertFalse(result["publishing_limit_readable"])

    def test_invalid_inference_json_does_not_retry(self):
        with mock.patch.object(probe, "request_json", return_value={
            "choices": [{"message": {"content": "not JSON"}}]
        }) as request:
            with self.assertRaisesRegex(RuntimeError, "INVALID_MODEL_JSON"):
                probe.inference("offline-test-key", "test")
            request.assert_called_once()

    @mock.patch.dict("os.environ", {"IG_TOKEN": "", "IG_ID": ""}, clear=False)
    def test_missing_credentials_make_no_request(self):
        with mock.patch.object(probe, "request_json") as request:
            self.assertFalse(probe.meta_access()["identity_match"])
            request.assert_not_called()


if __name__ == "__main__":
    unittest.main()
