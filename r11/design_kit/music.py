#!/usr/bin/env python3
"""Original background music for R11 reels, synthesised in code (no samples, no licences).

Each kit gets its own deterministic track from its id: key, chord progression, tempo and
groove vary; same id -> same audio bytes. Style: warm lounge / ambient house, built from
soft pads, an electric-piano arpeggio, round bass, a soft kick, clap and hats, with
sidechain ducking, a ping-pong delay and gentle saturation.

Licence class (aura music policy): AURA3_ORIGINAL_PROCEDURAL, commercial use allowed.
"""
from __future__ import annotations

import hashlib
import wave
from pathlib import Path

import numpy as np

SR = 44100
KEYS = [48, 50, 51, 53, 55, 57, 58]          # C, D, Eb, F, G, A, Bb (MIDI, octave 3)
# scale-degree progressions; (semitones from key root, chord quality)
PROGRESSIONS = [
    [(0, "maj7"), (9, "m7"), (5, "maj7"), (7, "dom7")],      # I  vi IV V
    [(9, "m7"), (5, "maj7"), (0, "maj7"), (7, "dom7")],      # vi IV I  V
    [(2, "m7"), (7, "dom7"), (0, "maj7"), (9, "m7")],        # ii V  I  vi
    [(0, "maj7"), (4, "m7"), (5, "maj7"), (7, "sus")],       # I  iii IV Vsus
    [(5, "maj7"), (7, "dom7"), (4, "m7"), (9, "m7")],        # IV V  iii vi
]
QUALITY = {"maj7": [0, 4, 7, 11], "m7": [0, 3, 7, 10], "dom7": [0, 4, 7, 10], "sus": [0, 5, 7, 10]}


def hz(midi):
    return 440.0 * 2 ** ((np.asarray(midi, dtype=float) - 69) / 12)


def params(seed_text: str) -> dict:
    h = hashlib.sha256(seed_text.encode()).digest()
    return {"key": KEYS[h[0] % len(KEYS)], "prog": PROGRESSIONS[h[1] % len(PROGRESSIONS)],
            "bpm": 88 + h[2] % 17, "arp_up": h[3] % 2 == 0, "hat_16th": h[4] % 3 == 0,
            "seed": int.from_bytes(h[5:9], "big")}


def env(n, attack, release, sr=SR):
    e = np.ones(n)
    a, r = min(n, int(attack * sr)), min(n, int(release * sr))
    if a:
        e[:a] = np.linspace(0, 1, a)
    if r:
        e[-r:] *= np.linspace(1, 0, r)
    return e


def lowpass(x, cutoff, sr=SR):
    """One-pole low-pass, vectorised in blocks via exponential smoothing."""
    a = 1 - np.exp(-2 * np.pi * cutoff / sr)
    y = np.empty_like(x)
    acc = 0.0
    for i in range(len(x)):          # ~0.1 s per 8 s stereo channel; fine for a reel
        acc += a * (x[i] - acc)
        y[i] = acc
    return y


def add(buf, start, sig):
    end = min(len(buf), start + len(sig))
    if end > start:
        buf[start:end] += sig[:end - start]


def pad_note(f, dur, detune_cents):
    t = np.arange(int(dur * SR)) / SR
    out = np.zeros_like(t)
    for k, amp in ((1, 1.0), (2, 0.35), (3, 0.18), (4, 0.08)):
        ff = f * k * 2 ** (detune_cents / 1200)
        out += amp * np.sin(2 * np.pi * ff * t + k)
    return out * env(len(t), 0.35, 0.5)


def ep_note(f, dur):
    t = np.arange(int(dur * SR)) / SR
    tone = (np.sin(2 * np.pi * f * t) * np.exp(-t * 3.2)
            + 0.45 * np.sin(2 * np.pi * 2 * f * t) * np.exp(-t * 5.5)
            + 0.12 * np.sin(2 * np.pi * 3 * f * t) * np.exp(-t * 9))
    tone *= 1 + 0.06 * np.sin(2 * np.pi * 5.5 * t)          # gentle tremolo
    return tone * env(len(t), 0.004, 0.08)


def bass_note(f, dur):
    t = np.arange(int(dur * SR)) / SR
    tone = np.sin(2 * np.pi * f * t) + 0.25 * np.sin(2 * np.pi * 2 * f * t)
    return tone * np.exp(-t * 1.6) * env(len(t), 0.01, 0.06)


def kick(dur=0.35):
    t = np.arange(int(dur * SR)) / SR
    f = 45 + 85 * np.exp(-t * 28)
    phase = 2 * np.pi * np.cumsum(f) / SR
    return np.sin(phase) * np.exp(-t * 11)


def noise_hit(rng, dur, decay, bright):
    n = rng.standard_normal(int(dur * SR))
    if bright:
        n = np.diff(n, prepend=0.0)                              # tilt towards highs
    t = np.arange(len(n)) / SR
    return n * np.exp(-t * decay)


def render(seed_text: str, seconds: float = 8.0, fade_out: float = 1.4) -> np.ndarray:
    """Return a float32 stereo array (n, 2) in -1..1."""
    p = params(seed_text)
    rng = np.random.default_rng(p["seed"])
    beat = 60.0 / p["bpm"]
    bar = 4 * beat
    n = int(seconds * SR)
    L, R = np.zeros(n + SR), np.zeros(n + SR)
    pad_l, pad_r, keys, bass, drums = (np.zeros(n + SR) for _ in range(5))
    duck = np.ones(n + SR)
    bars = int(np.ceil(seconds / bar)) + 1
    for b in range(bars):
        deg, q = p["prog"][b % len(p["prog"])]
        root = p["key"] + deg
        chord = [root + 12 + iv for iv in QUALITY[q]]            # pad voicing in octave 4
        start = int(b * bar * SR)
        for m in chord:
            add(pad_l, start, pad_note(hz(m), bar + 0.5, -5) * 0.11)
            add(pad_r, start, pad_note(hz(m), bar + 0.5, +5) * 0.11)
        # electric-piano arpeggio in 8ths across two octaves
        arp = chord + [m + 12 for m in chord[:2]]
        if not p["arp_up"]:
            arp = arp[::-1]
        for k in range(8):
            m = arp[k % len(arp)]
            vel = 0.20 if k % 2 == 0 else 0.13
            add(keys, start + int(k * beat / 2 * SR), ep_note(hz(m), beat * 1.6) * vel)
        # bass: root on 1, fifth/root on the "and" of 2, root on 3
        bass_root = p["key"] - 12 + deg
        for when, m, d in ((0, bass_root, 1.4 * beat), (1.5, bass_root + 7, 0.5 * beat), (2, bass_root, 1.8 * beat)):
            add(bass, start + int(when * beat * SR), bass_note(hz(m), d) * 0.34)
        # drums: soft kick 1 & 3 (plus a ghost on 4-and), clap 2 & 4, hats
        for k in (0, 2):
            s = start + int(k * beat * SR)
            add(drums, s, kick() * 0.55)
            dl = min(len(duck) - s, int(0.32 * SR))
            if dl > 0:
                duck[s:s + dl] = np.minimum(duck[s:s + dl], 1 - 0.45 * np.exp(-np.arange(dl) / SR * 9))
        add(drums, start + int(3.5 * beat * SR), kick() * 0.25)
        for k in (1, 3):
            add(drums, start + int(k * beat * SR), lowpass(noise_hit(rng, 0.18, 22, False), 3500) * 0.16)
        step = 0.25 if p["hat_16th"] else 0.5
        for k in range(int(4 / step)):
            v = 0.022 if (k * step) % 1 else 0.014
            add(drums, start + int(k * step * beat * SR), noise_hit(rng, 0.05, 70, True) * v)
    pad_l, pad_r = lowpass(pad_l, 2200) * duck, lowpass(pad_r, 2200) * duck
    # ping-pong delay on the keys (3/8 note)
    d = int(0.75 * beat * SR)
    keys_l, keys_r = keys.copy(), keys.copy()
    keys_r[d:] += 0.32 * keys[:-d]
    keys_l[2 * d:] += 0.20 * keys[:-2 * d]
    L = pad_l + 0.9 * keys_l + bass + drums
    R = pad_r + 0.9 * keys_r + bass + drums
    mix = np.stack([L[:n], R[:n]], axis=1)
    mix = np.tanh(1.3 * mix) / np.tanh(1.3)                     # gentle glue
    mix /= max(1e-9, np.abs(mix).max()) / 0.85
    fade_in = np.minimum(1, np.arange(n) / (0.25 * SR))
    fade_end = np.clip((n - np.arange(n)) / (fade_out * SR), 0, 1)
    return (mix * (fade_in * fade_end)[:, None]).astype(np.float32)


def write_wav(path: Path, audio: np.ndarray) -> None:
    pcm = (np.clip(audio, -1, 1) * 32767).astype("<i2")
    with wave.open(str(path), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm.tobytes())


if __name__ == "__main__":
    import sys
    write_wav(Path(sys.argv[2] if len(sys.argv) > 2 else "music.wav"), render(sys.argv[1] if len(sys.argv) > 1 else "demo"))
