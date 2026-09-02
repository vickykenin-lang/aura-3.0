#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path


def probe(path: Path) -> dict:
    cmd = [
        "ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)
    ]
    return json.loads(subprocess.check_output(cmd, text=True))


def qualify(path: Path) -> dict:
    data = probe(path)
    streams = data.get("streams", [])
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
    duration = float((data.get("format") or {}).get("duration") or 0)
    checks = {
        "duration_5_to_10": 5.0 <= duration <= 10.0,
        "video_stream_present": bool(video),
        "audio_stream_present": bool(audio),
        "portrait_1080x1920": bool(video and int(video.get("width", 0)) == 1080 and int(video.get("height", 0)) == 1920),
        "h264_video": bool(video and video.get("codec_name") == "h264"),
        "aac_audio": bool(audio and audio.get("codec_name") == "aac"),
    }
    return {
        "status": "TECHNICAL_PASS" if all(checks.values()) else "TECHNICAL_FAIL",
        "duration_seconds": duration,
        "checks": checks,
        "public_action_performed": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("path")
    parser.add_argument("--output")
    args = parser.parse_args()
    result = qualify(Path(args.path))
    if args.output:
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output).write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))
    return 0 if result["status"] == "TECHNICAL_PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
