#!/usr/bin/env python3
"""Bounded image/caption/Meta probes. Never create a container or publish."""
import base64
import hashlib
import json
import os
import re
from pathlib import Path
import subprocess
import sys
from datetime import datetime, timezone
from urllib.request import Request, urlopen
from urllib.error import HTTPError
from urllib.parse import urlencode

import release_guard

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "certification/evidence"
PROVIDER = os.getenv("READINESS_PROVIDER", "deepseek").strip()
MODEL = (os.getenv("AWS_BEDROCK_MODEL_ID", "us.amazon.nova-2-lite-v1:0")
         if PROVIDER == "amazon_nova" else "deepseek-flash")
NOVA_CLIENT = None


def write(path, value):
    path = ROOT / path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def request_json(url, headers=None, body=None):
    request = Request(url, headers=headers or {},
                      data=None if body is None else json.dumps(body).encode(),
                      method="GET" if body is None else "POST")
    try:
        with urlopen(request, timeout=90) as response:
            return json.loads(response.read().decode())
    except HTTPError as exc:
        # Only fixed status/type information may be persisted.
        raise RuntimeError("HTTP_" + str(exc.code)) from None
    except Exception:
        raise RuntimeError("NETWORK_OR_JSON_ERROR") from None


def nova_inference(content):
    global NOVA_CLIENT
    import boto3
    from botocore.config import Config
    from botocore.exceptions import BotoCoreError, ClientError
    parts = []
    if isinstance(content, str):
        parts = [{"text": content}]
    else:
        for part in content:
            if part.get("type") == "text":
                parts.append({"text": part["text"]})
            elif part.get("type") == "image_url":
                raw = part["image_url"]["url"]
                prefix = raw.split(",", 1)[0]
                fmt = {"data:image/png;base64": "png",
                       "data:image/jpeg;base64": "jpeg"}.get(prefix)
                if not fmt:
                    raise RuntimeError("UNSUPPORTED_NOVA_IMAGE")
                parts.append({"image": {"format": fmt, "source": {
                    "bytes": base64.b64decode(raw.split(",", 1)[1], validate=True)}}})
            else:
                raise RuntimeError("UNSUPPORTED_NOVA_CONTENT")
    try:
        if NOVA_CLIENT is None:
            NOVA_CLIENT = boto3.client(
                "bedrock-runtime", region_name=os.getenv("AWS_REGION", "us-east-1"),
                config=Config(connect_timeout=10, read_timeout=90,
                              retries={"total_max_attempts": 1, "mode": "standard"}))
        response = NOVA_CLIENT.converse(
            modelId=MODEL, messages=[{"role": "user", "content": parts}],
            inferenceConfig={"maxTokens": 1600, "temperature": 0})
    except ClientError as exc:
        code = str(exc.response.get("Error", {}).get("Code", "AWS_CLIENT_ERROR"))
        raise RuntimeError("NOVA_" + code) from None
    except BotoCoreError:
        raise RuntimeError("NOVA_CREDENTIAL_OR_NETWORK_ERROR") from None
    text = "".join(part.get("text", "") for part in
                   response.get("output", {}).get("message", {}).get("content", []))
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(), flags=re.I)
    try:
        result = json.loads(text)
        if not isinstance(result, dict):
            raise ValueError()
        return result
    except ValueError:
        raise RuntimeError("INVALID_NOVA_JSON") from None


def inference(key, content):
    if PROVIDER == "amazon_nova":
        return nova_inference(content)
    result = request_json("https://api.deepseek.com/chat/completions",
                          {"Authorization": "Bearer " + key, "Content-Type": "application/json"},
                          {"model": MODEL, "messages": [{"role": "user", "content": content}],
                           "max_tokens": 1600, "temperature": 0,
                           "response_format": {"type": "json_object"}})
    try:
        parsed = json.loads(result["choices"][0]["message"]["content"])
        if not isinstance(parsed, dict):
            raise ValueError()
        return parsed
    except (ValueError, TypeError, KeyError, IndexError):
        raise RuntimeError("INVALID_MODEL_JSON") from None


def reusable_vision(candidate, now):
    source = candidate.get("reuse_vision_evidence")
    if not source:
        return None
    if not source.startswith("campaigns/r11/evidence/") or ".." in Path(source).parts:
        raise RuntimeError("INVALID_VISION_EVIDENCE_PATH")
    record = json.loads((ROOT / source).read_text())
    observed = datetime.fromisoformat(record["observed_at"].replace("Z", "+00:00"))
    age = (datetime.fromisoformat(now) - observed).total_seconds()
    if not (record.get("vision_pass") is True
            and record.get("image_sha256") == candidate["image_sha256"]
            and record.get("provider") == MODEL and 0 <= age <= 86400):
        raise RuntimeError("VISION_EVIDENCE_NOT_APPLICABLE")
    return record


def stage_qualified_candidate(candidate, receipt, business):
    blocks = candidate["caption"].split("\n\n")
    post = {"id": candidate["candidate_id"], "date": receipt["observed_at"][:10],
            "photo_tag": "living", "image": candidate["image_url"],
            "image_source": "R11 AI-generated campaign concept",
            "disclosure": "",
            "ig": {"hook_en": blocks[0], "caption_hi": "\n\n".join(blocks[1:-1]),
                   "hashtags": blocks[-1]}}
    if release_guard.caption(post) != candidate["caption"]:
        raise RuntimeError("CAPTION_ASSEMBLY_MISMATCH")
    gate = {"pass": True, "visual_ok": True, "score": business["score"],
            "model": MODEL, "caption_match": True, "cta_ok": True, "conversion_ok": True,
            "vision": dict(receipt["vision"], model=MODEL),
            "evidence_source": "certification/evidence/first-post-readiness.json",
            "reviewed_at": receipt["observed_at"]}
    gate = release_guard.bind_qualified_gate(post, gate, ROOT)
    if not gate.get("release_manifest_sha256"):
        raise RuntimeError("CONTENT_BINDING_FAILED")
    calendar = json.loads((ROOT / "content/calendar.json").read_text())
    supersedes = candidate.get("supersedes_candidate_id")
    if supersedes:
        approvals = json.loads((ROOT / "data/approvals.json").read_text())
        published = json.loads((ROOT / "content/published.json").read_text())
        if str(approvals.get(supersedes, "pending")).lower() != "pending" or published.get(supersedes):
            raise RuntimeError("SUPERSEDED_CANDIDATE_ALREADY_DECIDED")
        old = next((p for p in calendar["days"] if p.get("id") == supersedes), None)
        if old:
            archive_id = re.sub(r"[^A-Za-z0-9_-]", "_", supersedes)
            write("campaigns/r11/evidence/superseded-" + archive_id + ".json", {
                "post": old, "superseded_by": post["id"],
                "reason": candidate.get("supersession_reason", "Revised public copy"),
                "source_sha": receipt["source_sha"]})
            calendar["days"] = [p for p in calendar["days"] if p.get("id") != supersedes]
    existing = next((p for p in calendar["days"] if p.get("id") == post["id"]), None)
    if existing is not None and existing != post:
        raise RuntimeError("CANDIDATE_ID_ALREADY_BOUND_TO_OTHER_CONTENT")
    if existing is None:
        calendar["days"].append(post)
    gates = json.loads((ROOT / "data/gate_results.json").read_text())
    gates.setdefault("posts", {})[post["id"]] = gate
    # Never turn an incomplete legacy batch into a passed batch.
    if gates.get("batch_complete") is not True:
        raise RuntimeError("EXISTING_BATCH_INCOMPLETE")
    release_guard.qualified_manifest(post, gates, ROOT)
    write("content/calendar.json", calendar)
    write("data/gate_results.json", gates)
    write("campaigns/r11/release-manifest.json", {
        "manifest": gate["release_manifest"],
        "manifest_sha256": gate["release_manifest_sha256"],
        "public_posting_approval": "PENDING"})
    receipt["release_manifest_sha256"] = gate["release_manifest_sha256"]


def meta_access():
    token = os.getenv("IG_TOKEN", "").strip()
    configured = os.getenv("IG_ID", "").strip()
    if not token or not configured:
        return {"identity_match": False, "publishing_limit_readable": False,
                "status": "MISSING_META_CREDENTIAL"}
    headers = {"Authorization": "Bearer " + token}
    base = "https://graph.instagram.com/v25.0/"
    try:
        me = request_json(base + "me?" + urlencode({"fields": "id,user_id,username"}), headers)
        matched = (str(me.get("user_id") or me.get("id") or "") == configured
                   and me.get("username") == "designinfra.interiors")
        if not matched:
            return {"identity_match": False, "publishing_limit_readable": False,
                    "status": "TARGET_MISMATCH"}
        limit = request_json(base + configured + "/content_publishing_limit?" +
                             urlencode({"fields": "quota_usage,config"}), headers)
        readable = isinstance(limit.get("data"), list) and bool(limit["data"])
        return {"identity_match": True, "publishing_limit_readable": readable,
                "status": "READ_ONLY_PUBLISHING_ACCESS_VERIFIED" if readable else "LIMIT_RESPONSE_UNVERIFIED",
                "public_action_performed": False,
                "actual_publish_tested": False}
    except RuntimeError as exc:
        return {"identity_match": locals().get("matched", False),
                "publishing_limit_readable": False, "status": str(exc),
                "public_action_performed": False}


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc).isoformat()
    candidate = json.loads((ROOT / "campaigns/r11/first-post.json").read_text())
    image = (ROOT / candidate["repository_image"]).read_bytes()
    if hashlib.sha256(image).hexdigest() != candidate["image_sha256"]:
        raise SystemExit("IMAGE_HASH_MISMATCH")
    from PIL import Image
    with Image.open(ROOT / candidate["repository_image"]) as decoded:
        if decoded.format != "JPEG":
            raise SystemExit("INSTAGRAM_REQUIRES_JPEG_SOURCE")
    if hashlib.sha256(candidate["caption"].encode()).hexdigest() != candidate["caption_sha256"]:
        raise SystemExit("CAPTION_HASH_MISMATCH")
    proof = release_guard.record_image_proof(candidate["image_url"], "image/jpeg", image)
    if proof["width"] < 1200 or proof["height"] < 800 or len(image) > 8 * 1024 * 1024:
        raise SystemExit("IMAGE_TECHNICAL_CHECK_FAILED")
    receipt = {"observed_at": now, "candidate_id": candidate["candidate_id"],
               "image_sha256": candidate["image_sha256"],
               "caption_sha256": hashlib.sha256(candidate["caption"].encode()).hexdigest(),
               "image_proof": proof, "provider": MODEL, "inference_calls": 0,
               "maximum_inference_calls": 2, "automatic_retries": 0,
               "public_action_performed": False, "founder_approval": "PENDING",
               "source_sha": os.getenv("GITHUB_SHA", "LOCAL")}
    vision_ok = business_ok = False
    generated_hook = False
    key = os.getenv("DEEPSEEK_API_KEY", "").strip()
    try:
        if PROVIDER != "amazon_nova" and not key:
            raise RuntimeError("MISSING_DEEPSEEK_CREDENTIAL")
        previous = reusable_vision(candidate, now)
        if previous:
            vision = previous["vision"]
            receipt["vision_evidence_reused_from"] = candidate["reuse_vision_evidence"]
            receipt["vision_original_observed_at"] = previous["observed_at"]
            receipt["vision_original_source_sha"] = previous["source_sha"]
        else:
            receipt["inference_calls"] += 1
            vision = inference(key, [
            {"type": "text", "text":
             'Inspect the actual attached interior image. Return JSON only: '
             '{"visual_ok":boolean,"quality_score":0-10,"current_design":boolean,'
             '"room_type":"living/dining/other","watermark_present":boolean,'
             '"visible_features":["specific visible facts"],"issues":["actual defects"],'
             '"suggested_hook":"one short English hook grounded in the visible design"}. '
             'Pass only for a clear, current modern luxury residential interior, score>=7, '
             'with no visible watermark. Do not infer property dimensions or material species.'},
            {"type": "image_url", "image_url": {
                "url": "data:image/jpeg;base64," + base64.b64encode(image).decode()}}
            ])
        vision_ok = (vision.get("visual_ok") is True and vision.get("current_design") is True
                     and vision.get("watermark_present") is False
                     and isinstance(vision.get("quality_score"), (int, float))
                     and 7 <= vision["quality_score"] <= 10
                     and bool(vision.get("visible_features")))
        generated_hook = bool(str(vision.get("suggested_hook", "")).strip())
        receipt["vision"] = vision
        receipt["vision_pass"] = vision_ok
        receipt["inference_calls"] += 1
        business = inference(key,
            'You are the separate Design Infra business and caption grounding gate. '
            'Compare this exact caption only with the actual-image findings below. '
            'Return JSON only: {"pass":boolean,"score":0-10,"caption_match":boolean,'
            '"cta_ok":boolean,"conversion_ok":boolean,"reasons":["specific findings"]}. '
            'Existing strict gate requires score>=7, caption_match, an explicit actionable '
            'consultation/website/lead CTA and a credible process/inclusions/timeline/price signal. '
            'Do not relax the gate just because the Founder removed copy. Never invent completed work. '
            'This is an AI-generated concept; do not require the removed disclaimer sentence. '
            'Keep design advice general; do not assert a specific floor plan or property size.\n'
            'Relevant BHK hashtags are audience-targeting tags, not a floor-plan claim; '
            'the caption prose itself must remain general.\n'
            'Image findings: ' + json.dumps(vision, ensure_ascii=False) +
            '\nExact caption: ' + candidate["caption"])
        business_ok = (business.get("pass") is True
                       and isinstance(business.get("score"), (int, float))
                       and 7 <= business["score"] <= 10
                       and all(business.get(k) is True for k in
                               ["caption_match", "cta_ok", "conversion_ok"]))
        receipt["business"] = business
        receipt["business_pass"] = business_ok
    except RuntimeError as exc:
        receipt["provider_error"] = str(exc)
    receipt["instagram"] = meta_access()
    tests_pass = os.getenv("OFFLINE_GUARDS_PASSED") == "true"
    provider_ok = bool(receipt.get("vision") and receipt.get("business"))
    write("runtime/provider_qualification.json", {
        "schema_version": 4, "department_id": "aura3", "observed_at": now,
        "status": "QUALIFIED" if provider_ok else "NOT_VERIFIED",
        "all_required_qualified": provider_ok,
        "scope": "Only the actual provider tested in this run is qualified; alternate providers are not.",
        "providers": {PROVIDER: {"model": MODEL, "actual_image_inference_this_run":
                                   bool(receipt.get("vision")) and not bool(receipt.get("vision_evidence_reused_from")),
                                   "reused_fresh_image_evidence": bool(receipt.get("vision_evidence_reused_from")),
                                   "separate_text_inference": bool(receipt.get("business"))}},
        "evidence_source": "certification/evidence/first-post-readiness.json",
        "source_sha": receipt["source_sha"], "secret_values_recorded": False})
    all_ok = (vision_ok and business_ok and generated_hook and tests_pass
              and receipt["instagram"].get("publishing_limit_readable") is True)
    write("runtime/capability_qualification.json", {
        "schema_version": 3, "department_id": "aura3", "observed_at": now,
        "status": "QUALIFIED" if all_ok else "NOT_VERIFIED", "all_required_qualified": all_ok,
        "capabilities": {"content_generation": generated_hook, "actual_image_visual_gate": vision_ok,
                         "business_quality_gate": business_ok, "founder_approval_gate": tests_pass,
                         "reporting": True, "publishing_access_read_only":
                         receipt["instagram"].get("publishing_limit_readable") is True,
                         "public_publish": "NOT_EXECUTED_FOUNDER_ONLY"},
        "evidence_source": "certification/evidence/first-post-readiness.json",
        "source_sha": receipt["source_sha"], "public_action_executed": False})
    receipt["offline_guards_passed"] = tests_pass
    receipt["readiness"] = "READY_FOR_FOUNDER_APPROVAL" if all_ok else "NOT_VERIFIED"
    if all_ok:
        stage_qualified_candidate(candidate, receipt, receipt["business"])
    write("certification/evidence/first-post-readiness.json", receipt)
    heartbeat = subprocess.run([sys.executable, str(ROOT / "scripts/run_heartbeat.py")],
                               capture_output=True, text=True)
    if heartbeat.returncode != 0:
        raise SystemExit("HEARTBEAT_FAILED")
    cert = subprocess.run([sys.executable, str(ROOT / "scripts/certify_live.py")],
                          capture_output=True, text=True)
    try:
        certification = json.loads(cert.stdout)
    except ValueError:
        raise SystemExit("CERTIFICATION_OUTPUT_INVALID")
    write("certification/evidence/live-certification.json", certification)
    print(json.dumps({"readiness": receipt["readiness"], "vision_pass": vision_ok,
                      "business_pass": business_ok, "instagram": receipt["instagram"],
                      "certification": certification["certification"],
                      "inference_calls": receipt["inference_calls"],
                      "public_action_performed": False}, indent=2))
    return 0 if all_ok and cert.returncode == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
