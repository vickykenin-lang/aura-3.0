import importlib.util
import io
import json
import unittest
from pathlib import Path
from unittest import mock
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("refresh_image_pool", ROOT / "scripts/refresh_image_pool.py")
module = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(module)


class VisualAcquisitionTests(unittest.TestCase):
    def test_image_key_ignores_query_parameters(self):
        left = module.image_key("https://upload.wikimedia.org/a/b/photo.jpg?width=1200")
        right = module.image_key("https://upload.wikimedia.org/a/b/photo.jpg?width=1600")
        self.assertEqual(left, right)

    def test_license_allowlist_accepts_cc0_and_public_domain(self):
        prefixes = ["CC0", "PUBLIC DOMAIN"]
        self.assertTrue(module.license_allowed("CC0 1.0", prefixes))
        self.assertTrue(module.license_allowed("Public domain", prefixes))
        self.assertFalse(module.license_allowed("CC BY-SA 4.0", prefixes))

    def test_page_conversion_rejects_attribution_required_license(self):
        config = {
            "allowed_mime_types": ["image/jpeg"],
            "allowed_license_prefixes": ["CC0", "PUBLIC DOMAIN"],
            "min_width": 900,
            "min_height": 600,
        }
        page = {
            "title": "File:Office.jpg",
            "imageinfo": [{
                "mime": "image/jpeg",
                "width": 1600,
                "height": 1000,
                "url": "https://upload.wikimedia.org/example/office.jpg",
                "thumburl": "https://upload.wikimedia.org/example/thumb/office.jpg",
                "descriptionurl": "https://commons.wikimedia.org/wiki/File:Office.jpg",
                "extmetadata": {
                    "LicenseShortName": {"value": "CC BY-SA 4.0"},
                    "Artist": {"value": "Example"},
                },
            }],
        }
        self.assertIsNone(module.pool_item_from_page(config, {"photo_tag": "office", "query": "office"}, page))

    def test_page_conversion_accepts_public_domain_https_image(self):
        config = {
            "allowed_mime_types": ["image/jpeg"],
            "allowed_license_prefixes": ["CC0", "PUBLIC DOMAIN"],
            "min_width": 900,
            "min_height": 600,
        }
        page = {
            "title": "File:Office.jpg",
            "imageinfo": [{
                "mime": "image/jpeg",
                "width": 1600,
                "height": 1000,
                "url": "https://upload.wikimedia.org/example/office.jpg",
                "thumburl": "https://upload.wikimedia.org/example/thumb/office.jpg",
                "descriptionurl": "https://commons.wikimedia.org/wiki/File:Office.jpg",
                "extmetadata": {
                    "LicenseShortName": {"value": "Public domain"},
                    "Artist": {"value": "Example contributor"},
                },
            }],
        }
        item = module.pool_item_from_page(
            config,
            {"photo_tag": "office", "query": "office", "angle": "office execution"},
            page,
        )
        self.assertIsNotNone(item)
        self.assertEqual(item["license"], "Public domain")
        self.assertEqual(item["photo_tag"], "office")
        self.assertTrue(item["image"].startswith("https://"))

    def test_commons_query_uses_persisted_offset_and_page_size(self):
        payload = {
            "continue": {"gsroffset": 150, "continue": "gsroffset||"},
            "query": {"pages": [{"title": "File:A.jpg"}]},
        }
        response = io.BytesIO(json.dumps(payload).encode("utf-8"))
        config = {
            "endpoint": "https://commons.wikimedia.org/w/api.php",
            "search_page_size": 50,
            "timeout_seconds": 15,
            "user_agent": "AURA3-Test/1.0",
        }
        search = {"query": "office interior"}
        with mock.patch.object(module.urllib.request, "urlopen", return_value=response) as urlopen:
            pages, next_offset, has_more = module.commons_query(config, search, offset=100)
        request = urlopen.call_args.args[0]
        params = parse_qs(urlparse(request.full_url).query)
        self.assertEqual(params["gsroffset"], ["100"])
        self.assertEqual(params["gsrlimit"], ["50"])
        self.assertEqual(next_offset, 150)
        self.assertTrue(has_more)
        self.assertEqual(len(pages), 1)

    def test_commons_query_marks_last_short_page_complete(self):
        payload = {"query": {"pages": [{"title": "File:A.jpg"}]}}
        response = io.BytesIO(json.dumps(payload).encode("utf-8"))
        config = {
            "endpoint": "https://commons.wikimedia.org/w/api.php",
            "search_page_size": 50,
            "timeout_seconds": 15,
        }
        with mock.patch.object(module.urllib.request, "urlopen", return_value=response):
            pages, next_offset, has_more = module.commons_query(config, {"query": "office"}, offset=200)
        self.assertEqual(len(pages), 1)
        self.assertEqual(next_offset, 200)
        self.assertFalse(has_more)


if __name__ == "__main__":
    unittest.main()
