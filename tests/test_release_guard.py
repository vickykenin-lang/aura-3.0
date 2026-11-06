import copy
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock
from PIL import Image

SCRIPTS = Path(__file__).resolve().parents[1] / 'scripts'
sys.path.insert(0, str(SCRIPTS))
import release_guard as guard


class ReleaseFixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        for name in guard.RELEASE_FILES:
            p = self.root / name
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text('test release implementation')
        self.put('governance/publishing_target.json', {'instagram_username': 'designinfra.interiors'})
        self.put('governance/authority_policy.json', {'rules': {'instagram_publish': 'FOUNDER_ONLY'}})
        self.put('governance/image_validation_rulebook.json', {'quality': {'minimum_source_width': 1200, 'minimum_source_height': 800}})
        self.put('state/control.json', {'kill_switch': False, 'business_execution_enabled': True, 'external_execution_enabled': True, 'certification_status': 'VERIFIED'})
        self.put('data/control.json', {'kill_switch': False})
        self.certificate = {'department_id': 'aura3', 'certification': 'VERIFIED', 'live': True, 'observed_at': datetime.now(timezone.utc).isoformat(), 'checks': [{'check': c, 'pass': True} for c in sorted(guard.CERTIFICATE_CHECKS)], 'release_code_sha256': guard.release_code_sha256(self.root)}
        self.put(guard.CERTIFICATE_PATH, self.certificate)
        data = io.BytesIO()
        Image.new('RGB', (1200, 1500), '#ded8ce').save(data, format='JPEG')
        self.image_bytes = data.getvalue()
        self.post = {'id': 'offline-only', 'image': 'https://example.invalid/reviewed.jpg', 'disclosure': 'AI-generated interior design concept.', 'ig': {'hook_en': 'Modern luxury', 'caption_hi': 'Reviewed caption.', 'hashtags': '#DesignInfra'}}
        self.proof = guard.record_image_proof(self.post['image'], 'image/jpeg', self.image_bytes)
        self.value = guard.manifest(self.post, self.proof, self.root)
        self.gates = {'batch_complete': True, 'posts': {'offline-only': {'pass': True, 'visual_ok': True, 'score': 9, 'release_manifest': self.value, 'release_manifest_sha256': guard.sha(self.value)}}}
        self.put('content/calendar.json', {'days': [self.post]})
        self.put('content/published.json', {})
        self.put('data/gate_results.json', self.gates)
        self.put('data/approvals.json', {'offline-only': 'approved_manual'})
        self.put('data/approval_manifests.json', {'offline-only': {'manifest': self.value, 'manifest_sha256': guard.sha(self.value)}})

    def put(self, path, value):
        p = self.root / path
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(value))

    def run_guard(self):
        with mock.patch.object(guard, 'fetch_image_proof', return_value=self.proof):
            return guard.prepare_release(self.root, 'offline-only')


class ReleaseGuardTests(ReleaseFixture):
    def test_exact_approved_content_passes(self):
        self.assertEqual(self.run_guard(), self.post)

    def test_canonical_external_disable_blocks_before_network(self):
        self.put('state/control.json', {'kill_switch': False, 'external_execution_enabled': False})
        with mock.patch.object(guard, 'fetch_image_proof') as network:
            with self.assertRaises(guard.ReleaseRefused):
                guard.prepare_release(self.root, 'offline-only')
            network.assert_not_called()

    def test_unverified_canonical_certification_blocks(self):
        self.put('state/control.json', {'kill_switch': False, 'business_execution_enabled': True, 'external_execution_enabled': True, 'certification_status': 'NOT_CERTIFIED'})
        with self.assertRaises(guard.ReleaseRefused):
            self.run_guard()

    def test_legacy_kill_switch_still_blocks(self):
        self.put('data/control.json', {'kill_switch': True})
        with self.assertRaises(guard.ReleaseRefused):
            self.run_guard()

    def test_stale_future_and_partial_certificates_block(self):
        for change in [{'observed_at': (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()}, {'observed_at': (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()}, {'checks': [{'check': 'heartbeat_runtime', 'pass': True}]}]:
            with self.subTest(change=change):
                self.put(guard.CERTIFICATE_PATH, {**self.certificate, **change})
                with self.assertRaises(guard.ReleaseRefused):
                    self.run_guard()

    def test_release_code_change_invalidates_certificate(self):
        (self.root / 'scripts/publish_instagram.py').write_text('different implementation')
        with self.assertRaises(guard.ReleaseRefused):
            self.run_guard()

    def test_caption_or_image_url_change_invalidates_qa_and_approval(self):
        for field in ['caption', 'image']:
            changed = copy.deepcopy(self.post)
            if field == 'caption':
                changed['ig']['caption_hi'] = 'Changed after approval.'
            else:
                changed['image'] = 'https://example.invalid/replacement.jpg'
            self.put('content/calendar.json', {'days': [changed]})
            with self.subTest(field=field), self.assertRaises(guard.ReleaseRefused):
                self.run_guard()

    def test_same_url_changed_image_bytes_blocks(self):
        with mock.patch.object(guard, 'fetch_image_proof', return_value={**self.proof, 'sha256': 'b' * 64}):
            with self.assertRaises(guard.ReleaseRefused):
                guard.prepare_release(self.root, 'offline-only')

    def test_legacy_id_only_approval_is_not_migrated(self):
        self.put('data/approval_manifests.json', {})
        with self.assertRaises(guard.ReleaseRefused):
            self.run_guard()

    def test_target_change_invalidates_qa(self):
        self.put('governance/publishing_target.json', {'instagram_username': 'another.account'})
        # Even if separately recertified, old content approval is target-specific.
        self.put(guard.CERTIFICATE_PATH, {**self.certificate, 'release_code_sha256': guard.release_code_sha256(self.root)})
        with self.assertRaises(guard.ReleaseRefused):
            self.run_guard()

    def test_1122_pixel_source_is_rejected_without_weakening_rulebook(self):
        with self.assertRaisesRegex(guard.ReleaseRefused, 'resolution'):
            guard.manifest(self.post, {**self.proof, 'width': 1122, 'height': 1402}, self.root)

    def test_missing_fresh_source_proof_cannot_create_gate_binding(self):
        guard.SOURCE_PROOFS.clear()
        result = guard.bind_qualified_gate(self.post, {'pass': True, 'visual_ok': True}, self.root)
        self.assertNotIn('release_manifest', result)
        self.assertIn('release_binding_error', result)

    def test_qualified_gate_is_bound_to_downloaded_bytes(self):
        result = guard.bind_qualified_gate(self.post, {'pass': True, 'visual_ok': True}, self.root)
        self.assertEqual(result['release_manifest'], self.value)

    def test_already_published_is_a_pure_noop_even_when_controls_disabled(self):
        self.put('content/published.json', {'offline-only': {'instagram': {'id': 'EXISTING_MEDIA'}}})
        self.put('state/control.json', {'kill_switch': True})
        with mock.patch.object(guard, 'fetch_image_proof') as network:
            self.assertIsNone(guard.prepare_release(self.root, 'offline-only'))
            network.assert_not_called()


class PublisherBoundaryTests(ReleaseFixture):
    def setUp(self):
        super().setUp()
        spec = importlib.util.spec_from_file_location('publisher_under_test', SCRIPTS / 'publish_instagram.py')
        self.publisher = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.publisher)
        self.publisher.ROOT = str(self.root)
        self.publisher.POST_ID = 'offline-only'

    def test_discovered_wrong_account_never_creates_container(self):
        p = self.publisher
        with mock.patch.object(p, 'discover_target', return_value=('https://graph.instagram.com', 'wrong-account')), mock.patch.object(p, 'request_json') as api:
            with self.assertRaises(p.PublishError):
                p.create_container(self.post['image'], 'Caption', 'expected-account', 'TEST_ONLY')
            api.assert_not_called()

    def test_wrong_username_never_creates_container(self):
        p = self.publisher
        with mock.patch.object(p, 'discover_target', return_value=('https://graph.instagram.com', 'expected-account')), mock.patch.object(p, 'request_json', return_value={'id': 'expected-account', 'username': 'wrong.username'}) as api:
            with self.assertRaises(p.PublishError):
                p.create_container(self.post['image'], 'Caption', 'expected-account', 'TEST_ONLY')
            self.assertEqual(api.call_args.args[1], 'GET')
            self.assertEqual(api.call_count, 1)

    def test_actual_main_refuses_external_disable_without_social_calls(self):
        p = self.publisher
        self.put('state/control.json', {'kill_switch': False, 'external_execution_enabled': False})
        with mock.patch.object(p, 'request_json') as api, mock.patch.object(guard, 'fetch_image_proof') as image:
            self.assertEqual(p.main(), 1)
            api.assert_not_called()
            image.assert_not_called()

    def test_actual_main_refuses_changed_caption_without_social_calls(self):
        p = self.publisher
        self.post['ig']['caption_hi'] = 'Changed after approval.'
        self.put('content/calendar.json', {'days': [self.post]})
        with mock.patch.object(p, 'request_json') as api:
            self.assertEqual(p.main(), 1)
            api.assert_not_called()

    def test_full_mocked_success_uses_only_confirmed_account(self):
        p = self.publisher
        replies = [{'id': 'expected-account', 'username': 'designinfra.interiors'}, {'id': 'MOCK_CONTAINER'}, {'status_code': 'FINISHED'}, {'id': 'MOCK_MEDIA'}, {'id': 'MOCK_MEDIA', 'permalink': 'https://example.invalid/post', 'media_type': 'IMAGE'}]
        with mock.patch.dict(p.os.environ, {'IG_AURA2_TOKEN': 'TEST_ONLY', 'IG_AURA2_ID': 'expected-account'}), mock.patch.object(guard, 'fetch_image_proof', return_value=self.proof), mock.patch.object(p, 'discover_target', return_value=('https://graph.instagram.com', 'expected-account')), mock.patch.object(p, 'request_json', side_effect=replies) as api:
            self.assertEqual(p.main(), 0)
            self.assertEqual(api.call_count, 5)
            self.assertEqual(api.call_args_list[1].args[2], 'expected-account/media')
        result = json.loads((self.root / 'content/published.json').read_text())
        self.assertEqual(result['offline-only']['instagram']['id'], 'MOCK_MEDIA')


class ApprovalBoundaryTests(ReleaseFixture):
    def setUp(self):
        super().setUp()
        spec = importlib.util.spec_from_file_location('approval_under_test', SCRIPTS / 'approve_manual.py')
        self.approval = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.approval)
        self.approval.ROOT = str(self.root)
        self.approval.POST_ID = 'offline-only'
        self.put('data/approvals.json', {'offline-only': 'pending'})
        self.put('data/approval_manifests.json', {})

    def test_exact_dashboard_fingerprint_records_both_decision_and_manifest(self):
        with mock.patch.dict(self.approval.os.environ, {'APPROVED_MANIFEST_SHA256': guard.sha(self.value)}), mock.patch.object(guard, 'fetch_image_proof', return_value=self.proof):
            self.assertEqual(self.approval.main(), 0)
        records = json.loads((self.root / 'data/approval_manifests.json').read_text())
        self.assertEqual(records['offline-only']['manifest'], self.value)
        decisions = json.loads((self.root / 'data/approvals.json').read_text())
        self.assertEqual(decisions['offline-only'], 'approved_manual')

    def test_missing_or_different_dashboard_fingerprint_cannot_approve(self):
        for fingerprint in ['', 'b' * 64]:
            with self.subTest(fingerprint=fingerprint), mock.patch.dict(self.approval.os.environ, {'APPROVED_MANIFEST_SHA256': fingerprint}), mock.patch.object(guard, 'fetch_image_proof') as image:
                self.assertEqual(self.approval.main(), 1)
                image.assert_not_called()
                self.assertEqual(json.loads((self.root / 'data/approvals.json').read_text())['offline-only'], 'pending')

    def test_approval_requires_same_image_bytes_as_qa(self):
        with mock.patch.dict(self.approval.os.environ, {'APPROVED_MANIFEST_SHA256': guard.sha(self.value)}), mock.patch.object(guard, 'fetch_image_proof', return_value={**self.proof, 'sha256': 'b' * 64}):
            self.assertEqual(self.approval.main(), 1)

    def test_style_acceptance_does_not_replace_public_release_approval(self):
        self.put('data/approvals.json', {'offline-only': 'STYLE_ACCEPTED_FOR_NOW'})
        with mock.patch.object(guard, 'fetch_image_proof') as image:
            with self.assertRaises(guard.ReleaseRefused):
                guard.prepare_release(self.root, 'offline-only')
            image.assert_not_called()


if __name__ == '__main__':
    unittest.main()
