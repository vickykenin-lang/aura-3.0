#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
API = "https://api.dev.runwayml.com/v1"
API_VERSION = "2024-11-06"
MODEL = os.environ.get("AURA3_REEL_MODEL", "h3_max")
DURATION = int(os.environ.get("AURA3_REEL_DURATION", "8"))
RATIO = os.environ.get("AURA3_REEL_RATIO", "768:1280")
JOBS_PATH = ROOT / "data/reel_generation_jobs.json"
OUT_DIR = ROOT / "reels/generated"

PROMPT = """You are an expert interior 3D reconstruction designer and cinematic virtual cinematographer. Reconstruct the exact room shown in the reference image and preserve architecture, wall and ceiling finishes, floor, furniture layout and proportions, fabrics, wood, stone, metal, glass, lighting fixtures, decor, plants, window positions, visible exterior view, colors, time of day, and lighting style. Do not add, remove, rearrange, redesign, beautify, modernize, recolor, or restyle anything. One continuous first-person Steadicam shot at approximately 1.55m eye height. Start from the natural foreground/entrance implied by the reference. Slowly move forward at about 0.3 m/s, then only if spatially safe make a gentle 12-18 degree orbit around the main focal furniture and settle on a closer hero frame. Strong natural parallax. If unseen geometry is uncertain, stay close to the original camera axis and use a simpler slow forward push instead of a large orbit. Luxury real-estate slow motion, ultra smooth and stable. No cuts, transitions, Ken Burns, flat 2D pan, zoom-only movement, morphing, jitter, warped walls, bending ceilings, drifting floor lines, sliding or melting furniture, stretching windows, duplicated or disappearing objects, texture crawling, geometry breathing, or unstable reflections. Photoreal, filmic, 24-35mm lens feel, controlled depth of field, accurate reflections and contact shadows, preserve reference lighting exactly. Empty room. No people, pets, text, logos, watermark, or UI. Vertical mobile composition; keep main furniture inside the center 70% safe area. Reference fidelity is always more important than cinematic movement."""


def load_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def save_jobs(data: dict) -> None:
    JOBS_PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def upsert_job(job: dict) -> None:
    data = load_json(JOBS_PATH, {"schema_version": 1, "jobs": []})
    jobs = list(data.get("jobs") or [])
    jobs = [x for x in jobs if x.get("reel_id") != job.get("reel_id")]
    jobs.append(job)
    data["jobs"] = jobs[-100:]
    save_jobs(data)


def request_json(url: str, *, method="GET", payload=None, timeout=90) -> dict:
    secret = (os.environ.get("RUNWAYML_API_SECRET") or "").strip()
    if not secret:
        raise RuntimeError("RUNWAYML_API_SECRET unavailable")
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(
        url,
        data=body,
        method=method,
        headers={
            "Authorization": f"Bearer {secret}",
            "Content-Type": "application/json",
            "X-Runway-Version": API_VERSION,
            "User-Agent": "AURA3-Reel-Generator/1.0",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as response:
        result = json.loads(response.read().decode("utf-8"))
    if not isinstance(result, dict):
        raise RuntimeError("Runway returned non-object JSON")
    return result


def create_task(image_url: str) -> str:
    result = request_json(
        f"{API}/image_to_video",
        method="POST",
        payload={
            "model": MODEL,
            "promptImage": image_url,
            "promptText": PROMPT,
            "ratio": RATIO,
            "duration": DURATION,
        },
        timeout=120,
    )
    task_id = str(result.get("id") or "").strip()
    if not task_id:
        raise RuntimeError("Runway did not return task id")
    return task_id


def wait_task(task_id: str) -> str:
    for _ in range(40):
        task = request_json(f"{API}/tasks/{task_id}", timeout=60)
        status = str(task.get("status") or "").upper()
        if status == "SUCCEEDED":
            output = task.get("output") or []
            if isinstance(output, list) and output and str(output[0]).startswith("https://"):
                return str(output[0])
            raise RuntimeError("Runway task succeeded without video output")
        if status in {"FAILED", "CANCELED", "CANCELLED"}:
            raise RuntimeError(f"Runway task ended with {status}")
        time.sleep(15)
    raise TimeoutError("Runway video generation timed out")


def download(url: str, dest: Path) -> None:
    req = urllib.request.Request(url, headers={"User-Agent": "AURA3-Reel-Generator/1.0"})
    with urllib.request.urlopen(req, timeout=180) as response:
        data = response.read()
    if not data:
        raise RuntimeError("Generated video download was empty")
    dest.write_bytes(data)


def normalize(src: Path, dest: Path) -> None:
    cmd = [
        "ffmpeg", "-y", "-i", str(src),
        "-t", "8",
        "-vf", "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,fps=24",
        "-an",
        "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p",
        "-movflags", "+faststart", str(dest),
    ]
    subprocess.run(cmd, check=True)


def probe(path: Path) -> dict:
    cmd = [
        "ffprobe", "-v", "error", "-select_streams", "v:0",
        "-show_entries", "stream=width,height,r_frame_rate:format=duration",
        "-of", "json", str(path),
    ]
    raw = subprocess.check_output(cmd, text=True)
    info = json.loads(raw)
    stream = (info.get("streams") or [{}])[0]
    duration = float((info.get("format") or {}).get("duration") or 0)
    return {
        "width": int(stream.get("width") or 0),
        "height": int(stream.get("height") or 0),
        "fps": str(stream.get("r_frame_rate") or ""),
        "duration_seconds": round(duration, 2),
    }


def main() -> int:
    post_id = (os.environ.get("POST_ID") or "").strip()
    if not post_id:
        raise SystemExit("POST_ID required")

    calendar = load_json(ROOT / "content/calendar.json", {"days": []})
    gates = load_json(ROOT / "data/gate_results.json", {"posts": {}})
    post = next((p for p in calendar.get("days", []) if p.get("id") == post_id), None)
    if not post:
        raise SystemExit(f"Unknown post id: {post_id}")
    gate = (gates.get("posts") or {}).get(post_id) or {}
    if not (gate.get("pass") and gate.get("visual_ok") and float(gate.get("score") or 0) >= 7):
        raise SystemExit("REFUSED: source post is not current strict-gate-passed")

    image_url = str(post.get("image") or "").strip()
    if not image_url.startswith("https://"):
        raise SystemExit("REFUSED: source image must be public HTTPS")

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    reel_id = f"{post_id}-reel-{stamp}"
    base_job = {
        "reel_id": reel_id,
        "post_id": post_id,
        "source_image": image_url,
        "status": "GENERATING",
        "requested_by": os.environ.get("GITHUB_ACTOR", "Founder"),
        "requested_at": datetime.now(timezone.utc).isoformat(),
        "provider": "runway",
        "model": MODEL,
        "target": {"ratio": "9:16", "width": 1080, "height": 1920, "duration_seconds": 8, "fps": 24},
        "prompt_profile": "INTERIOR_REFERENCE_FIDELITY_WALKTHROUGH_V1",
        "truth_note": "Founder-triggered Reel generation is independent from static-post approval and does not publish automatically.",
    }
    upsert_job(base_job)

    try:
        task_id = create_task(image_url)
        base_job["provider_task_id"] = task_id
        upsert_job(base_job)
        provider_url = wait_task(task_id)
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        raw = OUT_DIR / f"{reel_id}.raw.mp4"
        final = OUT_DIR / f"{reel_id}.mp4"
        download(provider_url, raw)
        normalize(raw, final)
        raw.unlink(missing_ok=True)
        tech = probe(final)
        technical_pass = tech["width"] == 1080 and tech["height"] == 1920 and 7.0 <= tech["duration_seconds"] <= 8.2
        base_job.update({
            "status": "READY_FOR_FOUNDER_REVIEW" if technical_pass else "TECHNICAL_REJECT",
            "video_path": final.relative_to(ROOT).as_posix(),
            "technical": tech,
            "technical_pass": technical_pass,
            "completed_at": datetime.now(timezone.utc).isoformat(),
        })
        upsert_job(base_job)
        print(json.dumps({"reel_generation": base_job["status"], "reel_id": reel_id, "post_id": post_id, "technical": tech}))
        return 0 if technical_pass else 2
    except Exception as exc:
        base_job.update({
            "status": "FAILED",
            "error_type": type(exc).__name__,
            "completed_at": datetime.now(timezone.utc).isoformat(),
        })
        upsert_job(base_job)
        print(json.dumps({"reel_generation": "FAILED", "reel_id": reel_id, "error_type": type(exc).__name__}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
