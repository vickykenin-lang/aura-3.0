import importlib.util
import pathlib
import unittest
from unittest import mock

MODULE_PATH = pathlib.Path(__file__).parents[1] / "scripts/publish_instagram.py"
SPEC = importlib.util.spec_from_file_location("publish_instagram", MODULE_PATH)
publish = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(publish)


class InstagramPublishTests(unittest.TestCase):
    def setUp(self):
        publish.POST_ID = "post-1"
        self.post = {"id": "post-1", "image": "https://example.invalid/post.jpg", "disclosure": "Inspiration reference.", "ig": {"hook_en": "Hook", "caption_hi": "Caption", "hashtags": "#DesignInfra"}}
        self.records = {"data/approvals.json": {"post-1": "approved_manual"}, "content/calendar.json": {"days": [self.post]}, "data/gate_results.json": {"batch_complete": True, "posts": {"post-1": {"pass": True, "visual_ok": True, "score": 9}}}, "content/published.json": {}}

    def load(self, path, default):
        return self.records.get(path, default)

    def test_publishes_only_approved_dual_gate_post(self):
        with mock.patch.object(publish, "load_json", side_effect=self.load), mock.patch.object(publish, "save_json") as save, mock.patch.object(publish, "publish_to_instagram", return_value={"id": "ig-media-1"}) as external, mock.patch.object(publish.release_guard, "prepare_release", return_value=self.post) as guard, mock.patch.dict(publish.os.environ, {"IG_AURA2_TOKEN": "TEST_ONLY", "IG_AURA2_ID": "test-account"}):
            self.assertEqual(publish.main(), 0)
            guard.assert_called_once_with(publish.ROOT, "post-1")
            external.assert_called_once()
            saved = {c.args[0]: c.args[1] for c in save.call_args_list}
            self.assertEqual(saved["data/approvals.json"]["post-1"], "published")
            self.assertEqual(saved["content/published.json"]["post-1"]["instagram"]["id"], "ig-media-1")

    def test_kill_switch_blocks_external_publish(self):
        with mock.patch.object(publish, "load_json", side_effect=self.load), mock.patch.object(publish.release_guard, "prepare_release", side_effect=publish.release_guard.ReleaseRefused("canonical kill switch blocks publishing")), mock.patch.object(publish, "publish_to_instagram") as external:
            self.assertEqual(publish.main(), 1)
            external.assert_not_called()

    def test_existing_media_id_is_idempotent(self):
        self.records["content/published.json"] = {"post-1": {"instagram": {"id": "existing-media"}}}
        with mock.patch.object(publish, "load_json", side_effect=self.load), mock.patch.object(publish, "save_json") as save, mock.patch.object(publish, "publish_to_instagram") as external, mock.patch.object(publish.release_guard, "prepare_release") as guard:
            self.assertEqual(publish.main(), 0)
            external.assert_not_called()
            guard.assert_not_called()
            save.assert_not_called()

    @mock.patch.object(publish, "request_json")
    def test_discovers_single_page_linked_instagram_account(self, request_json):
        request_json.side_effect = [publish.PublishError("not an Instagram Login token"), {"id": "page-1", "instagram_business_account": {"id": "ig-1"}}]
        self.assertEqual(publish.discover_target("TEST_ONLY"), ("https://graph.facebook.com", "ig-1"))

    @mock.patch.object(publish, "request_json")
    def test_refuses_ambiguous_managed_accounts(self, request_json):
        request_json.side_effect = [publish.PublishError("not an Instagram Login token"), {"id": "user-1"}, {"data": [{"instagram_business_account": {"id": "ig-1"}}, {"instagram_business_account": {"id": "ig-2"}}]}]
        with self.assertRaisesRegex(publish.PublishError, "multiple Instagram accounts"):
            publish.discover_target("TEST_ONLY")


if __name__ == "__main__":
    unittest.main()
