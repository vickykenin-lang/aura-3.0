import sys
from pathlib import Path
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import check_first_post_readiness as probe


class FirstPostReadinessTests(unittest.TestCase):
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
