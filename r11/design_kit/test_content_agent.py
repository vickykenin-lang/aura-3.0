import io
import json
import re
import shutil
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))

import build_kit  # noqa: E402
import content_agent as ca  # noqa: E402
import review_kit  # noqa: E402
from PIL import Image  # noqa: E402

IST = ca.IST
BRIEF = {"title": "Calm Japandi living", "subtitle": "Oak, linen and soft light for a restful family room",
         "scene": "A Japandi living room with a low oak sofa, linen cushions, a round jute rug, a slatted oak TV wall, "
                  "paper pendant light, large window with sheer curtains, warm beige walls and a few ceramic vases.",
         "fix_title": "Clutter-free living room", "problem": "Living room mein saman bikhra rehta hai aur jagah choti lagti hai",
         "solutions": ["Closed oak storage hides daily clutter", "Low furniture keeps sightlines open",
                       "One rug zones the seating clearly"],
         "reel_line": "Oak · linen · jute", "caption_body": "Japandi look: natural oak, linen aur soft light. Tip: "
         "TV wall mein closed storage rakhein taaki living room hamesha neat dikhe.",
         "hashtags": ["JapandiInterior", "LivingRoomDesign", "bad tag!"]}


class FakeStudio:
    def __init__(self, brief=None, qa=None, image_fail=0, design_fail=0):
        self.brief, self.qa, self.calls = brief or BRIEF, qa, []
        self.design_fail = design_fail
        self.image_fail = image_fail
        src = Image.open(REPO_ROOT / "campaigns/r11/first-post.jpg").convert("RGB")
        buf = io.BytesIO()
        build_kit.cover(src, (1024, 1280)).save(buf, "JPEG", quality=92)
        self.img = buf.getvalue()

    def text(self, messages, schema=None, max_tokens=900):
        self.calls.append("text")
        return json.dumps(self.brief)

    def image(self, prompt, width=1024, height=1280):
        self.calls.append("image")
        self.last_prompt = prompt
        return self.img

    def vision(self, prompt, images, schema=None, max_tokens=500):
        self.calls.append("vision")
        if "designer checklist" in prompt:
            n = len(re.findall(r"(?m)^\d+\. ", prompt))
            checks = [True] * n
            if self.design_fail > 0:
                self.design_fail -= 1
                checks[0] = False
            return json.dumps({"checks": checks})
        if "quality checker" in prompt:
            if self.image_fail > 0:
                self.image_fail -= 1
                return json.dumps({"photorealistic": True, "matches_room": True, "distorted_or_broken_objects": True,
                                   "people_present": False, "text_or_logos": False, "premium_designer_look": True,
                                   "quality": 8})
            return json.dumps(self.qa or {"photorealistic": True, "matches_room": True, "distorted_or_broken_objects": False,
                                          "people_present": False, "text_or_logos": False, "premium_designer_look": True,
                                          "quality": 8})
        if "close crop" in prompt:
            n = self.calls.count("vision")
            names = ["Fluted oak shutters", "Brass pendant light", "Jute area rug", "Linen sofa cushions",
                     "Marble side table", "Cane console doors", "Sheer linen drapes", "Terrazzo floor inlay"]
            return json.dumps({"clear_design_detail": True, "title": names[n % len(names)],
                               "why": "Adds warmth and keeps the room easy to maintain every day."})
        mats = ["Linen fabric", "Oak wood", "Matte plaster", "Jute", "Sheer curtain", "Marble"]
        return json.dumps({"swatches": [{"letter": "ABCDEF"[i], "material": m, "use": "Wall", "confident": True}
                                        for i, m in enumerate(mats)]})


class ContentAgentTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "repo"
        rel = "governance/publishing_target.json"
        (self.root / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(REPO_ROOT / rel, self.root / rel)
        ca.save(self.root / ca.SCHEDULE, {"items": [   # fixed fixture, independent of the live schedule
            {"id": "p001-carousel", "kit": "p001-warm-modern-luxury", "format": "carousel", "at": "2026-11-22T19:00:00+05:30"},
            {"id": "p001-reel", "kit": "p001-warm-modern-luxury", "format": "reel", "at": "2026-11-24T19:00:00+05:30"}]})

    def tearDown(self):
        self.tmp.cleanup()

    def sched(self):
        return json.loads((self.root / ca.SCHEDULE).read_text(encoding="utf-8"))["items"]

    def test_c1_missing_days_respects_taken_slots(self):
        now = datetime(2026, 11, 23, 10, 30, tzinfo=IST)
        days = ca.missing_days(json.loads((self.root / ca.SCHEDULE).read_text()), now)
        self.assertEqual([(str(d), s) for d, s in days],
                         [("2026-11-23", ["pm"]), ("2026-11-24", ["am"]), ("2026-11-25", ["am", "pm"])])

    def test_c2_full_concept_builds_and_passes_review(self):
        now = datetime(2026, 11, 23, 10, 30, tzinfo=IST)
        out = ca.run(self.root, FakeStudio(), now, ca.render_check)
        self.assertEqual(out["created"], ["auto-20261123"])
        spec_path = self.root / ca.SPECS / "auto-20261123.json"
        spec = json.loads(spec_path.read_text(encoding="utf-8"))
        self.assertEqual(spec["template"], "auto_v1")
        self.assertIn("+91 82879 00789", spec["caption"])
        self.assertIn("AI-generated design concept for inspiration.", spec["caption"])
        self.assertIn("#JapandiInterior", spec["caption"])
        tags = spec["caption"].rsplit("\n\n", 1)[1].split()
        self.assertTrue(all(__import__("re").fullmatch(r"#[A-Za-z0-9]+", x) for x in tags), tags)
        self.assertLessEqual(len(tags), 7)
        self.assertEqual(sum(p["pct"] for p in spec["materials"]["split"]), 100)
        self.assertEqual(len(spec["details"]["items"]), 3)
        # today only the 19:00 slot is free -> a lone carousel
        items = [i for i in self.sched() if i["kit"] == "auto-20261123"]
        self.assertEqual([(i["format"], i["at"]) for i in items], [("carousel", "2026-11-23T19:00:00+05:30")])
        out_dir = Path(self.tmp.name) / "kit"
        build_kit.build(self.root, spec_path, out_dir, with_reel=False)
        r = review_kit.review(out_dir, spec_path)
        self.assertEqual(r["deterministic_issues"], [], r["ocr"])
        self.assertEqual(r["verdict"], "READY_CODE_CHECKED")

    def test_c3_two_slots_reel_morning_carousel_evening(self):
        now = datetime(2026, 11, 25, 3, 0, tzinfo=IST)
        ca.run(self.root, FakeStudio(), now, ca.render_check)
        items = [(i["format"], i["at"]) for i in self.sched() if i["kit"] == "auto-20261125"]
        self.assertEqual(items, [("reel", "2026-11-25T07:00:00+05:30"), ("carousel", "2026-11-25T19:00:00+05:30")])
        self.assertEqual(ca.run(self.root, FakeStudio(), now, ca.render_check)["created"], ["auto-20261126"])

    def test_c4_bad_brief_retried_then_logged(self):
        bad = dict(BRIEF, problem="Sirf ₹2 lakh mein poora living room! " * 2)
        st = FakeStudio(brief=bad)
        out = ca.run(self.root, st, datetime(2026, 11, 23, 10, 30, tzinfo=IST), ca.render_check)
        self.assertEqual(out["created"], [])
        self.assertIn("BRIEF_INVALID", out["last_event"]["error"])
        self.assertEqual(st.calls.count("text"), 3)
        self.assertEqual([i for i in self.sched() if i["kit"].startswith("auto")], [])

    def test_c5_image_rejected_then_accepted(self):
        st = FakeStudio(image_fail=2)
        out = ca.run(self.root, st, datetime(2026, 11, 23, 10, 30, tzinfo=IST), ca.render_check)
        self.assertEqual(out["created"], ["auto-20261123"])
        self.assertEqual(st.calls.count("image"), 3)
        log = json.loads((self.root / ca.LOG).read_text())
        self.assertEqual([a["ok"] for a in log["concepts"]["auto-20261123"]["image_attempts"]], [False, False, True])

    def test_c6_image_rejected_three_times_writes_nothing(self):
        st = FakeStudio(image_fail=3)
        out = ca.run(self.root, st, datetime(2026, 11, 23, 10, 30, tzinfo=IST), ca.render_check)
        self.assertEqual(out["created"], [])
        self.assertIn("IMAGE_REJECTED", out["last_event"]["error"])
        self.assertFalse((self.root / ca.SPECS / "auto-20261123.json").exists())

    def test_c6b_draft_reused_after_late_failure(self):
        class Flaky(FakeStudio):
            def __init__(self):
                super().__init__()
                self.crop_calls = 0

            def vision(self, prompt, images, schema=None, max_tokens=500):
                if "close crop" in prompt:
                    self.crop_calls += 1
                    if self.crop_calls <= 6:          # first run: no usable detail at all
                        return '{"clear_design_detail": \t\t\n'
                return super().vision(prompt, images, schema, max_tokens)
        st = Flaky()
        now = datetime(2026, 11, 23, 10, 30, tzinfo=IST)
        out = ca.run(self.root, st, now, ca.render_check)
        self.assertIn("DETAILS_NOT_ENOUGH", out["last_event"]["error"])
        self.assertTrue((self.root / ca.DRAFTS / "auto-20261123.json").exists())
        self.assertTrue((self.root / ca.CONCEPTS / "auto-20261123.jpg").exists())
        out = ca.run(self.root, st, now, ca.render_check)
        self.assertEqual(out["created"], ["auto-20261123"])
        self.assertEqual((st.calls.count("text"), st.calls.count("image")), (1, 1))   # brief + image reused
        self.assertFalse((self.root / ca.DRAFTS / "auto-20261123.json").exists())

    def test_c6c_plain_room_rejected(self):
        plain = {"photorealistic": True, "matches_room": True, "distorted_or_broken_objects": False,
                 "people_present": False, "text_or_logos": False, "premium_designer_look": False, "quality": 9}
        out = ca.run(self.root, FakeStudio(qa=plain), datetime(2026, 11, 23, 10, 30, tzinfo=IST), ca.render_check)
        self.assertIn("IMAGE_REJECTED", out["last_event"]["error"])

    def test_c6e_design_checklist_gate(self):
        st = FakeStudio(design_fail=3)
        out = ca.run(self.root, st, datetime(2026, 11, 23, 10, 30, tzinfo=IST), ca.render_check)
        self.assertIn("IMAGE_REJECTED", out["last_event"]["error"])
        log = json.loads((self.root / ca.LOG).read_text())
        self.assertTrue(all(e.get("result") != "created" for e in log["events"]))
        st = FakeStudio(design_fail=1)
        out = ca.run(self.root, st, datetime(2026, 11, 23, 10, 30, tzinfo=IST), ca.render_check)
        self.assertEqual(out["created"], ["auto-20261123"])
        attempts = json.loads((self.root / ca.LOG).read_text())["concepts"]["auto-20261123"]["image_attempts"]
        self.assertTrue(attempts[0]["why"].startswith("DESIGN_RULES_FAILED:Shows "))
        self.assertTrue(attempts[1]["ok"])

    def test_c6f_every_room_has_rules(self):
        self.assertEqual(set(ca.DESIGN_RULES), {label for _, label in ca.ROOMS})
        kids = ca.checklist("Kids room")
        self.assertIn("Shows a bed for the child (single, bunk or day bed)", kids)
        self.assertIn("Does NOT show a crystal or glass chandelier", kids)

    def test_c6g_gap_filled_with_unposted_format(self):
        sched = json.loads((self.root / ca.SCHEDULE).read_text())
        sched["items"].append({"id": "20261124-am-carousel", "kit": "auto-20261124", "format": "carousel",
                               "at": "2026-11-24T07:00:00+05:30"})
        ca.save(self.root / ca.SCHEDULE, sched)
        ca.save(self.root / ca.SPECS / "auto-20261124.json", {"kit_id": "r11-kit-auto-20261124"})
        quota = FakeStudio()
        quota.text = lambda *a, **k: (_ for _ in ()).throw(ca.AgentError("STUDIO_502:ai_error:4006 quota"))
        # 19:00 slot is 11 h away: too early to fill, the agent keeps trying for a new concept
        out = ca.run(self.root, quota, datetime(2026, 11, 25, 8, 0, tzinfo=IST), ca.render_check)
        self.assertEqual(out["filled"], [])
        # 5 h before the slot and still no concept: the unposted reel of 24 Nov fills it
        out = ca.run(self.root, quota, datetime(2026, 11, 25, 14, 0, tzinfo=IST), ca.render_check)
        self.assertEqual(out["filled"], ["20261125-pm-reel-filler"])
        item = [i for i in self.sched() if i["id"] == "20261125-pm-reel-filler"][0]
        self.assertEqual((item["kit"], item["format"], item["at"]), ("auto-20261124", "reel", "2026-11-25T19:00:00+05:30"))
        # nothing left to reuse from that kit: next gap stays empty rather than repeating a post
        out = ca.run(self.root, quota, datetime(2026, 11, 26, 2, 0, tzinfo=IST), ca.render_check)
        self.assertEqual(out["filled"], [])

    def test_c6h_theme_drives_prompt_checklist_and_eyebrow(self):
        st = FakeStudio()
        now = datetime(2026, 11, 23, 10, 30, tzinfo=IST)
        room, label, style = ca.topic_for(now.date())
        ca.run(self.root, st, now, ca.render_check)
        self.assertIn(ca.STYLE_GUIDE[style], st.last_prompt)
        self.assertNotIn("warm cove lighting", st.last_prompt)
        self.assertTrue(st.last_prompt.index(ca.DESIGN_RULES[label]["must"][0]) < st.last_prompt.index("Style:"))
        spec = json.loads((self.root / ca.SPECS / "auto-20261123.json").read_text())
        self.assertEqual(spec["hero"]["eyebrow"], f"{style.upper()} · {label.upper()}")
        self.assertTrue(ca.checklist(label, style)[-1].startswith(f"Clearly looks {style} in style"))
        self.assertEqual(set(ca.STYLES), {"Vibrant", "Modern luxury", "Contemporary", "Minimalist", "High-end",
                                          "Heritage classic", "Warm modern"})

    def test_c7_brief_rules(self):
        self.assertEqual(ca.check_brief(BRIEF), [])
        for field, value in (("title", "x" * 27), ("caption_body", "Visit www.example.com"),
                             ("problem", "Only 50% cost"), ("solutions", ["a", "b"])):
            self.assertTrue(ca.check_brief(dict(BRIEF, **{field: value})), field)

    def test_c7b_near_duplicate_details_dropped(self):
        self.assertTrue(ca._same_detail("Fluted panel wardrobe", "Fluted wardrobe panels"))
        self.assertFalse(ca._same_detail("Ornate floral patterned rug", "Fluted panel wardrobe"))
        self.assertFalse(ca._same_detail("Cove light + backlit wall panel", "Walnut slats + long low console"))

    def test_c8_topic_rotation_has_no_repeat_within_12_days(self):
        start = datetime(2026, 11, 23).date()
        topics = [ca.topic_for(start + timedelta(days=k))[:2] for k in range(12)]
        self.assertEqual(len({t[0] for t in topics}), 12)


if __name__ == "__main__":
    unittest.main()
