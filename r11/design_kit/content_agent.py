#!/usr/bin/env python3
"""R11 content agent (A1 concept designer + A2 kit author), unattended.

Every run (hourly, inside the autopost workflow) it keeps the next 48 h of the schedule
filled: 07:00 IST = reel, 19:00 IST = carousel, one new concept per day.

For a missing day it:
  1. picks a room + style from a fixed rotation (no repeats inside 12 days),
  2. asks the text model for a short brief (title, problem, 3 fixes, caption body),
     validated by code: lengths, no prices/offers/links/phone numbers,
  3. generates the concept image (FLUX.2 klein 9B) and rejects it unless OCR finds no
     text and the vision model says: photorealistic, right room, no distortion, no people,
     no text/logos, premium designer look, quality >= 8, AND every item of that room's
     designer checklist (DESIGN_RULES: must-haves and must-nots) passes (max 3 attempts),
  4. picks 3 detail crops (edge density) and lets the vision model name each one,
  5. picks up to 6 material swatches and lets the vision model label them from a fixed
     vocabulary; the colour split is computed with k-means (no AI),
  6. writes the kit spec (template auto_v1), the image and the schedule items.

Captions, the WhatsApp number, CTA and disclosure are composed by code, never by a model.
AI runs on the designinfra-content-studio Worker; the GitHub OIDC token is the only credential.
"""
from __future__ import annotations

import base64
import hashlib
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from datetime import date, datetime, time as dtime, timedelta, timezone
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

HERE = Path(__file__).resolve().parent
STUDIO = "https://designinfra-content-studio.vickykenin.workers.dev"
AUDIENCE = "designinfra-content-studio"
IST = timezone(timedelta(hours=5, minutes=30))
SLOTS = {"am": (dtime(7, 0), "reel"), "pm": (dtime(19, 0), "carousel")}
HORIZON = timedelta(hours=48)
LEAD = timedelta(hours=2)          # never create content for a slot closer than this
MAX_IMAGE_ATTEMPTS = 3

SCHEDULE = "r11/design_kit/schedule.json"
SPECS = "r11/design_kit/kits"
CONCEPTS = "campaigns/r11/concepts"
LOG = "r11/design_kit/concepts.json"
DRAFTS = "r11/design_kit/drafts"   # brief + accepted image kept between runs, so a retry reuses them
MAX_DRAFT_FAILURES = 3

ROOMS = [
    ("living room", "Living room"), ("master bedroom", "Bedroom"), ("modular kitchen", "Kitchen"),
    ("dining area", "Dining"), ("kids bedroom", "Kids room"), ("bedroom wardrobe wall", "Wardrobe"),
    ("pooja unit corner in a living area", "Pooja unit"), ("home office nook", "Home office"),
    ("balcony sit-out", "Balcony"), ("entrance foyer", "Foyer"), ("TV unit wall in a living room", "TV wall"),
    ("guest bedroom", "Guest room"),
]
# What an interior designer insists on for each room: used in the brief, the image prompt and a
# checklist the vision model must pass item by item (a premium-looking image is not enough).
DESIGN_RULES = {
    "Living room": {"must": ["sofa seating arranged around a clear focal point (TV or feature wall)",
                             "a centre table within reach of the sofa", "a clear walkway through the room",
                             "layered lighting: cove or ceiling light plus a floor or table lamp"],
                    "avoid": ["a bed", "furniture blocking the walkway", "a TV placed directly opposite a bright window"]},
    "Bedroom": {"must": ["a double bed with a headboard as the focal point", "bedside tables on both sides of the bed",
                         "a wardrobe or closed storage", "soft warm bedside lighting"],
                "avoid": ["a mirror directly facing the bed", "a TV mounted above the headboard",
                          "a crowded study desk next to the bed"]},
    "Kitchen": {"must": ["a hob with a chimney above it", "a sink", "base cabinets and wall cabinets",
                         "under-cabinet task lighting", "a usable countertop work area between hob and sink"],
                "avoid": ["a bed or sofa", "the hob placed directly under a window", "curtains next to the hob"]},
    "Dining": {"must": ["a dining table with chairs that have space to pull out",
                        "a pendant light centred over the dining table", "a sideboard or crockery unit"],
               "avoid": ["a bed", "a dining table pushed against a wall", "chairs blocking the walkway"]},
    "Kids room": {"must": ["a bed for the child (single, bunk or day bed)",
                           "a child-height study desk with a kid-size chair",
                           "low open storage a child can reach for toys and books",
                           "rounded edges and durable, easy-clean finishes"],
                  "avoid": ["a crystal or glass chandelier", "glass vases or fragile decor at child height",
                            "an adult office chair on castors", "a white high-pile shag rug"]},
    "Wardrobe": {"must": ["a floor-to-ceiling wardrobe with shutters as the focus", "a bed visible in the room",
                          "profile or internal lighting on the wardrobe"],
                 "avoid": ["a wardrobe blocking a window", "a mirror directly facing the bed"]},
    "Pooja unit": {"must": ["a dedicated pooja unit (mandir) with a back panel and soft lighting",
                            "a ledge or drawer for pooja items",
                            "the deity area at or above eye level of a seated person"],
                   "avoid": ["a pooja unit under a staircase or a beam", "clutter or unrelated items around the mandir",
                             "a pooja unit inside a wardrobe or next to a toilet door"]},
    "Home office": {"must": ["a desk at the right working height", "an ergonomic chair", "task lighting at the desk",
                             "closed storage for files"],
                    "avoid": ["a bed in the frame", "the desk facing a bright window head-on"]},
    "Balcony": {"must": ["weather-proof outdoor seating", "plants in planters", "an outdoor floor finish such as deck tiles",
                         "a safety railing"],
                "avoid": ["an indoor fabric sofa", "a chandelier", "a rug that cannot get wet"]},
    "Foyer": {"must": ["a shoe cabinet or console", "a mirror", "a seating ledge or bench", "a clear entry path"],
              "avoid": ["a bed", "a dining table"]},
    "TV wall": {"must": ["a TV unit wall with closed storage below the TV", "concealed wiring",
                         "the TV at seated eye level", "accent lighting on the wall panel"],
                "avoid": ["a TV mounted too high", "a TV directly opposite a bright window"]},
    "Guest room": {"must": ["a bed with a bedside table", "a compact wardrobe or luggage space", "a reading light"],
                   "avoid": ["an office desk dominating the room", "a crystal chandelier in a small room"]},
}


def checklist(label: str) -> list[str]:
    r = DESIGN_RULES[label]
    return [f"Shows {m}" for m in r["must"]] + [f"Does NOT show {a}" for a in r["avoid"]]


STYLES = ["warm modern", "Japandi", "contemporary Indian", "modern classic", "soft minimal",
          "earthy natural", "art deco luxe", "mid-century modern"]
MATERIALS = ["Walnut wood", "Oak wood", "Teak wood", "Ash wood", "Marble", "Travertine", "Granite",
             "Terrazzo", "Matte plaster", "Textured plaster", "Painted wall", "Wallpaper", "Linen fabric",
             "Boucle fabric", "Velvet", "Leather", "Cotton fabric", "Jute", "Wool rug", "Brass",
             "Black metal", "Chrome", "Glass", "Mirror", "Cane weave", "Rattan", "Concrete",
             "Ceramic tile", "Vitrified tile", "Laminate", "Lacquer finish", "Fluted panel",
             "Stone cladding", "Sheer curtain", "Wood flooring"]
USES = ["Wall", "Floor", "Ceiling", "Sofa", "Bed", "Cabinet", "Wardrobe", "Counter", "Table", "Chair",
        "Curtain", "Rug", "Lighting", "Decor", "Headboard", "Shelf", "Panel", "Door", "Backsplash"]
COLOURS = {"Ivory": (238, 230, 214), "Cream": (226, 212, 186), "Beige": (205, 184, 156), "Sand": (190, 165, 128),
           "Taupe": (140, 124, 110), "Walnut": (96, 62, 40), "Espresso": (58, 40, 30), "Charcoal": (55, 56, 60),
           "Grey": (150, 150, 150), "White": (246, 246, 244), "Black": (22, 22, 22), "Sage": (150, 165, 140),
           "Olive": (110, 110, 70), "Terracotta": (186, 104, 72), "Navy": (40, 50, 82), "Teal": (40, 108, 108),
           "Blush": (226, 190, 180), "Mustard": (200, 160, 60), "Brass": (176, 140, 72), "Caramel": (170, 112, 64)}
BANNED = re.compile(r"(₹|\brs\.?\s*\d|\blakh|\bcrore|guarantee|discount|\boffer\b|https?:|www\.|@|\d{6,}|%)", re.I)
BRAND = {"name": "DESIGN INFRA", "handle": "@designinfra.interiors",
         "whatsapp_display": "+91 82879 00789", "disclosure": "AI-generated design concept"}


class AgentError(Exception):
    pass


def load(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def save(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


# ---------------- studio client ----------------
class Studio:
    """Calls the content-studio Worker with a fresh GitHub OIDC token per request."""

    def __init__(self, base=STUDIO):
        self.base = base

    def _token(self) -> str:
        url, req_token = os.environ.get("ACTIONS_ID_TOKEN_REQUEST_URL"), os.environ.get("ACTIONS_ID_TOKEN_REQUEST_TOKEN")
        if not url or not req_token:
            raise AgentError("OIDC_UNAVAILABLE (needs GitHub Actions with id-token: write)")
        req = urllib.request.Request(f"{url}&audience={AUDIENCE}", headers={"Authorization": f"bearer {req_token}"})
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read().decode())["value"]

    def _post(self, path: str, body: dict) -> dict:
        req = urllib.request.Request(self.base + path, data=json.dumps(body).encode(), method="POST",
                                     headers={"Content-Type": "application/json",
                                              "User-Agent": "designinfra-content-agent/1.0",
                                              "Authorization": f"Bearer {self._token()}"})
        try:
            with urllib.request.urlopen(req, timeout=180) as r:
                return json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            raw = e.read().decode(errors="replace")
            try:
                detail = json.loads(raw)
            except ValueError:
                detail = {}
            raise AgentError(f"STUDIO_{e.code}:{detail.get('error')}:{detail.get('why') or detail.get('detail', '')}"
                             f"{'' if detail else ':' + raw[:80]}") from None
        except urllib.error.URLError:
            raise AgentError("STUDIO_NETWORK") from None

    def text(self, messages, schema=None, max_tokens=900) -> str:
        body = {"messages": messages, "max_tokens": max_tokens, "temperature": 0.8}
        if schema:
            body["json_schema"] = schema
        return self._post("/text", body)["text"]

    def vision(self, prompt, images: list[bytes], schema=None, max_tokens=500) -> str:
        body = {"prompt": prompt, "images": [base64.b64encode(b).decode() for b in images], "max_tokens": max_tokens}
        if schema:
            body["json_schema"] = schema
        return self._post("/vision", body)["text"]

    def image(self, prompt, width=1024, height=1280) -> bytes:
        return base64.b64decode(self._post("/image", {"prompt": prompt, "width": width, "height": height})["image_b64"])


def parse_json(text: str) -> dict:
    m = re.search(r"\{.*\}", str(text), re.S)
    if not m:
        raise AgentError("MODEL_NO_JSON:" + repr(str(text)[:160]))
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        raise AgentError("MODEL_BAD_JSON") from None


def jpeg(img: Image.Image, quality=90, max_side=None) -> bytes:
    if max_side and max(img.size) > max_side:
        img = img.copy()
        img.thumbnail((max_side, max_side), Image.LANCZOS)
    buf = io.BytesIO()
    img.convert("RGB").save(buf, "JPEG", quality=quality)
    return buf.getvalue()


# ---------------- planning ----------------
def topic_for(day: date) -> tuple[str, str, str]:
    n = (day - date(2026, 1, 1)).days
    room, label = ROOMS[n % len(ROOMS)]
    style = STYLES[(n * 3 + n // len(ROOMS)) % len(STYLES)]
    return room, label, style


def missing_days(sched: dict, now: datetime) -> list[tuple[date, list[str]]]:
    """Days (IST) inside the horizon with at least one free slot, with the slots to fill."""
    taken = {datetime.fromisoformat(i["at"]).astimezone(IST).replace(second=0, microsecond=0) for i in sched["items"]}
    kits = {i["kit"] for i in sched["items"]}
    out = []
    today = now.astimezone(IST).date()
    for k in range(0, 4):
        day = today + timedelta(days=k)
        if f"auto-{day:%Y%m%d}" in kits:
            continue
        free = [slot for slot, (t, _) in SLOTS.items()
                if datetime.combine(day, t, IST) >= now + LEAD and datetime.combine(day, t, IST) not in taken]
        # a day is planned once its first free slot is inside the horizon; all its free slots are filled together
        if free and datetime.combine(day, SLOTS[free[0]][0], IST) <= now + HORIZON:
            out.append((day, free))
    return out


BRIEF_SCHEMA = {"type": "object", "properties": {
    "title": {"type": "string"}, "subtitle": {"type": "string"}, "scene": {"type": "string"},
    "fix_title": {"type": "string"}, "problem": {"type": "string"},
    "solutions": {"type": "array", "items": {"type": "string"}}, "reel_line": {"type": "string"},
    "caption_body": {"type": "string"}, "hashtags": {"type": "array", "items": {"type": "string"}}},
    "required": ["title", "subtitle", "scene", "fix_title", "problem", "solutions", "reel_line", "caption_body", "hashtags"]}
LIMITS = {"title": 26, "subtitle": 66, "scene": 700, "fix_title": 30, "problem": 115, "reel_line": 36, "caption_body": 280}


def check_brief(b: dict) -> list[str]:
    issues = []
    for k, n in LIMITS.items():
        v = str(b.get(k, "")).strip()
        if not v:
            issues.append(f"{k} is empty")
        elif len(v) > n:
            issues.append(f"{k} is {len(v)} chars, max {n}")
    sols = b.get("solutions")
    if not isinstance(sols, list) or len(sols) != 3:
        issues.append("solutions must have exactly 3 items")
    else:
        for s in sols:
            if not str(s).strip() or len(str(s)) > 64:
                issues.append(f"solution too long or empty (max 64): {str(s)[:40]}")
    for k in ("title", "subtitle", "fix_title", "problem", "reel_line", "caption_body"):
        if BANNED.search(str(b.get(k, ""))):
            issues.append(f"{k} mentions a price, offer, link, phone number or percentage")
    for s in b.get("solutions") or []:
        if BANNED.search(str(s)):
            issues.append("a solution mentions a price, offer, link or number")
    return issues


def write_brief(studio, room, label, style) -> dict:
    system = ("You are the content designer for Design Infra, a residential interior design studio in Delhi NCR. "
              "Audience: Indian homeowners of 2BHK/3BHK apartments. Never mention prices, budgets, discounts, offers, "
              "guarantees, timelines, phone numbers, links, brands or competitors. Return JSON only.")
    user = (f"Create one Instagram design concept: a {style} {room} for a Delhi NCR apartment.\n"
            "Fields (character limits are hard limits):\n"
            "- title: max 26 chars, English, catchy, e.g. 'Warm modern luxury'\n"
            "- subtitle: max 66 chars, English, what makes the space special\n"
            "- scene: max 700 chars, a precise visual description for an image generator of a premium, "
            "professionally designed and fully styled room (never a plain or rental-looking room). It must name: "
            "the ceiling design (false ceiling, cove or profile lighting), a statement light, one feature wall "
            "treatment (panelling, fluting, stone, wallpaper or texture), flooring, the main furniture, soft "
            "furnishings (rug, curtains, cushions) and decor (art, plants, vases). It must also show the 3 solutions. "
            "Realistic for an Indian apartment. No people, no text.\n"
            f"- fix_title: max 30 chars, English headline for a problem-solution slide about this {label.lower()}\n"
            "- problem: max 115 chars, Hinglish, a specific everyday problem homeowners face in this room "
            "(e.g. 'Dining chhota hai, kitchen se aate-jaate chairs se takkar hoti hai')\n"
            f"- the room MUST have: {'; '.join(DESIGN_RULES[label]['must'])}. It must NOT have: "
            f"{'; '.join(DESIGN_RULES[label]['avoid'])}. The scene must describe every must-have item.\n"
            "- solutions: exactly 3 items, max 64 chars each, English, concrete design moves visible in the scene "
            "(e.g. 'Round 4-seater frees the walkway', 'Wall bench saves floor space', 'Pendant marks the "
            "dining zone'); never vague phrases like 'optimized size' or 'calming palette'\n"
            "- reel_line: max 36 chars, three key materials joined by ' · ', e.g. 'Oak · linen · brass'\n"
            "- caption_body: max 280 chars, Hinglish, describe the look and give one practical tip\n"
            "- hashtags: 3 to 5 words without '#', CamelCase, about the room and style")
    messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    for attempt in range(3):
        brief = parse_json(studio.text(messages, BRIEF_SCHEMA))
        issues = check_brief(brief)
        if not issues:
            return {k: (v.strip() if isinstance(v, str) else v) for k, v in brief.items()}
        messages = messages[:2] + [{"role": "assistant", "content": json.dumps(brief, ensure_ascii=False)},
                                   {"role": "user", "content": "Fix these problems and return the full JSON again: "
                                    + "; ".join(issues)}]
    raise AgentError("BRIEF_INVALID:" + "; ".join(issues)[:200])


# ---------------- image QA ----------------
def ocr_words(img: Image.Image) -> list[str]:
    with tempfile.NamedTemporaryFile(suffix=".png") as f:
        img.convert("L").save(f.name)
        r = subprocess.run(["tesseract", f.name, "stdout", "--psm", "11", "tsv"], capture_output=True, text=True)
    if r.returncode != 0:
        raise AgentError("OCR_UNAVAILABLE")
    words = []
    for line in r.stdout.splitlines()[1:]:
        cols = line.split("\t")
        if len(cols) == 12 and cols[11].strip():
            try:
                conf = float(cols[10])
            except ValueError:
                continue
            w = cols[11].strip()
            if conf >= 80 and re.fullmatch(r"[A-Za-z]{3,}", w) and re.search(r"[aeiouAEIOU]", w):
                words.append(w)
    return words


QA_SCHEMA = {"type": "object", "properties": {
    "photorealistic": {"type": "boolean"}, "matches_room": {"type": "boolean"},
    "distorted_or_broken_objects": {"type": "boolean"}, "people_present": {"type": "boolean"},
    "text_or_logos": {"type": "boolean"}, "quality": {"type": "integer"}},
    "required": ["photorealistic", "matches_room", "distorted_or_broken_objects", "people_present", "text_or_logos", "quality"]}


def design_check(studio, img: Image.Image, room: str, label: str) -> list[str]:
    """Item-by-item designer checklist; returns the items the image fails."""
    items = checklist(label)
    numbered = "\n".join(f"{i}. {t}" for i, t in enumerate(items, 1))
    out = parse_json(studio.vision(
        f"You are a senior interior designer checking a design concept of a {room} before it is published. "
        f"Look carefully at the image and answer each designer checklist item with true or false:\n{numbered}\n"
        f'Reply with one JSON object only: {{"checks": [true or false for each item, in order, exactly {len(items)} values]}}.',
        [jpeg(img, 88, 1024)]))
    checks = out.get("checks")
    if not isinstance(checks, list) or len(checks) != len(items):
        return ["CHECKLIST_UNREADABLE"]
    return [t for t, ok in zip(items, checks) if ok is not True]


def qa_image(studio, img: Image.Image, room: str, label: str | None = None) -> dict:
    words = ocr_words(img)
    if len(words) >= 2:
        return {"ok": False, "why": "TEXT_IN_IMAGE:" + " ".join(words[:5])}
    qa = parse_json(studio.vision(
        f"You are a strict quality checker for an interior design studio's Instagram. The image should show a {room}. "
        "Judge it and return JSON: photorealistic (looks like a real photo), matches_room, distorted_or_broken_objects "
        "(melted, warped or impossible furniture, broken geometry), people_present, text_or_logos (any letters, "
        "signage, watermark), premium_designer_look (true only if it looks professionally designed and styled: "
        "designed ceiling and lighting, a feature wall or rich materials, curated decor; false for a plain, bare or "
        "rental-looking room), quality (0-10 for a premium interior design studio's post; be strict). Reply with one "
        'JSON object only, like {"photorealistic": true, "matches_room": true, "distorted_or_broken_objects": false, '
        '"people_present": false, "text_or_logos": false, "premium_designer_look": true, "quality": 8}.',
        [jpeg(img, 88, 1024)]))
    ok = (qa.get("photorealistic") is True and qa.get("matches_room") is True
          and qa.get("distorted_or_broken_objects") is False and qa.get("people_present") is False
          and qa.get("text_or_logos") is False and qa.get("premium_designer_look") is True
          and isinstance(qa.get("quality"), int) and qa["quality"] >= 8)
    if not ok:
        return {"ok": False, "why": "VISION_REJECTED", "qa": qa}
    if label:
        failed = design_check(studio, img, room, label)
        if failed:
            return {"ok": False, "why": "DESIGN_RULES_FAILED:" + " | ".join(failed)[:200], "qa": qa}
    return {"ok": True, "why": "", "qa": qa}


def make_image(studio, room, style, scene, label=None) -> tuple[Image.Image, list]:
    lead, avoid = "", ""
    if label:   # the image model weighs early words most: the must-haves go first, the must-nots last
        r = DESIGN_RULES[label]
        lead = " featuring " + ", ".join(r["must"])
        avoid = " No " + ", no ".join(a.removeprefix("a ").removeprefix("an ") for a in r["avoid"]) + "."
    prompt = (f"Award-winning interior design portfolio photograph of a premium {style} {room}{lead}, in a modern "
              f"Delhi NCR apartment, designed and styled by a luxury interior design studio. {scene}{avoid} Designer false "
              "ceiling with warm cove lighting, layered textures, curated decor. Eye-level wide-angle architectural "
              "photography, vertical composition, natural daylight with warm ambient lighting, realistic proportions "
              "and materials, high detail, sharp focus. No people. Absolutely no text, letters, logos or watermarks.")
    attempts = []
    for _ in range(MAX_IMAGE_ATTEMPTS):
        img = Image.open(io.BytesIO(studio.image(prompt))).convert("RGB")
        res = qa_image(studio, img, room, label)
        attempts.append({"ok": res["ok"], "why": res["why"], "qa": res.get("qa")})
        if res["ok"]:
            return img, attempts
    raise AgentError("IMAGE_REJECTED:" + ",".join(a["why"] for a in attempts))


# ---------------- automatic slide content ----------------
def _integral(a: np.ndarray) -> np.ndarray:
    return np.pad(a.cumsum(0).cumsum(1), ((1, 0), (1, 0)))


def _box_sum(ii, x0, y0, x1, y1):
    return ii[y1, x1] - ii[y0, x1] - ii[y1, x0] + ii[y0, x0]


def _iou(a, b):
    ix = max(0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    return inter / ((a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter)


def edge_map(img: Image.Image) -> np.ndarray:
    return np.asarray(img.convert("L").filter(ImageFilter.FIND_EDGES), dtype=np.float64) / 255.0


def detail_candidates(img: Image.Image, n=6) -> list[list[int]]:
    w, h = img.size
    bw = int(w * 0.46)
    bh = int(bw / 1.507)
    ii = _integral(edge_map(img))
    cands = []
    for y in range(int(h * 0.08), h - bh, 32):
        for x in range(0, w - bw + 1, 32):
            cands.append((_box_sum(ii, x, y, x + bw, y + bh) / (bw * bh), [x, y, x + bw, y + bh]))
    cands.sort(key=lambda c: -c[0])
    chosen = []
    for _, box in cands:
        if all(_iou(box, c) < 0.05 for c in chosen):
            chosen.append(box)
        if len(chosen) == n:
            break
    return chosen


DETAIL_SCHEMA = {"type": "object", "properties": {
    "clear_design_detail": {"type": "boolean"}, "title": {"type": "string"}, "why": {"type": "string"}},
    "required": ["clear_design_detail", "title", "why"]}


def write_details(studio, img, label) -> list[dict]:
    items = []
    for box in detail_candidates(img):
        crop = img.crop(tuple(box))
        try:
            d = _detail_reply(studio, crop, label)
        except AgentError:
            continue
        title, why = str(d.get("title", "")).strip(), str(d.get("why", "")).strip()
        if d.get("clear_design_detail") is True and 3 <= len(title) <= 34 and 10 <= len(why) <= 100 \
                and not BANNED.search(title + why) and not any(_same_detail(title, i["title"]) for i in items):
            items.append({"box": box, "title": title, "text": why})
        if len(items) == 3:
            return items
    raise AgentError(f"DETAILS_NOT_ENOUGH:{len(items)}")


STOP = {"a", "an", "the", "and", "with", "of", "for", "in", "on", "to"}


def _words(title: str) -> set[str]:
    return {w.rstrip("s") for w in re.findall(r"[a-z]+", title.lower()) if w not in STOP}


def _same_detail(a: str, b: str) -> bool:
    """'Fluted panel wardrobe' vs 'Fluted wardrobe panels' -> same detail, keep only one."""
    wa, wb = _words(a), _words(b)
    return bool(wa and wb) and len(wa & wb) / min(len(wa), len(wb)) >= 0.6


def _detail_reply(studio, crop, label) -> dict:
    return parse_json(studio.vision(
            f"This is a close crop from an interior design concept of a {label.lower()}. If it clearly shows one "
            "copyable design detail (lighting, joinery, material, storage, furniture, styling), name it. Return JSON: "
            "clear_design_detail, title (max 34 chars, English, e.g. 'Fluted oak wardrobe shutters'), why (max 100 "
            "chars, English, why it works for an Indian home). Describe only what is visible. Reply with one JSON "
            'object only, like {"clear_design_detail": true, "title": "...", "why": "..."}.',
            [jpeg(crop, 88, 800)]))


def swatch_candidates(img: Image.Image, n=6) -> list[list[int]]:
    """Textured, evenly lit squares with colours as different from each other as possible."""
    w, h = img.size
    s = 128
    arr = np.asarray(img, dtype=np.float64)
    ii = _integral(edge_map(img))
    cands = []
    for y in range(int(h * 0.12), h - s + 1, 48):
        for x in range(0, w - s + 1, 48):
            e = _box_sum(ii, x, y, x + s, y + s) / (s * s)
            patch = arr[y:y + s, x:x + s].reshape(-1, 3)
            mean, spread = patch.mean(0), patch.std(0).mean()
            if 0.015 < e < 0.14 and 40 < mean.mean() < 232 and spread < 38:
                cands.append((e, mean, [x, y, x + s, y + s]))
    if len(cands) < n:
        raise AgentError("SWATCHES_NOT_ENOUGH")
    cands.sort(key=lambda c: c[0])
    picks = [cands[len(cands) // 2]]
    while len(picks) < n:
        best, best_d = None, 0.0
        for c in cands:
            if any(_iou(c[2], p[2]) > 0 for p in picks):
                continue
            d = min(float(((c[1] - p[1]) ** 2).sum()) for p in picks)
            if d > best_d:
                best, best_d = c, d
        if best is None or best_d < 150:
            break
        picks.append(best)
    return [p[2] for p in picks]


def _kmeans(x: np.ndarray, k: int, iters=12) -> np.ndarray:
    order = np.argsort(x.mean(1))
    centers = x[order[np.linspace(0, len(x) - 1, k).astype(int)]].copy()
    for _ in range(iters):
        lab = np.argmin(((x[:, None] - centers[None]) ** 2).sum(2), 1)
        for j in range(k):
            if (lab == j).any():
                centers[j] = x[lab == j].mean(0)
    return centers


SWATCH_SCHEMA = {"type": "object", "properties": {"swatches": {"type": "array", "items": {"type": "object", "properties": {
    "letter": {"type": "string"}, "material": {"type": "string", "enum": MATERIALS}, "use": {"type": "string", "enum": USES},
    "confident": {"type": "boolean"}}, "required": ["letter", "material", "use", "confident"]}}}, "required": ["swatches"]}


def write_materials(studio, img) -> list[dict]:
    boxes = swatch_candidates(img)
    sheet = Image.new("RGB", (3 * 260, 2 * 290), (255, 255, 255))
    dr = ImageDraw.Draw(sheet)
    try:
        lf = ImageFont.truetype("/usr/share/fonts/opentype/inter/Inter-Bold.otf", 26)
    except OSError:
        lf = ImageFont.load_default()
    letters = "ABCDEF"
    for i, b in enumerate(boxes):
        x, y = (i % 3) * 260, (i // 3) * 290
        sheet.paste(img.crop(tuple(b)).resize((250, 250)), (x + 5, y + 35))
        dr.text((x + 10, y + 2), letters[i], fill=(0, 0, 0), font=lf)
    out = parse_json(studio.vision(
        "The first image is a contact sheet of square swatches cut from the second image, an interior design "
        "concept. For each lettered swatch choose the closest material and where it is used in the room, only from "
        "the allowed lists. Set confident=false if the swatch is unclear. Return JSON {swatches:[{letter, material, "
        "use, confident}]}. Allowed materials: " + ", ".join(MATERIALS) + ". Allowed uses: " + ", ".join(USES)
        + ". Reply with the JSON object only.", [jpeg(sheet, 90), jpeg(img, 85, 1024)], None, 700))
    tiles, seen = [], set()
    for s in out.get("swatches", []):
        letter = str(s.get("letter", "")).strip().upper()[:1]
        if letter in letters[:len(boxes)] and s.get("confident") is True and s.get("material") in MATERIALS \
                and s.get("use") in USES and s["material"] not in seen:
            seen.add(s["material"])
            tiles.append({"name": s["material"], "use": s["use"], "box": boxes[letters.index(letter)]})
    if len(tiles) < 3:
        raise AgentError(f"MATERIALS_NOT_ENOUGH:{len(tiles)}")
    return tiles[:6]


def colour_split(img: Image.Image) -> list[dict]:
    small = np.asarray(img.resize((64, 80)), dtype=np.float64).reshape(-1, 3)
    centers = _kmeans(small, 3)
    lab = np.argmin(((small[:, None] - centers[None]) ** 2).sum(2), 1)
    counts = np.bincount(lab, minlength=3)
    order = np.argsort(-counts)
    pct = [int(round(100 * counts[i] / counts.sum())) for i in order]
    pct[0] += 100 - sum(pct)
    out, used = [], set()
    for p, i in zip(pct, order):
        rgb = [int(v) for v in centers[i]]
        name = min(COLOURS, key=lambda n: sum((a - b) ** 2 for a, b in zip(COLOURS[n], rgb)))
        if name in used:
            name = ("Deep " if sum(rgb) < sum(COLOURS[name]) else "Light ") + name.lower()
        used.add(name)
        out.append({"pct": p, "name": name, "rgb": rgb})
    return out


# ---------------- spec ----------------
def captions(brief: dict) -> tuple[str, str]:
    tags = ["DesignInfra", "DelhiNCRInteriors"]
    for t in brief.get("hashtags") or []:
        t = re.sub(r"[^A-Za-z0-9]", "", str(t))
        if 3 <= len(t) <= 30 and t not in tags:
            tags.append(t)
    tags = " ".join("#" + t for t in tags[:7])
    cta = f"Apne ghar ke liye free consultation chahiye? Bio link par details share karein ya WhatsApp karein: {BRAND['whatsapp_display']}"
    disclosure = BRAND["disclosure"] + " for inspiration."
    carousel = (f"{brief['title']} ✨\n\n{brief['caption_body']}\n\nSwipe karein: problem → solution, 3 details to copy "
                f"aur material palette 👉\n\n{cta}\n\n{disclosure}\n\n{tags}")
    reel = f"{brief['title']} ✨ {brief['subtitle']}\n\n{cta}\n\n{disclosure}\n\n{tags}"
    return carousel, reel


def build_spec(kit, image_rel, image_sha, label, brief, details, tiles, split, model) -> dict:
    carousel, reel = captions(brief)
    return {
        "schema_version": 1, "template": "auto_v1", "kit_id": f"r11-kit-{kit}", "status": "AUTO_GENERATED",
        "publishing": False,
        "source": {"path": image_rel, "sha256": image_sha, "provenance": f"AI-generated by the R11 content agent ({model})"},
        "brand": BRAND,
        "hero": {"eyebrow": f"CONCEPT · {label.upper()}", "title": brief["title"], "subtitle": brief["subtitle"]},
        "problem_solution": {"eyebrow": "PROBLEM → SOLUTION", "title": brief["fix_title"],
                             "problem": brief["problem"], "solutions": brief["solutions"]},
        "details": {"eyebrow": "WHAT MAKES IT WORK", "title": "3 details to copy", "items": details},
        "materials": {"eyebrow": "MATERIAL PALETTE", "title": "Materials in this look", "tiles": tiles,
                      "split_title": "COLOUR SPLIT", "split": split},
        "cta": {"eyebrow": "FREE CONSULTATION", "title": "Apne ghar ke liye aisa look chahiye?",
                "body": "2BHK · 3BHK · full home interiors across Delhi NCR",
                "primary": "Enquiry form — link in bio", "secondary": f"WhatsApp  {BRAND['whatsapp_display']}"},
        "reel": {"cards": [{"start": 0.3, "end": 2.7, "title": brief["title"], "sub": f"{label} concept"},
                           {"start": 2.9, "end": 5.4, "title": brief["reel_line"], "sub": brief["solutions"][0]}],
                 "end_card": {"title": "Apne ghar ke liye aisa look?", "sub": "Free consultation",
                              "lines": ["Link in bio", f"WhatsApp {BRAND['whatsapp_display']}"]}},
        "reel_caption": reel, "caption": carousel,
    }


def create_concept(root: Path, studio, day: date, slots: list[str], render_check=None) -> dict:
    kit = f"auto-{day:%Y%m%d}"
    room, label, style = topic_for(day)
    image_rel = f"{CONCEPTS}/{kit}.jpg"
    draft_path = root / DRAFTS / f"{kit}.json"
    draft = load(draft_path, None)
    if draft and (root / image_rel).exists() and draft.get("room") == room and draft.get("style") == style:
        brief, attempts = draft["brief"], draft["image_attempts"]
        img = Image.open(root / image_rel).convert("RGB")
    else:
        brief = write_brief(studio, room, label, style)
        img, attempts = make_image(studio, room, style, brief["scene"], label)
        (root / CONCEPTS).mkdir(parents=True, exist_ok=True)
        img.save(root / image_rel, "JPEG", quality=92, subsampling=0)
        img = Image.open(root / image_rel).convert("RGB")     # work from the exact saved bytes
        draft = {"room": room, "style": style, "brief": brief, "image_attempts": attempts, "failures": 0}
        save(draft_path, draft)
    spec_path = root / SPECS / f"{kit}.json"
    try:
        details = write_details(studio, img, label)
        tiles = write_materials(studio, img)
        split = colour_split(img)
        image_sha = hashlib.sha256((root / image_rel).read_bytes()).hexdigest()
        spec = build_spec(kit, image_rel, image_sha, label, brief, details, tiles, split, "FLUX.2 klein 9B")
        save(spec_path, spec)
        if render_check:          # build the slides once now, so a layout problem fails here, not at post time
            render_check(root, spec_path)
    except Exception:
        spec_path.unlink(missing_ok=True)
        draft["failures"] = draft.get("failures", 0) + 1
        if draft["failures"] >= MAX_DRAFT_FAILURES:   # start over with a new brief and image next time
            draft_path.unlink(missing_ok=True)
            (root / image_rel).unlink(missing_ok=True)
        else:
            save(draft_path, draft)
        raise
    draft_path.unlink(missing_ok=True)
    # slots: am -> reel, pm -> carousel; a lone free slot always gets the carousel
    sched = load(root / SCHEDULE, {"items": []})
    fmts = {"am": "reel", "pm": "carousel"} if len(slots) == 2 else {slots[0]: "carousel"}
    for slot in slots:
        t, _ = SLOTS[slot]
        sched["items"].append({"id": f"{day:%Y%m%d}-{slot}-{fmts[slot]}", "kit": kit, "format": fmts[slot],
                               "at": datetime.combine(day, t, IST).isoformat()})
    sched["items"].sort(key=lambda i: i["at"])
    save(root / SCHEDULE, sched)
    return {"kit": kit, "room": room, "style": style, "title": brief["title"], "slots": slots,
            "image_attempts": attempts}


def run(root: Path, studio, now: datetime, render_check=None, max_new=1) -> dict:
    sched = load(root / SCHEDULE, {"items": []})
    log = load(root / LOG, {"concepts": {}, "events": []})
    todo = missing_days(sched, now)
    done = []
    for day, slots in todo[:max_new]:
        at = now.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        try:
            info = create_concept(root, studio, day, slots, render_check)
            log["concepts"][info["kit"]] = {"created_at": at, **info}
            log["events"].append({"at": at, "day": str(day), "result": "created", "kit": info["kit"]})
            done.append(info["kit"])
        except Exception as e:  # any failure is logged; posting of existing items is never blocked
            log["events"].append({"at": at, "day": str(day), "result": "failed",
                                  "error": f"{type(e).__name__}: {e}"[:300]})
        log["events"] = log["events"][-60:]
        save(root / LOG, log)
    fillers = fill_gaps(root, now)
    if fillers:
        at = now.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        log["events"].append({"at": at, "result": "filled", "items": fillers})
        log["events"] = log["events"][-60:]
        save(root / LOG, log)
    return {"missing_days": [str(d) for d, _ in todo], "created": done, "filled": fillers,
            "last_event": log["events"][-1] if log["events"] else None}


FILL_WINDOW = timedelta(hours=6)
FILL_MAX_AGE = timedelta(days=14)


def fill_gaps(root: Path, now: datetime) -> list[str]:
    """A slot that is about to come up empty (no new concept could be made in time) gets the
    not-yet-scheduled format of a recent auto kit, e.g. the reel of a concept that only went out
    as a carousel. Keeps the 07:00 / 19:00 rhythm when generation fails or the AI quota is out."""
    sched = load(root / SCHEDULE, {"items": []})
    taken = {datetime.fromisoformat(i["at"]).astimezone(IST).replace(second=0, microsecond=0) for i in sched["items"]}
    kits = sorted({i["kit"] for i in sched["items"] if re.fullmatch(r"auto-\d{8}", i["kit"])}, reverse=True)
    added = []
    today = now.astimezone(IST).date()
    for k in range(2):
        for slot, (t, _) in SLOTS.items():
            at = datetime.combine(today + timedelta(days=k), t, IST)
            if not (now + LEAD <= at <= now + FILL_WINDOW) or at in taken:
                continue
            for kit in kits:
                made = datetime.strptime(kit[5:], "%Y%m%d").replace(tzinfo=IST)
                if now - made > FILL_MAX_AGE or not (root / SPECS / f"{kit}.json").exists():
                    continue
                used = {i["format"] for i in sched["items"] if i["kit"] == kit}
                missing = [f for f in ("reel", "carousel") if f not in used]
                if missing:
                    item = {"id": f"{at:%Y%m%d}-{slot}-{missing[0]}-filler", "kit": kit, "format": missing[0],
                            "at": at.isoformat()}
                    sched["items"].append(item)
                    taken.add(at)
                    added.append(item["id"])
                    break
    if added:
        sched["items"].sort(key=lambda i: i["at"])
        save(root / SCHEDULE, sched)
    return added


def render_check(root: Path, spec_path: Path):
    import build_kit
    with tempfile.TemporaryDirectory() as tmp:
        build_kit.build(root, spec_path, Path(tmp) / "kit", with_reel=False)


def main():
    root = HERE.parents[1]
    sys.path.insert(0, str(HERE))
    out = run(root, Studio(), datetime.now(timezone.utc), render_check)
    print(json.dumps({"ok": True, **out}, ensure_ascii=False))


if __name__ == "__main__":
    main()
