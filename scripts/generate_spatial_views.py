#!/usr/bin/env python3
"""A bounded, resumable reference-image pilot. No social publishing operations."""
from __future__ import annotations
import base64
from datetime import datetime, timezone
import hashlib
import io
import json
import os
from pathlib import Path
import re
import subprocess
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
MODEL = "seedream5_pro"
CREDITS_PER_IMAGE = 9
VIEWS = ("layout", "birdview")
MAX_NOVA_CALLS = 3
MAX_POLLS = 30
POLL_SECONDS = 10


class SafeFailure(RuntimeError):
    pass


class PersistenceFailure(SafeFailure):
    pass


def now():
    return datetime.now(timezone.utc).isoformat()


def read_json(path, default=None):
    if not path.exists():
        return default
    try:
        value = json.loads(path.read_text())
    except (OSError, ValueError):
        raise SafeFailure("INVALID_JSON_STATE") from None
    if not isinstance(value, dict):
        raise SafeFailure("INVALID_STATE_OBJECT")
    return value


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
    tmp.replace(path)


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def image_proof(data):
    try:
        with Image.open(io.BytesIO(data)) as image:
            image.verify()
        with Image.open(io.BytesIO(data)) as image:
            width, height, fmt = image.width, image.height, image.format
    except (OSError, ValueError):
        raise SafeFailure("INVALID_IMAGE") from None
    if fmt not in {"JPEG", "PNG"} or width < 1200 or height < 800:
        raise SafeFailure("IMAGE_FORMAT_OR_RESOLUTION")
    return {"sha256": hashlib.sha256(data).hexdigest(), "width": width, "height": height,
            "format": fmt, "mime": "image/jpeg" if fmt == "JPEG" else "image/png"}


class Runway:
    def __init__(self):
        self.secret = os.getenv("RUNWAYML_API_SECRET", "").strip()

    def request(self, path, payload=None):
        if not self.secret:
            raise SafeFailure("MISSING_RUNWAY_CREDENTIAL")
        request = Request("https://api.dev.runwayml.com/v1/" + path,
                          headers={"Authorization": "Bearer " + self.secret,
                                   "Content-Type": "application/json",
                                   "X-Runway-Version": "2024-11-06"},
                          data=None if payload is None else json.dumps(payload).encode(),
                          method="GET" if payload is None else "POST")
        try:
            with urlopen(request, timeout=90) as response:
                result = json.loads(response.read())
            if not isinstance(result, dict):
                raise SafeFailure("RUNWAY_INVALID_RESPONSE")
            return result
        except HTTPError as exc:
            raise SafeFailure("RUNWAY_HTTP_" + str(exc.code)) from None
        except (URLError, TimeoutError, ValueError):
            raise SafeFailure("RUNWAY_RESPONSE_UNCONFIRMED") from None

    def preflight(self, credits):
        data = self.request("organization")
        balance = data.get("creditBalance")
        if not isinstance(balance, (int, float)) or balance < credits:
            raise SafeFailure("INSUFFICIENT_OR_UNVERIFIED_RUNWAY_CREDITS")
        return {"account_access_verified": True, "credits_sufficient": True,
                "estimated_credits_for_unsubmitted_views": credits,
                "generation_access_verified": False}

    def create(self, payload):
        data = self.request("text_to_image", payload)
        task = str(data.get("id", ""))
        if not re.fullmatch(r"[A-Za-z0-9-]{8,100}", task):
            raise SafeFailure("RUNWAY_SUBMISSION_UNCONFIRMED")
        return task

    def task(self, task):
        if not re.fullmatch(r"[A-Za-z0-9-]{8,100}", task):
            raise SafeFailure("INVALID_TASK_ID")
        return self.request("tasks/" + task)

    def download(self, url):
        parsed = urlsplit(str(url))
        host = parsed.hostname or ""
        allowed = any(host == domain or host.endswith("." + domain)
                      for domain in ["cloudfront.net", "runwayml.com", "runway.com"])
        if parsed.scheme != "https" or parsed.username or parsed.password or not allowed:
            raise SafeFailure("UNTRUSTED_OUTPUT_URL")
        try:
            with urlopen(Request(url, headers={"User-Agent": "AURA3-Spatial/1.0"}), timeout=60) as response:
                data = response.read(16 * 1024 * 1024 + 1)
        except Exception:
            raise SafeFailure("OUTPUT_DOWNLOAD_FAILED") from None
        if not data or len(data) > 16 * 1024 * 1024:
            raise SafeFailure("OUTPUT_SIZE_INVALID")
        return data


def prompt_for(view, brief, anchors):
    shared = (
        "Reconstruct the SAME warm modern luxury living-dining room in the single reference image. "
        "Retain the furniture design, materials, cream/ivory/walnut palette and relative positions. "
        "This is an inferred concept, not a measured plan. "
        "Do not invent additional rooms, a full apartment, extra windows, or a sofa sectional extension. "
        "Keep circulation plausible. NO text, logos, watermarks, dimensions, numbers, BHK labels or "
        "numbered style labels. Furniture anchors: " + json.dumps(anchors, ensure_ascii=False) + ". "
        "Image analysis context (uncertain features are not measurements): " +
        json.dumps(brief, ensure_ascii=False)[:1200] + ". ")
    if view == "layout":
        return shared + (
            "Deliver a strict vertical overhead 2D architectural furniture plan. Flat orthographic "
            "top view, fine charcoal wall and furniture outlines, pale material fills, restrained "
            "soft shadows on ivory background. Show the observed rear glazing at TOP, sofa LEFT, "
            "TV console RIGHT, lounge chair LOWER RIGHT and dining toward TOP. Front edge open "
            "because the unseen entrance boundary is unknown. Remove ceiling and pendant occlusion.")
    if view == "birdview":
        return shared + (
            "Deliver a photorealistic 3D bird's-eye dollhouse cutaway. Camera above the open FRONT "
            "looking down toward the rear window at 60 degrees. Remove ceiling and front wall, "
            "keep low side walls. Show the entire original living-dining arrangement. Warm daylight, "
            "premium realistic finishes, plain off-white surroundings. Keep dining and seating clear.")
    raise SafeFailure("INVALID_VIEW")


def qualifies(qa):
    keys = ["pass", "same_room", "correct_view", "furniture_consistency",
            "orientation_consistent", "no_extra_rooms", "no_text_or_dimensions"]
    score = qa.get("quality_score")
    return (all(qa.get(key) is True for key in keys)
            and isinstance(score, (int, float)) and 7 <= score <= 10)


class Pilot:
    def __init__(self, root, runway, nova, persist, sleep=time.sleep):
        self.root, self.runway, self.nova = Path(root), runway, nova
        self.persist, self.sleep = persist, sleep
        self.path = self.root / "data/spatial_jobs.json"
        self.state = read_json(self.path, {"schema_version": 1, "jobs": {}})

    def save(self):
        self.job["updated_at"] = now()
        write_json(self.path, self.state)
        self.persist()

    def nova_call(self, content):
        if self.job["nova_calls"] >= MAX_NOVA_CALLS:
            raise SafeFailure("NOVA_CALL_BUDGET_EXHAUSTED")
        self.job["nova_calls"] += 1
        self.save()  # Reserve before the external request, including uncertain responses.
        result = self.nova(content)
        if not isinstance(result, dict):
            raise SafeFailure("INVALID_NOVA_JSON")
        return result

    def run(self, request):
        if request.get("execute") is not True:
            return {"status": "DISARMED"}
        job_id = str(request.get("job_id", ""))
        if not re.fullmatch(r"[a-z0-9-]{5,80}", job_id):
            raise SafeFailure("INVALID_JOB_ID")
        if request.get("model") != MODEL or request.get("ratio") != "2048:2048":
            raise SafeFailure("UNSUPPORTED_MODEL_OR_SIZE")
        if (request.get("max_image_tasks") != 2 or request.get("max_runway_credits") != 18
                or request.get("max_nova_calls") != 3
                or request.get("automatic_generation_retries") != 0
                or request.get("publishing") is not False):
            raise SafeFailure("INVALID_PILOT_BUDGET")
        source_path = (self.root / request["source_path"]).resolve()
        if not source_path.is_relative_to(self.root.resolve()):
            raise SafeFailure("SOURCE_OUTSIDE_REPOSITORY")
        source = source_path.read_bytes()
        proof = image_proof(source)
        if proof["sha256"] != request["source_sha256"]:
            raise SafeFailure("SOURCE_BYTES_CHANGED")
        config_hash = digest(request)
        jobs = self.state.setdefault("jobs", {})
        if job_id not in jobs:
            jobs[job_id] = {
                "request_sha256": config_hash, "source": proof, "created_at": now(),
                "model": MODEL, "status": "CREATED", "views": {},
                "estimated_reserved_runway_credits": 0, "image_task_attempts": 0,
                "nova_calls": 0, "automatic_generation_retries": 0,
                "concept_only": True, "measured_plan": False, "public_posting": False,
                "workflow_run_id": os.getenv("GITHUB_RUN_ID", ""),
                "source_sha": os.getenv("GITHUB_SHA", ""),
            }
        self.job = jobs[job_id]
        if self.job["request_sha256"] != config_hash:
            raise SafeFailure("JOB_ID_BOUND_TO_DIFFERENT_REQUEST")
        retryable_preflight = (
            self.job["status"] == "BLOCKED" and self.job["image_task_attempts"] == 0
            and self.job["nova_calls"] == 0 and self.job.get("blocker") in {
                "INSUFFICIENT_OR_UNVERIFIED_RUNWAY_CREDITS", "MISSING_RUNWAY_CREDENTIAL",
                "RUNWAY_HTTP_401", "RUNWAY_HTTP_403", "RUNWAY_HTTP_429",
                "RUNWAY_RESPONSE_UNCONFIRMED"})
        if retryable_preflight:
            self.job["status"] = "CREATED"
            self.job.pop("blocker", None)
        if self.job["status"] in {"READY_FOR_REVIEW", "NEEDS_REVIEW", "BLOCKED"}:
            return self.job  # Completed/blocked jobs are never silently regenerated.
        self.job_id = job_id
        self.save()
        try:
            uncertain = [v for v in self.job["views"].values()
                         if v.get("state") in {"SUBMITTING", "SUBMISSION_UNCONFIRMED", "QA_RUNNING"}]
            if uncertain or self.job.get("brief_status") == "RUNNING":
                raise SafeFailure("EXTERNAL_RESPONSE_UNCONFIRMED_NO_AUTOMATIC_RETRY")
            remaining = sum(name not in self.job["views"] for name in VIEWS)
            self.job["preflight"] = self.runway.preflight(remaining * CREDITS_PER_IMAGE)
            self.save()
            source_part = {"type": "image_url", "image_url": {
                "url": "data:" + proof["mime"] + ";base64," + base64.b64encode(source).decode()}}
            if "brief" not in self.job:
                self.job["brief_status"] = "RUNNING"
                brief = self.nova_call([
                    {"type": "text", "text":
                     'Analyse this actual living-dining image for a conceptual camera transformation. '
                     'Return JSON only: {"observed_arrangement":"brief visible placement description",'
                     '"materials":["visible finishes"],"uncertain_features":["unknown or hidden geometry"]}. '
                     'Do not infer a floor area, BHK count or dimensions. Do not mistake a straight '
                     'curved-edge sofa for a sectional. Do not invent built-in shelving.'}, source_part])
                if not isinstance(brief.get("observed_arrangement"), str):
                    raise SafeFailure("INVALID_SPATIAL_BRIEF")
                self.job["brief"], self.job["brief_status"] = brief, "COMPLETE"
                self.save()
            for name in VIEWS:
                self.process_view(name, request, source_part)
            self.job["status"] = ("READY_FOR_REVIEW" if all(
                self.job["views"][v].get("qa_pass") is True for v in VIEWS) else "NEEDS_REVIEW")
            self.save()
        except PersistenceFailure:
            raise
        except Exception as exc:
            self.job["status"] = ("WAITING_FOR_PROVIDER" if
                                  str(exc) == "PROVIDER_POLL_WINDOW_EXHAUSTED" else "BLOCKED")
            message = str(exc)
            self.job["blocker"] = (message if isinstance(exc, SafeFailure)
                                   and re.fullmatch(r"[A-Z0-9_]+", message) else type(exc).__name__)
            self.save()
        return self.job

    def process_view(self, name, request, source_part):
        view = self.job["views"].get(name)
        if view is None:
            if self.job["image_task_attempts"] >= 2:
                raise SafeFailure("IMAGE_TASK_BUDGET_EXHAUSTED")
            if self.job["estimated_reserved_runway_credits"] + CREDITS_PER_IMAGE > 18:
                raise SafeFailure("CREDIT_BUDGET_EXHAUSTED")
            prompt = prompt_for(name, self.job["brief"], request["anchors"])
            if len(prompt.encode("utf-16-le")) // 2 > 4000:
                raise SafeFailure("PROMPT_TOO_LONG")
            view = {"state": "SUBMITTING", "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest()}
            self.job["views"][name] = view
            self.job["image_task_attempts"] += 1
            self.job["estimated_reserved_runway_credits"] += CREDITS_PER_IMAGE
            self.save()  # Must succeed remotely BEFORE a billable task is submitted.
            payload = {"model": MODEL, "ratio": "2048:2048", "outputCount": 1,
                       "outputFormat": "jpeg", "promptText": prompt,
                       "referenceImages": [{"uri": source_part["image_url"]["url"]}]}
            try:
                view["task_id"] = self.runway.create(payload)
                view["state"] = "SUBMITTED"
                self.save()
            except PersistenceFailure:
                raise
            except Exception:
                view["state"] = "SUBMISSION_UNCONFIRMED"
                self.save()
                raise SafeFailure("RUNWAY_SUBMISSION_UNCONFIRMED_NO_RETRY") from None
        if view.get("state") in {"QA_PASSED", "QA_REJECTED"}:
            return
        if not view.get("asset"):
            for index in range(MAX_POLLS):
                data = self.runway.task(view["task_id"])
                status = str(data.get("status", "")).upper()
                if status == "SUCCEEDED":
                    outputs = data.get("output") or []
                    if not outputs:
                        raise SafeFailure("PROVIDER_SUCCEEDED_WITHOUT_OUTPUT")
                    raw = self.runway.download(outputs[0])
                    proof = image_proof(raw)
                    suffix = ".jpg" if proof["format"] == "JPEG" else ".png"
                    rel = Path("assets/spatial") / self.job_id / (name + suffix)
                    path = self.root / rel
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(raw)
                    # Signed provider URLs are never persisted in the public repository.
                    view.update(asset=rel.as_posix(), output=proof, state="GENERATED")
                    self.save()
                    break
                if status in {"FAILED", "CANCELED", "CANCELLED"}:
                    view["state"] = "PROVIDER_FAILED"
                    self.save()
                    raise SafeFailure("RUNWAY_TASK_FAILED_NO_REGENERATION")
                if index < MAX_POLLS - 1:
                    self.sleep(POLL_SECONDS)  # Polling the same known task is not regeneration.
            else:
                self.job["status"] = "WAITING_FOR_PROVIDER"
                self.save()
                raise SafeFailure("PROVIDER_POLL_WINDOW_EXHAUSTED")
        raw = (self.root / view["asset"]).read_bytes()
        if hashlib.sha256(raw).hexdigest() != view["output"]["sha256"]:
            raise SafeFailure("GENERATED_BYTES_CHANGED")
        if len(raw) > 3750000:
            raise SafeFailure("OUTPUT_TOO_LARGE_FOR_VISION_REVIEW")
        view["state"] = "QA_RUNNING"
        qa = self.nova_call([
            {"type": "text", "text":
             'Compare ORIGINAL image first and GENERATED image second. The requested view is ' + name +
             '. This is a concept reconstruction, not a measured survey. Require the same visible room, '
             'sofa on left, TV console on right, dining by rear window, lounge chair near front-right; '
             'allow the camera to move and ceiling/front wall removal. No invented extra rooms, '
             'furniture additions, mirrored layout, text, labels or dimensions. For layout require a '
             'strict overhead plan; for birdview require an elevated 3D cutaway. Return JSON only: '
             '{"pass":boolean,"quality_score":0-10,"same_room":boolean,"correct_view":boolean,'
             '"furniture_consistency":boolean,"orientation_consistent":boolean,"no_extra_rooms":boolean,'
             '"no_text_or_dimensions":boolean,"issues":["specific mismatches"]}.'},
            source_part,
            {"type": "image_url", "image_url": {
                "url": "data:" + view["output"]["mime"] + ";base64," + base64.b64encode(raw).decode()}}
        ])
        view.update(qa=qa, qa_pass=qualifies(qa),
                    state="QA_PASSED" if qualifies(qa) else "QA_REJECTED")
        self.save()


def persist_git(root, job_id):
    paths = ["data/spatial_jobs.json"]
    if (root / "assets/spatial" / job_id).exists():
        paths.append("assets/spatial/" + job_id)
    def command(args):
        result = subprocess.run(args, cwd=root, capture_output=True, text=True)
        if result.returncode:
            raise PersistenceFailure("DURABLE_STATE_PERSISTENCE_FAILED")
        return result
    command(["git", "add", "--", *paths])
    changed = subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=root)
    if changed.returncode == 0:
        return
    if changed.returncode != 1:
        raise PersistenceFailure("DURABLE_STATE_DIFF_FAILED")
    command(["git", "commit", "-m", "Record bounded spatial pilot state"])
    command(["git", "push", "origin", "HEAD:main"])


def main():
    request = read_json(ROOT / "operations/spatial_generation_request.json")
    if not request or request.get("execute") is not True:
        print("SPATIAL_REQUEST_DISARMED")
        return 0
    for path in ["state/control.json", "data/control.json"]:
        control = read_json(ROOT / path)
        if not control or control.get("kill_switch") is not False:
            print("SPATIAL_REQUEST_BLOCKED_BY_KILL_SWITCH")
            return 2
    authority = read_json(ROOT / "governance/authority_policy.json")
    if (authority or {}).get("rules", {}).get("three_d_transformation") != "AUTO":
        print("SPATIAL_REQUEST_NOT_AUTHORIZED")
        return 2
    import check_first_post_readiness as nova
    nova.MODEL = os.getenv("AWS_BEDROCK_MODEL_ID", "us.amazon.nova-2-lite-v1:0")
    job_id = str(request.get("job_id", ""))
    if not re.fullmatch(r"[a-z0-9-]{5,80}", job_id):
        print("INVALID_JOB_ID")
        return 2
    try:
        result = Pilot(ROOT, Runway(), lambda content: nova.nova_inference(content),
                       lambda: persist_git(ROOT, job_id)).run(request)
    except SafeFailure as exc:
        print(str(exc))
        return 2
    print(json.dumps({"status": result["status"], "image_task_attempts": result["image_task_attempts"],
                      "nova_calls": result["nova_calls"], "public_posting": False}, indent=2))
    return 0 if result["status"] == "READY_FOR_REVIEW" else 2


if __name__ == "__main__":
    raise SystemExit(main())
