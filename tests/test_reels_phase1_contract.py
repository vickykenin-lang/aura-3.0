import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))

import select_reel_music  # noqa: E402
import render_reel_ffmpeg  # noqa: E402


class ReelsPhase1ContractTests(unittest.TestCase):
    def load(self, path):
        return json.loads((ROOT / path).read_text(encoding='utf-8'))

    def test_shadow_config_has_no_publish_authority(self):
        cfg = self.load('data/reels_config.json')
        self.assertFalse(cfg['enabled'])
        self.assertEqual(cfg['mode'], 'SHADOW_ONLY')
        self.assertFalse(cfg['publish_authority'])
        self.assertTrue(cfg['founder_approval_required'])
        self.assertFalse(cfg['failure_isolation']['reel_failure_blocks_static_pipeline'])

    def test_three_pilot_briefs_are_unique_and_policy_compliant(self):
        calendar = self.load('data/reels_calendar.json')
        reels = calendar['reels']
        self.assertEqual(len(reels), 3)
        images = [r['image'].split('?', 1)[0] for r in reels]
        self.assertEqual(len(images), len(set(images)))
        for reel in reels:
            self.assertGreaterEqual(float(reel['duration_seconds']), 5.0)
            self.assertLessEqual(float(reel['duration_seconds']), 10.0)
            self.assertEqual(reel['disclosure'], 'Inspiration reference')
            self.assertFalse(reel['public_action_authorized'])
            self.assertGreaterEqual(len(reel['overlay_lines']), 2)
            self.assertLessEqual(len(reel['overlay_lines']), 4)
            self.assertIn('designinfra.in', reel['cta'])

    def test_music_license_gate(self):
        catalog = self.load('data/reels_music_catalog.json')
        signals = self.load('data/reels_trend_signals.json')['signals']
        selected = select_reel_music.select_track(signals[0], catalog)
        self.assertIsNotNone(selected)
        self.assertTrue(select_reel_music.license_ok(selected))
        unsafe = dict(selected)
        unsafe['commercial_use_allowed'] = False
        self.assertFalse(select_reel_music.license_ok(unsafe))
        unsafe = dict(selected)
        unsafe['license_evidence'] = ''
        self.assertFalse(select_reel_music.license_ok(unsafe))

    def test_trend_never_overrides_license(self):
        signal = {'genre': 'ambient_house', 'mood': 'premium', 'tempo_bpm': 96, 'energy': 'medium'}
        catalog = {'tracks': [
            {'id': 'unsafe-perfect', 'genre': 'ambient_house', 'moods': ['premium'], 'bpm': 96, 'energy': 'medium', 'commercial_use_allowed': False, 'license_type': 'UNKNOWN', 'license_evidence': '', 'source_reference': 'x'},
            {'id': 'safe-less-perfect', 'genre': 'ambient_house', 'moods': ['calm'], 'bpm': 92, 'energy': 'medium', 'commercial_use_allowed': True, 'license_type': 'AURA3_ORIGINAL_PROCEDURAL', 'license_evidence': 'internal://evidence', 'source_reference': 'internal://track'},
        ]}
        self.assertEqual(select_reel_music.select_track(signal, catalog)['id'], 'safe-less-perfect')

    def test_renderer_filter_retains_disclosure_and_cta(self):
        reel = self.load('data/reels_calendar.json')['reels'][0]
        vf = render_reel_ffmpeg.build_video_filter(reel, 7.0)
        self.assertIn('Inspiration reference', vf)
        self.assertIn('designinfra.in', vf)
        self.assertIn('zoompan', vf)

    def test_reel_approval_registry_is_pending_only(self):
        approvals = self.load('data/reels_approvals.json')
        states = [v for k, v in approvals.items() if not k.startswith('_')]
        self.assertTrue(states)
        self.assertEqual(set(states), {'pending'})
        self.assertEqual(self.load('data/reels_published.json'), {})


if __name__ == '__main__':
    unittest.main()
