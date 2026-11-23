import json
import shutil
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))

import autopost  # noqa: E402
import build_kit  # noqa: E402

IST = timezone(timedelta(hours=5, minutes=30))
KIT = "p001-warm-modern-luxury"
UID = "1789"
COMMIT = "a" * 40


def t(s):
    return datetime.fromisoformat(s).replace(tzinfo=IST)


class FakeGraph:
    def __init__(self, recent=None, me=None, quota=(1, 50), fail_on=None):
        self.calls, self.uploads = [], []
        self.recent, self.quota, self.fail_on = recent or [], quota, fail_on
        self.me = me or {"user_id": UID, "username": "designinfra.interiors"}
        self.n = 0
        self.sleep = lambda s: None

    def call(self, method, path, params=None):
        params = params or {}
        self.calls.append((method, path, params))
        if self.fail_on and self.fail_on(method, path, params):
            raise autopost.Refused("IG_ERROR_9004/: media could not be fetched")
        if path == "me":
            return self.me
        if path.endswith("content_publishing_limit"):
            return {"data": [{"quota_usage": self.quota[0], "config": {"quota_total": self.quota[1]}}]}
        if method == "GET" and path == f"{UID}/media":
            return {"data": self.recent}
        if method == "POST" and path == f"{UID}/media":
            self.n += 1
            if params.get("media_type") == "REELS":
                return {"id": "reel1", "uri": "https://rupload.facebook.com/ig-api-upload/v25.0/reel1"}
            return {"id": f"c{self.n}"}
        if method == "POST" and path == f"{UID}/media_publish":
            return {"id": "m1"}
        if params.get("fields") == "status_code":
            return {"status_code": "FINISHED"}
        if params.get("fields") == "permalink":
            return {"permalink": "https://www.instagram.com/p/test/"}
        raise AssertionError(f"unexpected call {method} {path} {params}")

    def upload(self, uri, blob):
        self.uploads.append((uri, len(blob)))
        return {"success": True}

    def posts(self):
        return [c for c in self.calls if c[0] == "POST"]


class AutopostTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.base = tempfile.TemporaryDirectory()
        root = Path(cls.base.name) / "repo"
        for rel in ("campaigns/r11/first-post.jpg", f"r11/design_kit/kits/{KIT}.json",
                    "governance/publishing_target.json"):
            (root / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(REPO_ROOT / rel, root / rel)
        (root / autopost.SCHEDULE).write_text(json.dumps({"items": [   # fixed fixture, not the live schedule
            {"id": "p001-carousel", "kit": KIT, "format": "carousel", "at": "2026-11-22T19:00:00+05:30"},
            {"id": "p001-reel", "kit": KIT, "format": "reel", "at": "2026-11-24T19:00:00+05:30"}]}), encoding="utf-8")
        (root / autopost.STATE).write_text('{"items": {}}', encoding="utf-8")
        cls.secs = build_kit.SECS
        build_kit.SECS = 3.0          # short reel keeps the test fast; format checks still apply
        cls.first = autopost.prepare(root)
        cls.second = autopost.prepare(root)
        cls.template = root

    @classmethod
    def tearDownClass(cls):
        build_kit.SECS = cls.secs
        cls.base.cleanup()

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "repo"
        shutil.copytree(self.template, self.root)
        self.kit = self.root / autopost.KITS / KIT

    def tearDown(self):
        self.tmp.cleanup()

    def fetch(self, url):
        return (self.kit / url.rsplit("/", 1)[1]).read_bytes()

    def run_pub(self, g, now, dry=False, fetch=None):
        return autopost.publish(self.root, now, g, UID, "o/r", COMMIT, dry_run=dry, fetch=fetch or self.fetch)

    def state(self):
        return json.loads((self.root / autopost.STATE).read_text(encoding="utf-8"))["items"]

    def test_p1_prepare_builds_once(self):
        self.assertEqual(self.first[0]["action"], "built")
        self.assertTrue(self.first[0]["verdict"].startswith("READY"))
        self.assertEqual(self.second[0]["action"], "current")

    def test_p1b_old_review_is_redone_without_rebuild(self):
        review = self.kit / "review.json"
        old = json.loads(review.read_text(encoding="utf-8"))
        old.pop("reviewer_version")
        review.write_text(json.dumps(old), encoding="utf-8")
        before = (self.kit / "slide1.jpg").read_bytes()
        r = autopost.prepare(self.root)
        self.assertEqual(r[0]["action"], "re-reviewed")
        self.assertEqual((self.kit / "slide1.jpg").read_bytes(), before)
        self.assertEqual(autopost.prepare(self.root)[0]["action"], "current")

    def test_p2_nothing_due_before_time(self):
        g = FakeGraph()
        self.assertEqual(self.run_pub(g, t("2026-11-22T18:59:00"))["result"], "NOTHING_DUE")
        self.assertEqual(g.calls, [])

    def test_p3_carousel(self):
        g = FakeGraph()
        r = self.run_pub(g, t("2026-11-22T19:47:00"))
        self.assertEqual(r["result"], "PUBLISHED")
        posts = g.posts()
        kids = [p for p in posts if p[2].get("is_carousel_item") == "true"]
        self.assertEqual(len(kids), 5)
        self.assertEqual(kids[0][2]["image_url"],
                         f"https://raw.githubusercontent.com/o/r/{COMMIT}/campaigns/r11/kits/{KIT}/slide1.jpg")
        car = [p for p in posts if p[2].get("media_type") == "CAROUSEL"][0]
        self.assertEqual(car[2]["children"], "c1,c2,c3,c4,c5")
        self.assertEqual(car[2]["caption"], (self.kit / "caption.txt").read_text(encoding="utf-8").strip())
        self.assertEqual(posts[-1][1], f"{UID}/media_publish")
        st = self.state()["p001-carousel"]
        self.assertEqual((st["status"], st["media_id"], st["permalink"]),
                         ("PUBLISHED", "m1", "https://www.instagram.com/p/test/"))

    def test_p4_reel_after_gap(self):
        self.run_pub(FakeGraph(), t("2026-11-22T19:47:00"))
        g = FakeGraph()
        self.assertEqual(self.run_pub(g, t("2026-11-23T01:00:00"))["result"], "NOTHING_DUE")
        r = self.run_pub(g, t("2026-11-24T19:47:00"))
        self.assertEqual(r["result"], "PUBLISHED")
        create = [p for p in g.posts() if p[2].get("media_type") == "REELS"][0][2]
        self.assertEqual((create["upload_type"], create["share_to_feed"]), ("resumable", "true"))
        self.assertEqual(g.uploads, [("https://rupload.facebook.com/ig-api-upload/v25.0/reel1",
                                      (self.kit / "reel.mp4").stat().st_size)])
        self.assertEqual(self.state()["p001-reel"]["status"], "PUBLISHED")

    def test_p5_min_gap_between_posts(self):
        self.run_pub(FakeGraph(), t("2026-11-24T19:47:00"))   # both due; only one goes
        self.assertEqual(list(self.state()), ["p001-carousel"])
        self.assertEqual(self.run_pub(FakeGraph(), t("2026-11-24T20:47:00"))["result"], "MIN_GAP_SINCE_LAST_POST")

    def test_p6_dry_run_writes_nothing(self):
        g = FakeGraph()
        r = self.run_pub(g, t("2026-11-22T19:47:00"), dry=True)
        self.assertEqual((r["result"], len(r["would_post"])), ("DRY_RUN_OK", 5))
        self.assertEqual(g.posts(), [])
        self.assertEqual(self.state(), {})

    def test_p6b_preview_next_is_read_only(self):
        g = FakeGraph()
        r = autopost.publish(self.root, t("2026-11-21T23:00:00"), g, UID, "o/r", COMMIT, dry_run=True,
                             fetch=self.fetch, preview_next=True)
        self.assertEqual((r["result"], r["item"]), ("DRY_RUN_OK", "p001-carousel"))
        self.assertEqual(r["instagram"], {"account": "@designinfra.interiors", "account_id_matches": True,
                                          "publish_quota_24h": "1/50", "recent_posts_read": 0, "latest_post_at": None})
        self.assertEqual([c[1] for c in g.calls], ["me", f"{UID}/content_publishing_limit", f"{UID}/media"])
        self.assertEqual(self.state(), {})
        with self.assertRaisesRegex(autopost.Refused, "PREVIEW_NEXT_NEEDS_DRY_RUN"):
            autopost.publish(self.root, t("2026-11-21T23:00:00"), g, UID, "o/r", COMMIT, dry_run=False,
                             fetch=self.fetch, preview_next=True)

    def test_p7_duplicate_caption_is_not_reposted(self):
        cap = (self.kit / "caption.txt").read_text(encoding="utf-8").strip()
        g = FakeGraph(recent=[{"id": "old", "caption": cap, "media_type": "CAROUSEL_ALBUM",
                               "permalink": "https://www.instagram.com/p/old/", "timestamp": "2026-11-22T14:00:00+0000"}])
        self.assertEqual(self.run_pub(g, t("2026-11-22T20:47:00"))["result"], "ALREADY_ON_INSTAGRAM")
        self.assertEqual(g.posts(), [])
        st = self.state()["p001-carousel"]
        self.assertEqual((st["status"], st["media_id"], st["published_at"]), ("RECOVERED", "old", "2026-11-22T14:00:00Z"))

    def test_p8_wrong_account_or_quota(self):
        for g, code in ((FakeGraph(me={"user_id": "999", "username": "designinfra.interiors"}), "ACCOUNT_ID_MISMATCH"),
                        (FakeGraph(me={"user_id": UID, "username": "someone.else"}), "USERNAME_MISMATCH"),
                        (FakeGraph(quota=(50, 50)), "PUBLISHING_QUOTA_USED_UP")):
            with self.assertRaises(autopost.Refused) as ctx:
                self.run_pub(g, t("2026-11-22T19:47:00"))
            self.assertEqual(str(ctx.exception), code)
            self.assertEqual(g.posts(), [])

    def test_p9_kit_guards(self):
        review = self.kit / "review.json"
        good = review.read_text(encoding="utf-8")
        review.write_text(json.dumps({"verdict": "REJECTED_BY_VISION_REVIEW"}), encoding="utf-8")
        with self.assertRaisesRegex(autopost.Refused, "KIT_NOT_READY"):
            self.run_pub(FakeGraph(), t("2026-11-22T19:47:00"))
        review.write_text(good, encoding="utf-8")
        with self.assertRaisesRegex(autopost.Refused, "PUBLIC_URL_BYTES_DIFFER:slide1.jpg"):
            self.run_pub(FakeGraph(), t("2026-11-22T19:47:00"), fetch=lambda u: b"other")
        with open(self.kit / "slide2.jpg", "ab") as f:
            f.write(b"x")
        with self.assertRaisesRegex(autopost.Refused, "FILE_CHANGED:slide2.jpg"):
            self.run_pub(FakeGraph(), t("2026-11-22T19:47:00"))

    def test_p10_failures_retry_then_stop(self):
        bad = FakeGraph(fail_on=lambda m, p, q: m == "POST" and q.get("media_type") == "CAROUSEL")
        start = t("2026-11-22T19:47:00")
        for k in range(3):
            with self.assertRaises(autopost.Refused):
                self.run_pub(bad, start + timedelta(hours=k))
            self.assertEqual(self.state()["p001-carousel"]["attempts"], k + 1)
            self.assertEqual(self.run_pub(FakeGraph(), start + timedelta(hours=k, minutes=10))["result"], "NOTHING_DUE")
        self.assertEqual(self.run_pub(FakeGraph(), start + timedelta(hours=5))["result"], "NOTHING_DUE")
        self.assertIn("9004", self.state()["p001-carousel"]["error"])

    def test_p12_broken_kit_does_not_stop_prepare(self):
        sched = json.loads((self.root / autopost.SCHEDULE).read_text(encoding="utf-8"))
        sched["items"].append({"id": "x-carousel", "kit": "no-such-kit", "format": "carousel",
                               "at": "2026-11-23T19:00:00+05:30"})
        (self.root / autopost.SCHEDULE).write_text(json.dumps(sched), encoding="utf-8")
        r = {x["kit"]: x for x in autopost.prepare(self.root, now=t("2026-11-23T10:00:00"))}
        self.assertEqual(r["no-such-kit"]["action"], "failed")
        self.assertEqual(r[KIT]["action"], "current")

    def test_p11_token_redacted(self):
        self.assertEqual(autopost.Graph("SECRET123")._clean("bad token SECRET123 here"), "bad token [REDACTED] here")


if __name__ == "__main__":
    unittest.main()
