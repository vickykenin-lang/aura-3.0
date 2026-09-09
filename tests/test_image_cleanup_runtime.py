import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import sys
sys.path.insert(0, 'scripts')
import aura3_image_cleanup_runtime as cleanup


class CleanupRuntimeTests(unittest.TestCase):
    def test_cleanup_candidate_requires_current_quality_overlay(self):
        self.assertTrue(cleanup._cleanup_candidate({
            'visual_ok': False,
            'quality': 8,
            'design_freshness': 'Current',
            'copyright_status': 'Clear',
            'watermarks': 'Present',
            'brand_logo_risk': 'None',
        }))
        self.assertTrue(cleanup._cleanup_candidate({
            'visual_ok': False,
            'quality': 9,
            'design_freshness': 'Current',
            'copyright_status': 'Unknown',
            'watermarks': 'None',
            'brand_logo_risk': 'Present',
        }))

    def test_cleanup_candidate_rejects_flagged_or_dated_image(self):
        self.assertFalse(cleanup._cleanup_candidate({
            'visual_ok': False,
            'quality': 9,
            'design_freshness': 'Current',
            'copyright_status': 'Flagged',
            'watermarks': 'Present',
            'brand_logo_risk': 'None',
        }))
        self.assertFalse(cleanup._cleanup_candidate({
            'visual_ok': False,
            'quality': 9,
            'design_freshness': 'Dated',
            'copyright_status': 'Clear',
            'watermarks': 'Present',
            'brand_logo_risk': 'None',
        }))

    def test_cleanup_candidate_does_not_reedit_clean_visual(self):
        self.assertFalse(cleanup._cleanup_candidate({
            'visual_ok': True,
            'quality': 9,
            'design_freshness': 'Current',
            'copyright_status': 'Clear',
            'watermarks': 'None',
            'brand_logo_risk': 'None',
        }))

    def test_cleanup_image_requires_https(self):
        with self.assertRaises(ValueError):
            cleanup.cleanup_image('http://example.com/image.jpg')

    def test_provider_request_requires_secret_without_exposing_it(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(RuntimeError, 'RUNWAYML_API_SECRET is required'):
                cleanup._json_request('https://api.dev.runwayml.com/v1/tasks/test')

    def test_persisted_asset_uses_pages_url_and_repo_asset_path(self):
        fake_bytes = b'fake-image-bytes'
        with tempfile.TemporaryDirectory() as td, \
             mock.patch.object(cleanup.Path, 'resolve', return_value=Path(td) / 'scripts' / 'aura3_image_cleanup_runtime.py'), \
             mock.patch.object(cleanup, '_download_image', return_value=('image/jpeg', fake_bytes)), \
             mock.patch.dict(os.environ, {'GITHUB_REPOSITORY': 'vickykenin-lang/aura-3.0'}, clear=False):
            stable_url, path = cleanup._persist_cleaned_asset('https://source.example/a.jpg', 'https://provider.example/out.jpg')
            self.assertTrue(stable_url.startswith('https://vickykenin-lang.github.io/aura-3.0/assets/cleaned/'))
            self.assertTrue(path.exists())
            self.assertEqual(path.read_bytes(), fake_bytes)


if __name__ == '__main__':
    unittest.main()
