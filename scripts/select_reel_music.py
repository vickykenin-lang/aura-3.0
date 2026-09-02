#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load(path: str):
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def license_ok(track: dict) -> bool:
    return bool(
        track.get("commercial_use_allowed") is True
        and str(track.get("license_type", "")).strip()
        and str(track.get("license_evidence", "")).strip()
        and str(track.get("source_reference", "")).strip()
    )


def score(track: dict, signal: dict) -> float:
    value = 0.0
    if track.get("genre") == signal.get("genre"):
        value += 5.0
    if signal.get("mood") in (track.get("moods") or []):
        value += 3.0
    if track.get("energy") == signal.get("energy"):
        value += 1.0
    try:
        value += max(0.0, 2.0 - abs(float(track.get("bpm", 0)) - float(signal.get("tempo_bpm", 0))) / 10.0)
    except (TypeError, ValueError):
        pass
    return value


def select_track(signal: dict, catalog: dict) -> dict | None:
    eligible = [track for track in catalog.get("tracks", []) if license_ok(track)]
    if not eligible:
        return None
    return max(eligible, key=lambda item: score(item, signal))


def main() -> int:
    catalog = load("data/reels_music_catalog.json")
    signals = load("data/reels_trend_signals.json").get("signals", [])
    signal = signals[0] if signals else {}
    selected = select_track(signal, catalog)
    result = {
        "status": "LICENSED_TRACK_SELECTED" if selected else "NO_LICENSED_TRACK_AVAILABLE",
        "trend_signal": signal,
        "selected_track": selected,
        "public_action_performed": False,
    }
    out = ROOT / "evaluation/results/reels_music_selection.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
