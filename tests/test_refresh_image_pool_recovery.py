import importlib.util
import io
import json
import urllib.error
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("refresh_image_pool", ROOT / "scripts/refresh_image_pool.py")
module = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(module)


class RecoveryTransportTests(unittest.TestCase):
    def test_retryable_429_recovers_without_relaxing_query(self):
        err = urllib.error.HTTPError("https://api.openverse.org/v1/images/", 429, "rate", {"Retry-After": "0"}, None)
        ok = io.BytesIO(json.dumps({"page": 1, "page_count": 1, "results": []}).encode())
        with mock.patch.object(module.urllib.request, "urlopen", side_effect=[err, ok]) as urlopen, mock.patch.object(module.time, "sleep"):
            rows, next_page, has_more = module.openverse_query(
                {"search_page_size": 20, "timeout_seconds": 5, "user_agent": "AURA3-Test/1.0"},
                {"query": "modern office"},
                1,
                {"endpoint": "https://api.openverse.org/v1/images/", "license_slugs": ["cc0", "pdm"], "http_retry_attempts": 2},
            )
        self.assertEqual(rows, [])
        self.assertEqual(next_page, 2)
        self.assertFalse(has_more)
        self.assertEqual(urlopen.call_count, 2)

    def test_commons_query_adds_bitmap_filter(self):
        ok = io.BytesIO(json.dumps({"query": {"pages": []}}).encode())
        with mock.patch.object(module.urllib.request, "urlopen", return_value=ok) as urlopen:
            module.commons_query({"search_page_size": 20, "timeout_seconds": 5}, {"query": "modern office photograph"})
        self.assertIn("filetype%3Abitmap", urlopen.call_args.args[0].full_url)
        self.assertNotIn("photograph", urlopen.call_args.args[0].full_url)

    def test_openverse_bearer_token_is_optional_and_secret_not_logged(self):
        headers = module._headers({"user_agent": "AURA3-Test/1.0"}, openverse=True)
        self.assertNotIn("Authorization", headers)
        with mock.patch.dict(module.os.environ, {"OPENVERSE_ACCESS_TOKEN": "secret-token"}):
            headers = module._headers({}, openverse=True)
        self.assertEqual(headers["Authorization"], "Bearer secret-token")


if __name__ == "__main__":
    unittest.main()
