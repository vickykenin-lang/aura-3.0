#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import tempfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"


def fftext(value: str) -> str:
    return str(value).replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'").replace("%", "\\%")


def load_reel(reel_id: str) -> dict:
    data = json.loads((ROOT / "data/reels_calendar.json").read_text(encoding="utf-8"))
    reel = next((r for r in data.get("reels", []) if r.get("id") == reel_id), None)
    if not reel:
        raise SystemExit(f"unknown reel id: {reel_id}")
    return reel


def build_video_filter(reel: dict, duration: float) -> str:
    lines = [str(v).strip() for v in reel.get("overlay_lines", []) if str(v).strip()][:3]
    filters = [
        "scale=1080:1920:force_original_aspect_ratio=increase",
        "crop=1080:1920",
        f"zoompan=z='min(zoom+0.0007,1.08)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={int(duration*30)}:s=1080x1920:fps=30",
        "format=yuv420p",
        "drawbox=x=55:y=225:w=970:h=410:color=black@0.28:t=fill",
        f"drawtext=fontfile={FONT}:text='{fftext(reel.get('hook',''))}':fontcolor=white:fontsize=56:x=(w-text_w)/2:y=270:box=0",
    ]
    slots = [(0.7, 2.7, 760), (2.5, 4.8, 900), (4.5, 6.4, 1040)]
    for line, (start, end, y) in zip(lines, slots):
        filters.append(
            f"drawtext=fontfile={FONT}:text='{fftext(line)}':fontcolor=white:fontsize=48:x=(w-text_w)/2:y={y}:enable='between(t,{start},{min(end,duration)})'"
        )
    cta = fftext(reel.get("cta", "designinfra.in"))
    disclosure = fftext(reel.get("disclosure", "Inspiration reference"))
    filters.extend([
        f"drawtext=fontfile={FONT}:text='{cta}':fontcolor=white:fontsize=43:x=(w-text_w)/2:y=1510:enable='gte(t,{max(0,duration-1.8)})'",
        f"drawtext=fontfile={FONT}:text='{disclosure}':fontcolor=white@0.85:fontsize=25:x=(w-text_w)/2:y=1810",
    ])
    return ",".join(filters)


def render(reel: dict, output: Path) -> None:
    duration = float(reel.get("duration_seconds", 7.0))
    if not 5.0 <= duration <= 10.0:
        raise SystemExit("duration outside 5-10 second policy")
    image_url = str(reel.get("image", ""))
    if not image_url.startswith("https://"):
        raise SystemExit("reel image must use HTTPS")

    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as temp_dir:
        image_path = Path(temp_dir) / "source.jpg"
        urllib.request.urlretrieve(image_url, image_path)
        video_filter = build_video_filter(reel, duration)
        audio = f"aevalsrc=0.018*sin(2*PI*110*t)+0.010*sin(2*PI*220*t)+0.006*sin(2*PI*329.63*t):s=48000:d={duration}"
        cmd = [
            "ffmpeg", "-y", "-loop", "1", "-i", str(image_path),
            "-f", "lavfi", "-i", audio,
            "-t", str(duration),
            "-vf", video_filter,
            "-c:v", "libx264", "-preset", "medium", "-crf", "20",
            "-c:a", "aac", "-b:a", "128k", "-af", "volume=0.55",
            "-shortest", "-movflags", "+faststart", str(output),
        ]
        subprocess.run(cmd, check=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("reel_id")
    parser.add_argument("--output")
    args = parser.parse_args()
    reel = load_reel(args.reel_id)
    output = Path(args.output) if args.output else ROOT / "reels/output" / f"{args.reel_id}.mp4"
    render(reel, output)
    print(json.dumps({"status": "RENDERED_SHADOW", "reel_id": args.reel_id, "output": str(output), "public_action_performed": False}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
