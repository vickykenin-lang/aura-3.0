import importlib.util
import pathlib
import unittest
from unittest import mock


MODULE_PATH = pathlib.Path(__file__).parents[1] / "scripts" / "publish_instagram.py"
SPEC = importlib.util.spec_from_file_location("publish_instagram", MODULE_PATH)
publish = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(publish)


class InstagramPublishTests(unittest.TestCase):
    def setUp(self):
        publish.POST_ID = "post-1"

    @mock.patch.object(publish, "save_json")
    @mock.patch.object(publish, "publish_to_instagram")
    @mock.patch.object(publish, "load_json")
    def test_publishes_only_approved_dual_gate_post(self, load_json, publish_post, save_json):
        load_json.side_effect = [
            {"kill_switch": False},
            {"post-1": "approved_manual"},
            {
                "days": [
                    {
                        "id": "post-1",
                        "image": "https://example.com/post.jpg",
                        "disclosure": "Inspiration reference.",
                        "ig": {
                            "hook_en": "Hook",
                            "caption_hi": "Caption",
                            "hashtags": "#DesignInfra",
                        },
                    }
                ]
            },
            {
                "batch_complete": True,
                "posts": {"post-1": {"pass": True, "visual_ok": True, "score": 9}},
            },
            {},
        ]
        publish_post.return_value = {
            "id": "ig-media-1",
            "url": "https://instagram.com/p/example/",
            "at": "2026-08-22T12:00:00+00:00",
        }

        with mock.patch.dict(
            publish.os.environ,
            {"IG_ACCESS_TOKEN": "secret", "IG_USER_ID": "ig-user"},
            clear=False,
        ):
            self.assertEqual(publish.main(), 0)

        publish_post.assert_called_once()
        saved = {call.args[0]: call.args[1] for call in save_json.call_args_list}
        self.assertEqual(saved["data/approvals.json"]["post-1"], "published")
        self.assertEqual(
            saved["content/published.json"]["post-1"]["instagram"]["id"],
            "ig-media-1",
        )

    @mock.patch.object(publish, "load_json", return_value={"kill_switch": True})
    def test_kill_switch_blocks_external_publish(self, _load_json):
        self.assertEqual(publish.main(), 1)

    @mock.patch.object(publish, "save_json")
    @mock.patch.object(publish, "publish_to_instagram")
    @mock.patch.object(publish, "load_json")
    def test_existing_media_id_is_idempotent(self, load_json, publish_post, save_json):
        load_json.side_effect = [
            {"kill_switch": False},
            {"post-1": "approved_manual"},
            {"days": [{"id": "post-1"}]},
            {"batch_complete": True, "posts": {}},
            {"post-1": {"instagram": {"id": "ig-media-1"}}},
        ]

        self.assertEqual(publish.main(), 0)

        publish_post.assert_not_called()
        save_json.assert_called_once()


if __name__ == "__main__":
    unittest.main()
