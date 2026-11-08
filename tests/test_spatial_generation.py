import copy
import hashlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import generate_spatial_views as spatial


class FakeRunway:
    def __init__(self, image):
        self.image, self.creates, self.preflights = image, [], 0
        self.enough, self.uncertain, self.pending = True, False, False

    def preflight(self, credits):
        self.preflights += 1
        if not self.enough:
            raise spatial.SafeFailure("INSUFFICIENT_OR_UNVERIFIED_RUNWAY_CREDITS")
        return {"credits_sufficient": True, "estimated_credits_for_unsubmitted_views": credits}

    def create(self, payload):
        self.creates.append(payload)
        if self.uncertain:
            raise spatial.SafeFailure("RUNWAY_RESPONSE_UNCONFIRMED")
        return "offline-task-" + str(len(self.creates))

    def task(self, task):
        if self.pending:
            return {"status": "RUNNING"}
        return {"status": "SUCCEEDED", "output": ["https://offline.cloudfront.net/signed-private-value"]}

    def download(self, url):
        return self.image


class SpatialGenerationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        image = io.BytesIO()
        Image.new("RGB", (1254, 1254), "#eadbcb").save(image, format="JPEG")
        self.image = image.getvalue()
        p = self.root / "campaigns/source.jpg"
        p.parent.mkdir(parents=True)
        p.write_bytes(self.image)
        self.request = {"job_id": "offline-layout-pilot", "execute": True,
                        "source_path": "campaigns/source.jpg",
                        "source_sha256": hashlib.sha256(self.image).hexdigest(),
                        "model": "seedream5_pro", "ratio": "2048:2048",
                        "max_image_tasks": 2, "max_runway_credits": 18,
                        "max_nova_calls": 3, "automatic_generation_retries": 0,
                        "publishing": False,
                        "anchors": {"sofa": "left", "TV": "right", "dining": "rear"}}
        self.api = FakeRunway(self.image)
        self.nova_count = 0
        self.qa_ok = True
        self.saved = []

    def nova(self, content):
        self.nova_count += 1
        if self.nova_count == 1:
            return {"observed_arrangement": "Sofa left, TV right, dining rear.",
                    "materials": ["timber"], "uncertain_features": ["room dimensions"]}
        return {"pass": self.qa_ok, "quality_score": 9, "same_room": True,
                "correct_view": True, "furniture_consistency": True,
                "orientation_consistent": True, "no_extra_rooms": True,
                "no_text_or_dimensions": True, "issues": []}

    def persist(self):
        self.saved.append(json.loads((self.root / "data/spatial_jobs.json").read_text()))

    def pilot(self, persist=None):
        return spatial.Pilot(self.root, self.api, self.nova, persist or self.persist,
                             sleep=lambda seconds: None)

    def test_two_outputs_and_repeat_is_pure_noop(self):
        result = self.pilot().run(self.request)
        self.assertEqual(result["status"], "READY_FOR_REVIEW")
        self.assertEqual(len(self.api.creates), 2)
        self.assertEqual(self.nova_count, 3)
        self.assertEqual(result["estimated_reserved_runway_credits"], 18)
        for payload in self.api.creates:
            self.assertEqual(payload["outputCount"], 1)
            self.assertEqual(payload["referenceImages"][0]["uri"],
                             "data:image/jpeg;base64," + spatial.base64.b64encode(self.image).decode())
        self.assertNotIn("signed-private-value", json.dumps(self.saved))
        calls = self.api.preflights
        self.pilot().run(self.request)
        self.assertEqual((len(self.api.creates), self.nova_count, self.api.preflights), (2, 3, calls))

    def test_insufficient_credit_blocks_all_inference_then_same_job_can_resume(self):
        self.api.enough = False
        result = self.pilot().run(self.request)
        self.assertEqual(result["status"], "BLOCKED")
        self.assertEqual((len(self.api.creates), self.nova_count), (0, 0))
        self.api.enough = True
        self.assertEqual(self.pilot().run(self.request)["status"], "READY_FOR_REVIEW")
        self.assertEqual((len(self.api.creates), self.nova_count), (2, 3))

    def test_uncertain_billable_submission_is_never_repeated(self):
        self.api.uncertain = True
        result = self.pilot().run(self.request)
        self.assertEqual(result["status"], "BLOCKED")
        self.assertEqual(result["views"]["layout"]["state"], "SUBMISSION_UNCONFIRMED")
        self.pilot().run(self.request)
        self.assertEqual(len(self.api.creates), 1)

    def test_durable_intent_failure_prevents_image_submission(self):
        def failing_intent():
            self.persist()
            job = self.saved[-1]["jobs"][self.request["job_id"]]
            if any(v["state"] == "SUBMITTING" for v in job["views"].values()):
                raise spatial.PersistenceFailure("DURABLE_STATE_PERSISTENCE_FAILED")
        with self.assertRaises(spatial.PersistenceFailure):
            self.pilot(failing_intent).run(self.request)
        self.assertEqual(len(self.api.creates), 0)

    def test_failed_quality_check_keeps_outputs_without_regeneration(self):
        self.qa_ok = False
        result = self.pilot().run(self.request)
        self.assertEqual(result["status"], "NEEDS_REVIEW")
        self.assertEqual(len(self.api.creates), 2)
        self.assertTrue(all(v["state"] == "QA_REJECTED" for v in result["views"].values()))
        self.pilot().run(self.request)
        self.assertEqual(len(self.api.creates), 2)

    def test_pending_provider_task_resumes_by_task_id(self):
        self.api.pending = True
        with mock.patch.object(spatial, "MAX_POLLS", 1):
            result = self.pilot().run(self.request)
        self.assertEqual(result["status"], "WAITING_FOR_PROVIDER")
        self.assertEqual(len(self.api.creates), 1)
        self.api.pending = False
        self.assertEqual(self.pilot().run(self.request)["status"], "READY_FOR_REVIEW")
        self.assertEqual((len(self.api.creates), self.nova_count), (2, 3))

    def test_changed_source_or_request_cannot_reuse_job(self):
        self.pilot().run(self.request)
        modified = copy.deepcopy(self.request)
        modified["anchors"]["sofa"] = "right"
        with self.assertRaisesRegex(spatial.SafeFailure, "JOB_ID_BOUND"):
            self.pilot().run(modified)
        (self.root / "campaigns/source.jpg").write_bytes(b"changed")
        with self.assertRaises(spatial.SafeFailure):
            self.pilot().run(self.request)
        self.assertEqual(len(self.api.creates), 2)

    def test_unapproved_budget_and_model_are_blocked(self):
        for key, value in [("max_image_tasks", 3), ("max_runway_credits", 19),
                           ("max_nova_calls", 2), ("automatic_generation_retries", 1),
                           ("publishing", True), ("model", "arbitrary-model"), ("ratio", "auto")]:
            with self.subTest(key=key), self.assertRaises(spatial.SafeFailure):
                self.pilot().run(dict(self.request, **{key: value}))
        self.assertEqual((self.api.preflights, len(self.api.creates), self.nova_count), (0, 0, 0))

    def test_unknown_running_qa_is_not_repeated(self):
        job = self.pilot().run(self.request)
        state = spatial.read_json(self.root / "data/spatial_jobs.json")
        state["jobs"][self.request["job_id"]]["status"] = "GENERATED"
        state["jobs"][self.request["job_id"]]["views"]["layout"]["state"] = "QA_RUNNING"
        spatial.write_json(self.root / "data/spatial_jobs.json", state)
        self.assertEqual(self.pilot().run(self.request)["status"], "BLOCKED")
        self.assertEqual((len(self.api.creates), self.nova_count), (2, 3))


if __name__ == "__main__":
    unittest.main()
