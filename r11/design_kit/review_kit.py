#!/usr/bin/env python3
"""R11 Design Kit reviewer (agent A4).

Checks a built kit before it can be published automatically:
  1. Deterministic: every file matches kit.json sha256, slides are 1080x1350 JPEG
     under 8 MB, reel is 1080x1920 H.264/AAC 30 fps, caption carries the WhatsApp
     number, the disclosure and at most 30 hashtags.
  2. Vision (optional, --nova): Amazon Nova reads all slides and must report no
     spelling mistakes, readable text and the exact WhatsApp number.

Writes review.json next to the kit. It never publishes anything.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

from PIL import Image

MAX_JPEG = 8 * 1024 * 1024
MAX_CAPTION = 2200
MAX_TAGS = 30
DEFAULT_MODEL = "us.amazon.nova-2-lite-v1:0"


def sha256(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def check_files(out: Path, spec: dict) -> list[str]:
    issues = []
    manifest = json.loads((out / "kit.json").read_text(encoding="utf-8"))
    if manifest.get("publishing") is not False:
        issues.append("MANIFEST_PUBLISHING_NOT_FALSE")
    if manifest["source"]["sha256"] != spec["source"]["sha256"]:
        issues.append("SOURCE_SHA_DIFFERS_FROM_SPEC")
    slides = [o for o in manifest["outputs"] if o["kind"] == "carousel_slide"]
    if len(slides) != 5:
        issues.append(f"SLIDE_COUNT:{len(slides)}")
    for o in manifest["outputs"]:
        p = out / o["file"]
        if not p.exists():
            issues.append(f"MISSING:{o['file']}")
            continue
        if sha256(p) != o["sha256"]:
            issues.append(f"SHA_MISMATCH:{o['file']}")
        if o["kind"] == "carousel_slide":
            with Image.open(p) as im:
                if im.format != "JPEG" or im.size != (1080, 1350) or im.mode != "RGB":
                    issues.append(f"SLIDE_FORMAT:{o['file']}:{im.format}:{im.size}:{im.mode}")
            if p.stat().st_size > MAX_JPEG:
                issues.append(f"SLIDE_TOO_BIG:{o['file']}")
        if o["kind"] == "reel":
            issues += check_reel(p)
    return issues


def check_reel(p: Path) -> list[str]:
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                        "stream=codec_type,codec_name,width,height,pix_fmt,r_frame_rate:format=duration",
                        "-of", "json", str(p)], capture_output=True, text=True)
    if r.returncode != 0:
        return ["REEL_UNREADABLE"]
    info = json.loads(r.stdout)
    v = next((s for s in info["streams"] if s["codec_type"] == "video"), {})
    a = next((s for s in info["streams"] if s["codec_type"] == "audio"), {})
    issues = []
    if (v.get("codec_name"), v.get("width"), v.get("height"), v.get("pix_fmt"), v.get("r_frame_rate")) != \
            ("h264", 1080, 1920, "yuv420p", "30/1"):
        issues.append("REEL_VIDEO_FORMAT")
    if a.get("codec_name") != "aac":
        issues.append("REEL_AUDIO_FORMAT")
    if not 3 <= float(info["format"]["duration"]) <= 90:
        issues.append("REEL_DURATION")
    return issues


def check_caption(caption: str, spec: dict) -> list[str]:
    issues = []
    if len(caption) > MAX_CAPTION:
        issues.append("CAPTION_TOO_LONG")
    if len(re.findall(r"#\w+", caption)) > MAX_TAGS:
        issues.append("TOO_MANY_HASHTAGS")
    if spec["brand"]["whatsapp_display"] not in caption:
        issues.append("CAPTION_MISSING_WHATSAPP")
    if spec["brand"]["disclosure"] not in caption:
        issues.append("CAPTION_MISSING_DISCLOSURE")
    if "bio" not in caption.lower():
        issues.append("CAPTION_MISSING_BIO_LINK_CTA")
    return issues


def nova_review(out: Path, spec: dict, converse=None) -> dict:
    prompt = (
        "You are the quality reviewer for an Instagram carousel by an interior design studio. "
        "Five slides follow in order. Check every word you can read on the slides. Return JSON only: "
        '{"pass":boolean,"quality_score":0-10,"spelling_errors":["exact wrong words"],'
        '"text_readable":boolean,"same_room_across_slides":boolean,'
        '"whatsapp_number_seen":"the phone number exactly as printed, or empty",'
        '"issues":["specific problems"]}. Hinglish words such as "Apne ghar ke liye aisa look chahiye" '
        "are intended and are not spelling errors.")
    content = [{"text": prompt}]
    for i in range(1, 6):
        content.append({"image": {"format": "jpeg", "source": {"bytes": (out / f"slide{i}.jpg").read_bytes()}}})
    if converse is None:
        import boto3
        client = boto3.client("bedrock-runtime", region_name=(os.environ.get("AWS_REGION") or "us-east-1").strip())
        model = (os.environ.get("AWS_BEDROCK_MODEL_ID") or DEFAULT_MODEL).strip()

        def converse(msgs):
            r = client.converse(modelId=model, messages=msgs,
                                inferenceConfig={"maxTokens": 800, "temperature": 0.0})
            return "".join(p.get("text", "") for p in r["output"]["message"]["content"])
    try:
        text = converse([{"role": "user", "content": content}])
    except Exception as exc:  # provider down or credentials invalid: report, never crash
        code = getattr(exc, "response", {}).get("Error", {}).get("Code") or type(exc).__name__
        return {"ok": False, "unavailable": True, "issues": [f"NOVA_UNAVAILABLE:{code}"]}
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return {"ok": False, "issues": ["NOVA_NO_JSON"], "raw": text[:400]}
    qa = json.loads(m.group(0))
    want = spec["brand"]["whatsapp_display"].replace(" ", "")
    seen = str(qa.get("whatsapp_number_seen", "")).replace(" ", "")
    ok = (qa.get("pass") is True and isinstance(qa.get("quality_score"), (int, float))
          and qa["quality_score"] >= 7 and not qa.get("spelling_errors")
          and qa.get("text_readable") is True and qa.get("same_room_across_slides") is True
          and seen == want)
    return {"ok": ok, "qa": qa}


def review(out: Path, spec_path: Path, use_nova=False, converse=None) -> dict:
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    issues = check_files(out, spec)
    for name in ("caption.txt", "reel_caption.txt"):
        cap = out / name
        if name == "reel_caption.txt" and not (out / "reel.mp4").exists():
            continue
        issues += [f"{i}:{name}" for i in check_caption(cap.read_text(encoding="utf-8") if cap.exists() else "", spec)]
    result = {"kit_id": spec["kit_id"], "deterministic_issues": issues, "vision": None}
    if use_nova and not issues:
        result["vision"] = nova_review(out, spec, converse)
    # Text on every slide is drawn by code, so the code checks are the gate. Nova is an
    # extra eye: if it runs and objects, the kit is blocked; if it cannot run, it is noted.
    if issues:
        verdict = "REJECTED"
    elif result["vision"] is None or result["vision"].get("unavailable"):
        verdict = "READY_CODE_CHECKED"
    else:
        verdict = "READY_VISION_CHECKED" if result["vision"]["ok"] else "REJECTED_BY_VISION_REVIEW"
    result["verdict"] = verdict
    result["publishing"] = False
    (out / "review.json").write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return result


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("spec")
    ap.add_argument("--out", required=True)
    ap.add_argument("--nova", action="store_true")
    a = ap.parse_args()
    r = review(Path(a.out), Path(a.spec), a.nova)
    print(json.dumps({"kit_id": r["kit_id"], "verdict": r["verdict"],
                      "issues": r["deterministic_issues"],
                      "vision": (r["vision"] or {}).get("qa") or (r["vision"] or {}).get("issues")}, ensure_ascii=False))
    sys.exit(0 if r["verdict"].startswith("READY") else 3)


if __name__ == "__main__":
    main()
