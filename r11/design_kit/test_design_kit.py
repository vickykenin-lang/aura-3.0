import copy
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))

import build_kit  # noqa: E402
import review_kit  # noqa: E402

SPEC = HERE / "kits" / "p001-warm-modern-luxury.json"


def write_spec(tmp, mutate=None):
    spec = json.loads(SPEC.read_text(encoding="utf-8"))
    if mutate:
        mutate(spec)
    p = Path(tmp) / "spec.json"
    p.write_text(json.dumps(spec, ensure_ascii=False), encoding="utf-8")
    return p


class BuildTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.out = Path(cls.tmp.name) / "kit"
        cls.manifest = build_kit.build(ROOT, SPEC, cls.out, with_reel=bool(os.environ.get("RUN_REEL")))

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_b1_outputs(self):
        names = [o["file"] for o in self.manifest["outputs"]]
        self.assertEqual(names[:5], [f"slide{i}.jpg" for i in range(1, 6)])
        self.assertIn("caption.txt", names)
        self.assertFalse(self.manifest["publishing"])

    def test_b2_deterministic_review_passes(self):
        r = review_kit.review(self.out, SPEC)
        self.assertEqual(r["deterministic_issues"], [])
        self.assertEqual(r["verdict"], "READY_CODE_CHECKED")

    def test_b3_split_sums_to_100(self):
        self.assertEqual(sum(p["pct"] for p in self.manifest["colour_split"]), 100)

    def test_b4_nova_pass_and_fail(self):
        good = {"pass": True, "quality_score": 8, "spelling_errors": [], "text_readable": True,
                "same_room_across_slides": True, "whatsapp_number_seen": "+91 82879 00789", "issues": []}
        r = review_kit.review(self.out, SPEC, True, converse=lambda m: "```json\n" + json.dumps(good) + "\n```")
        self.assertEqual(r["verdict"], "READY_VISION_CHECKED")
        for bad in ({"spelling_errors": ["Warrm"]}, {"whatsapp_number_seen": "+91 82879 00780"},
                    {"quality_score": 6}, {"text_readable": False}):
            r = review_kit.review(self.out, SPEC, True, converse=lambda m, b=bad: json.dumps({**good, **b}))
            self.assertEqual(r["verdict"], "REJECTED_BY_VISION_REVIEW", bad)
        r = review_kit.review(self.out, SPEC, True, converse=lambda m: "sorry")
        self.assertEqual(r["verdict"], "REJECTED_BY_VISION_REVIEW")

    def test_b4b_nova_unavailable(self):
        class Denied(Exception):
            response = {"Error": {"Code": "UnrecognizedClientException"}}

        def boom(msgs):
            raise Denied("bad token")
        r = review_kit.review(self.out, SPEC, True, converse=boom)
        self.assertEqual(r["verdict"], "READY_CODE_CHECKED")
        self.assertEqual(r["vision"]["issues"], ["NOVA_UNAVAILABLE:UnrecognizedClientException"])

    def test_b5_nova_gets_five_images(self):
        seen = {}

        def fake(msgs):
            seen["n"] = sum(1 for c in msgs[0]["content"] if "image" in c)
            return "{}"
        review_kit.review(self.out, SPEC, True, converse=fake)
        self.assertEqual(seen["n"], 5)

    def test_b7_ocr_reads_back_every_line(self):
        r = review_kit.review(self.out, SPEC)
        self.assertEqual(sum(v["checked"] for v in r["ocr"].values()), 40)
        self.assertTrue(all(v["missing"] == [] for v in r["ocr"].values()))
        real = {i: review_kit.ocr_text(self.out / f"slide{i}.jpg") for i in range(1, 6)}

        def wrong(path):   # slide 5 printed with a different phone number, slide 2 lost a line
            text = real[int(path.stem[-1])]
            return text.replace("82879", "82897").replace("Clear walking path", "") if path.stem in ("slide5", "slide2") else text
        r = review_kit.review(self.out, SPEC, reader=wrong)
        self.assertEqual(r["verdict"], "REJECTED")
        self.assertIn("OCR_PHONE_NOT_ON_SLIDE5", r["deterministic_issues"])
        self.assertTrue(any(i.startswith("OCR_TEXT_MISSING:slide2:Clear walking path") for i in r["deterministic_issues"]))

        def missing(path):
            raise OSError("tesseract not installed")
        r = review_kit.review(self.out, SPEC, reader=missing)
        self.assertEqual((r["verdict"], r["deterministic_issues"]), ("REJECTED", ["OCR_UNAVAILABLE"]))

    @unittest.skipUnless(os.environ.get("RUN_REEL"), "set RUN_REEL=1 to render the 8 s reel")
    def test_b6_reel_format(self):
        self.assertEqual(review_kit.check_reel(self.out / "reel.mp4"), [])


class GuardTests(unittest.TestCase):
    def build(self, mutate):
        with tempfile.TemporaryDirectory() as tmp:
            build_kit.build(ROOT, write_spec(tmp, mutate), Path(tmp) / "kit", with_reel=False)

    def assertKitError(self, mutate, code):
        with self.assertRaises(build_kit.KitError) as ctx:
            self.build(mutate)
        self.assertTrue(str(ctx.exception).startswith(code), str(ctx.exception))

    def test_g1_source_hash(self):
        self.assertKitError(lambda s: s["source"].update(sha256="0" * 64), "SOURCE_SHA256_MISMATCH")

    def test_g2_box_outside_image(self):
        self.assertKitError(lambda s: s["details"]["items"][0].update(box=[0, 0, 5000, 100]), "BOX_OUTSIDE_IMAGE")

    def test_g3_title_overflow(self):
        self.assertKitError(lambda s: s["plan"].update(title="word " * 40), "TEXT_OVERFLOW")

    def test_g4_split_not_100(self):
        self.assertKitError(lambda s: s["materials"]["split"][0].update(pct=50), "SPLIT_NOT_100")

    def test_g5_legend_too_long(self):
        self.assertKitError(lambda s: s["plan"]["markers"][0].update(text="A very long legend line " * 3),
                            "LEGEND_TOO_LONG")


class ReviewGuardTests(unittest.TestCase):
    def test_r1_tamper_and_caption(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "kit"
            build_kit.build(ROOT, SPEC, out, with_reel=False)
            with open(out / "slide3.jpg", "ab") as f:
                f.write(b"x")
            (out / "caption.txt").write_text("No phone here #a", encoding="utf-8")
            r = review_kit.review(out, SPEC)
            self.assertEqual(r["verdict"], "REJECTED")
            for code in ("SHA_MISMATCH:slide3.jpg", "CAPTION_MISSING_WHATSAPP:caption.txt",
                         "CAPTION_MISSING_DISCLOSURE:caption.txt"):
                self.assertIn(code, r["deterministic_issues"])

    def test_r2_hashtag_limit(self):
        spec = json.loads(SPEC.read_text(encoding="utf-8"))
        cap = spec["caption"] + " " + " ".join(f"#t{i}" for i in range(30))
        self.assertIn("TOO_MANY_HASHTAGS", review_kit.check_caption(cap, spec))


if __name__ == "__main__":
    unittest.main()
