import io
import json
from pathlib import Path
import sys
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import release_guard
import run_deepseek_primary as core
import certify_live


class PipelineBindingTests(unittest.TestCase):
    def test_qualification_binds_caption_to_bytes_seen_by_the_downloader(self):
        data = io.BytesIO()
        Image.new('RGB', (1200, 1500), 'ivory').save(data, format='JPEG')
        post = {'id': 'local-only', 'image': 'https://example.invalid/image.jpg', 'ig': {'hook_en': 'Reviewed room', 'caption_hi': 'Reviewed copy', 'hashtags': '#DesignInfra'}, 'disclosure': 'AI-generated concept'}
        def vision(*args):
            release_guard.record_image_proof(post['image'], 'image/jpeg', data.getvalue())
            return {'visual_ok': True, 'quality': 9}
        with mock.patch.object(core, 'deepseek_vision', side_effect=vision), mock.patch.object(core, 'deepseek_business', return_value={'pass': True, 'score': 9}):
            result = core.deepseek_qualify_post(post, '', 'TEST_ONLY')
        self.assertEqual(result['release_manifest']['target_username'], 'designinfra.interiors')
        self.assertEqual(result['release_manifest_sha256'], release_guard.sha(result['release_manifest']))

    def test_preflight_failure_persists_sanitized_status_without_retry(self):
        with mock.patch.dict(core.os.environ, {'DEEPSEEK_API_KEY': 'TEST_ONLY'}), mock.patch.object(core.maintainer, 'save_json') as save, mock.patch.object(core, 'deepseek_provider_preflight', side_effect=RuntimeError('DeepSeek HTTP 403 token=DO_NOT_LOG')) as preflight, mock.patch.object(core, 'revalidate_legacy_metadata_gates') as revalidation:
            self.assertEqual(core.main(), 1)
        preflight.assert_called_once()
        revalidation.assert_not_called()
        status = save.call_args.args[1]
        self.assertEqual(status['stage'], 'provider_preflight')
        self.assertEqual(status['http_status'], 403)
        self.assertNotIn('DO_NOT_LOG', json.dumps(status))

    def test_legacy_revalidation_failure_is_distinguished_from_preflight(self):
        with mock.patch.dict(core.os.environ, {'DEEPSEEK_API_KEY': 'TEST_ONLY'}), mock.patch.object(core.maintainer, 'save_json') as save, mock.patch.object(core, 'deepseek_provider_preflight'), mock.patch.object(core, 'revalidate_legacy_metadata_gates', side_effect=RuntimeError('PRIVATE')):
            self.assertEqual(core.main(), 1)
        self.assertEqual(save.call_args.args[1]['stage'], 'legacy_visual_revalidation')
        self.assertIsNone(save.call_args.args[1]['http_status'])

    def test_missing_credential_has_current_blocked_status(self):
        with mock.patch.dict(core.os.environ, {'DEEPSEEK_API_KEY': '', 'DEEPSEEK_KEY': ''}), mock.patch.object(core.maintainer, 'save_json') as save, mock.patch.object(core, 'deepseek_provider_preflight') as preflight:
            self.assertEqual(core.main(), 1)
        self.assertEqual(save.call_args.args[1]['category'], 'CREDENTIALS_UNAVAILABLE')
        preflight.assert_not_called()

    def test_certification_does_not_restamp_stale_qualification(self):
        self.assertTrue(certify_live.fresh({'observed_at': datetime.now(timezone.utc).isoformat()}))
        self.assertFalse(certify_live.fresh({'observed_at': (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()}))
        self.assertFalse(certify_live.fresh({'observed_at': (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()}))
        self.assertFalse(certify_live.fresh({}))


if __name__ == '__main__':
    unittest.main()
