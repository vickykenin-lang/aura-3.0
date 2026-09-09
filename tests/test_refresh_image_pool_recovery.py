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


class StockSourceTests(unittest.TestCase):
    def setUp(self):
        self.cfg = {
            "min_width": 1200,
            "min_height": 800,
            "allowed_source_licenses": ["Pexels License", "Pixabay Content License", "Unsplash License"],
            "metadata_prefilter": {"positive_tokens": ["office", "workspace", "meeting", "interior"], "negative_tokens": ["historic"]},
        }
        self.search = {"query": "modern office interior", "photo_tag": "office", "angle": "current office planning"}

    def test_retryable_429_recovers_without_logging_secret(self):
        err = urllib.error.HTTPError("https://example.invalid", 429, "rate", {"Retry-After": "0"}, None)
        ok = io.BytesIO(json.dumps({"ok": True}).encode())
        with mock.patch.object(module.urllib.request, "urlopen", side_effect=[err, ok]) as urlopen, mock.patch.object(module.time, "sleep"):
            result = module._json_request("https://example.invalid", {"Authorization": "SECRET"}, 5, source="pexels", attempts=2)
        self.assertEqual(result, {"ok": True})
        self.assertEqual(urlopen.call_count, 2)

    def test_pexels_item_preserves_license_and_source(self):
        source = {"id": "pexels", "license": "Pexels License", "license_url": "https://www.pexels.com/license/"}
        row = {
            "id": 123, "width": 2400, "height": 1600,
            "url": "https://www.pexels.com/photo/modern-office-123/",
            "photographer": "Example",
            "alt": "Modern office interior workspace",
            "src": {"large2x": "https://images.pexels.com/photos/123/photo.jpeg", "medium": "https://images.pexels.com/photos/123/photo.jpeg?w=600"},
        }
        item = module._stock_item(self.cfg, source, self.search, row)
        self.assertIsNotNone(item)
        self.assertEqual(item["source"], "Pexels")
        self.assertEqual(item["license"], "Pexels License")

    def test_pixabay_item_preserves_license_and_source(self):
        source = {"id": "pixabay", "license": "Pixabay Content License", "license_url": "https://pixabay.com/service/license-summary/"}
        row = {
            "id": 456, "imageWidth": 2200, "imageHeight": 1400,
            "largeImageURL": "https://cdn.pixabay.com/photo/office.jpg",
            "previewURL": "https://cdn.pixabay.com/photo/office-preview.jpg",
            "pageURL": "https://pixabay.com/photos/office-456/",
            "tags": "modern office, interior, workspace", "user": "Example",
        }
        item = module._stock_item(self.cfg, source, self.search, row)
        self.assertIsNotNone(item)
        self.assertEqual(item["source"], "Pixabay")
        self.assertEqual(item["license"], "Pixabay Content License")

    def test_unsplash_item_uses_direct_image_url_and_license(self):
        source = {"id": "unsplash", "license": "Unsplash License", "license_url": "https://unsplash.com/license"}
        row = {
            "id": "abc", "width": 4000, "height": 2600,
            "alt_description": "Modern office interior workspace",
            "urls": {"raw": "https://images.unsplash.com/photo-abc?ixid=x", "small": "https://images.unsplash.com/photo-abc?w=400"},
            "links": {"html": "https://unsplash.com/photos/abc"},
            "user": {"name": "Example"},
        }
        item = module._stock_item(self.cfg, source, self.search, row)
        self.assertIsNotNone(item)
        self.assertEqual(item["source"], "Unsplash")
        self.assertIn("w=1600", item["image"])
        self.assertEqual(item["license"], "Unsplash License")

    def test_old_sources_are_not_active(self):
        cfg = json.loads((ROOT / "data/image_sources.json").read_text())
        ids = [str(x.get("id")) for x in cfg.get("sources", []) if x.get("enabled", True)]
        self.assertEqual(ids, ["pexels", "pixabay", "unsplash"])
        text = json.dumps(cfg).lower()
        self.assertNotIn('"wikimedia_commons"', text)
        self.assertNotIn('"openverse"', text)
        self.assertNotIn('"nappy_fallback"', text)


if __name__ == "__main__":
    unittest.main()
