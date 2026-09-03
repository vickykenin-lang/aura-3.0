import importlib.util
import unittest
from pathlib import Path

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


if __name__ == "__main__":
    unittest.main()
