#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import tempfile
import textwrap
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FONT_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
FONT_REG = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"


def esc(value: str) -> str:
    return (str(value).replace("\\", "\\\\").replace(":", "\\:")
            .replace("'", "\\'").replace("%", "\\%").replace("\n", "\\n"))


def wrap(value: str, width: int) -> str:
    return "\n".join(textwrap.wrap(str(value).strip(), width=width, break_long_words=False))


def load_reel(reel_id: str) -> dict:
    data = json.loads((ROOT / "data/reels_calendar.json").read_text(encoding="utf-8"))
    reel = next((r for r in data.get("reels", []) if r.get("id") == reel_id), None)
    if not reel:
        raise SystemExit(f"unknown reel id: {reel_id}")
    return reel


def dimensions(path: Path) -> tuple[int, int]:
    out = subprocess.check_output([
        "ffprobe", "-v", "error", "-select_streams", "v:0",
        "-show_entries", "stream=width,height", "-of", "json", str(path)
    ], text=True)
    s = json.loads(out)["streams"][0]
    return int(s["width"]), int(s["height"])


def alpha(start: float, end: float, fade: float = 0.20) -> str:
    return (f"if(lt(t,{start}),0,if(lt(t,{start+fade}),(t-{start})/{fade},"
            f"if(lt(t,{end-fade}),1,if(lt(t,{end}),({end}-t)/{fade},0))))")


def filter_graph(reel: dict) -> str:
    hook = esc(wrap(reel.get("hook", ""), 24))
    lines = [str(x).strip() for x in reel.get("overlay_lines", []) if str(x).strip()]
    mid = esc(wrap(" · ".join(lines[:2]), 33))
    cta = esc(wrap(reel.get("cta", "designinfra.in"), 32))
    disclosure = esc(reel.get("disclosure", "Inspiration reference"))

    # Founder motion rule:
    # - no handheld shake
    # - no random x/y drift
    # - no full 360 spin
    # - smooth controlled 4-degree rotation over 7 sec
    # - tiny push-in only, to keep the interior premium and calm
    return ";".join([
        "[0:v]scale=1180:2100:force_original_aspect_ratio=increase,crop=1180:2100,format=yuv420p[prep]",
        "[prep]zoompan=z='min(1.0+on*0.000055,1.012)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=210:s=1180x2100:fps=30,trim=duration=7,setpts=PTS-STARTPTS[push]",
        "[push]rotate='(-2+4*t/7)*PI/180':ow=1180:oh=2100:fillcolor=black@0,"
        "crop=1080:1920:x=(iw-1080)/2:y=(ih-1920)/2,format=yuv420p[motion]",
        "[motion]drawbox=x=0:y=1260:w=1080:h=660:color=black@0.24:t=fill[shade]",
        f"[shade]drawtext=fontfile={FONT_REG}:text='DESIGN INFRA':fontcolor=white@0.82:fontsize=24:x=70:y=94[brand]",
        f"[brand]drawtext=fontfile={FONT_BOLD}:text='{hook}':fontcolor=white:fontsize=60:line_spacing=13:x=70:y=1370:shadowcolor=black@0.65:shadowx=2:shadowy=2:alpha='{alpha(0.15,2.45)}'[a]",
        f"[a]drawtext=fontfile={FONT_BOLD}:text='{mid}':fontcolor=white:fontsize=44:line_spacing=11:x=70:y=1410:shadowcolor=black@0.60:shadowx=2:shadowy=2:alpha='{alpha(2.35,5.10)}'[b]",
        f"[b]drawtext=fontfile={FONT_BOLD}:text='{cta}':fontcolor=white:fontsize=43:line_spacing=10:x=70:y=1435:shadowcolor=black@0.60:shadowx=2:shadowy=2:alpha='{alpha(5.00,7.00)}'[c]",
        f"[c]drawtext=fontfile={FONT_REG}:text='{disclosure}':fontcolor=white@0.72:fontsize=23:x=70:y=1835[outv]",
    ])


def render(reel: dict, output: Path, image_url: str | None) -> None:
    source = image_url or str(reel.get("image", ""))
    if not source.startswith("https://"):
        raise SystemExit("source image must be HTTPS")
    output.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory() as td:
        src = Path(td) / "source.jpg"
        urllib.request.urlretrieve(source, src)
        w, h = dimensions(src)
        if h <= w or h / w < 1.55:
            raise SystemExit(f"QUALITY_GATE_FAIL: native portrait source required, got {w}x{h}")

        subprocess.run([
            "ffmpeg", "-y", "-loop", "1", "-i", str(src),
            "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo",
            "-filter_complex", filter_graph(reel),
            "-map", "[outv]", "-map", "1:a:0", "-t", "7",
            "-c:v", "libx264", "-preset", "medium", "-crf", "18",
            "-c:a", "aac", "-b:a", "128k", "-shortest", "-movflags", "+faststart",
            str(output)
        ], check=True)


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("reel_id")
    p.add_argument("--output")
    p.add_argument("--image-url")
    a = p.parse_args()
    reel = load_reel(a.reel_id)
    out = Path(a.output) if a.output else ROOT / "reels/output" / f"{a.reel_id}-v2.mp4"
    render(reel, out, a.image_url)
    print(json.dumps({
        "status": "RENDERED_QUALITY_RECOVERY_V2",
        "reel_id": a.reel_id,
        "motion_profile": "SMOOTH_SUBTLE_ROTATION",
        "rotation_degrees_total": 4.0,
        "rotation_start_degrees": -2.0,
        "rotation_end_degrees": 2.0,
        "max_zoom": 1.012,
        "random_drift": false,
        "handheld_shake": false,
        "synthetic_music": false,
        "founder_creative_approval": false,
        "public_action_performed": false,
        "output": str(out)
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
