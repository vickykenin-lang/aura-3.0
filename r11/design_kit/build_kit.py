#!/usr/bin/env python3
"""R11 Design Kit builder (agent A5: packager).

Input : one concept image + a kit spec JSON (zones, crops, copy).
Output: 5 carousel slides (1080x1350 JPEG), an 8 s reel (1080x1920 MP4),
        caption.txt and kit.json (sha256 of every file).

All text, labels and the layout plan are drawn by code, never by an image
model, so spelling, phone number and brand details are always exact.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageStat

W, H = 1080, 1350          # carousel slide (4:5)
RW, RH, FPS, SECS = 1080, 1920, 30, 8.0   # reel (9:16)
SS = 2                     # supersampling for vector drawing
SLIDES = 5
BUILDER_VERSION = 2   # bump when output changes, so committed kits are rebuilt (2: reels carry music)

IVORY = (250, 247, 242)
CHAR = (31, 41, 55)
AMBER = (180, 83, 9)
MUTED = (107, 114, 128)
LINE = (214, 207, 196)
WHITE = (255, 255, 255)
UPHOL = (241, 235, 226)
WALNUT_PALE = (214, 186, 158)
STONE_PALE = (233, 224, 209)
RUG = (238, 231, 220)

FONT_DIR = Path("/usr/share/fonts/opentype/inter")


class KitError(Exception):
    pass


def font(name: str, size: int) -> ImageFont.FreeTypeFont:
    path = FONT_DIR / f"{name}.otf"
    if not path.exists():
        raise KitError(f"FONT_MISSING:{path.name} (install fonts-inter)")
    return ImageFont.truetype(str(path), size)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


# ---------- text helpers ----------
def wrap(draw, text, fnt, width):
    lines, cur = [], ""
    for word in text.split():
        trial = (cur + " " + word).strip()
        if draw.textlength(trial, font=fnt) <= width:
            cur = trial
        else:
            if cur:
                lines.append(cur)
            if draw.textlength(word, font=fnt) > width:
                raise KitError(f"WORD_TOO_WIDE:{word}")
            cur = word
    if cur:
        lines.append(cur)
    return lines


def block(draw, xy, text, fnt, fill, width, leading=1.28, max_lines=None):
    x, y = xy
    lines = wrap(draw, text, fnt, width)
    if max_lines and len(lines) > max_lines:
        raise KitError(f"TEXT_OVERFLOW:{text[:40]}")
    for line in lines:
        draw.text((x, y), line, font=fnt, fill=fill)
        y += round(fnt.size * leading)
    return y


def tracked(draw, xy, text, fnt, fill, tracking=4):
    x, y = xy
    for ch in text:
        draw.text((x, y), ch, font=fnt, fill=fill)
        x += draw.textlength(ch, font=fnt) + tracking
    return x


def tracked_width(draw, text, fnt, tracking=4):
    return sum(draw.textlength(c, font=fnt) + tracking for c in text) - tracking


def footer(draw, spec, n, color=MUTED):
    f = font("Inter-SemiBold", 19)
    tracked(draw, (64, H - 70), spec["brand"]["name"], f, color, 5)
    label = f"{n} / {SLIDES}"
    fm = font("Inter-Medium", 20)
    draw.text((W - 64 - draw.textlength(label, font=fm), H - 72), label, font=fm, fill=color)


def header(draw, eyebrow, title):
    tracked(draw, (64, 64), eyebrow, font("Inter-SemiBold", 21), AMBER, 4)
    return block(draw, (64, 100), title, font("InterDisplay-Light", 58), CHAR, W - 128, 1.15, 2)


# ---------- image helpers ----------
def cover(img, size, focus=(0.5, 0.5)):
    tw, th = size
    sw, sh = img.size
    s = max(tw / sw, th / sh)
    nw, nh = math.ceil(sw * s), math.ceil(sh * s)
    im = img.resize((nw, nh), Image.LANCZOS)
    x, y = round((nw - tw) * focus[0]), round((nh - th) * focus[1])
    return im.crop((x, y, x + tw, y + th))


def rounded(img, r):
    mask = Image.new("L", (img.width * SS, img.height * SS), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, mask.width - 1, mask.height - 1), r * SS, fill=255)
    out = img.convert("RGBA")
    out.putalpha(mask.resize(img.size, Image.LANCZOS))
    return out


def median_hex(img, box):
    rgb = tuple(int(v) for v in ImageStat.Stat(img.crop(tuple(box)).convert("RGB")).median)
    return rgb, "#%02X%02X%02X" % rgb


def check_box(img, box, what):
    x0, y0, x1, y1 = box
    if not (0 <= x0 < x1 <= img.width and 0 <= y0 < y1 <= img.height):
        raise KitError(f"BOX_OUTSIDE_IMAGE:{what}")


# ---------- slide 1: hero ----------
def slide_hero(src, spec):
    s = Image.new("RGB", (W, H), IVORY)
    s.paste(cover(src, (W, 1080)), (0, 0))
    d = ImageDraw.Draw(s)
    hero = spec["hero"]
    tracked(d, (64, 1112), hero["eyebrow"], font("Inter-SemiBold", 20), AMBER, 4)
    brand = spec["brand"]["name"]
    fb = font("Inter-SemiBold", 20)
    tracked(d, (W - 64 - tracked_width(d, brand, fb, 5), 1112), brand, fb, CHAR, 5)
    d.text((64, 1142), hero["title"], font=font("InterDisplay-Light", 66), fill=CHAR)
    block(d, (64, 1228), hero["subtitle"], font("Inter-Regular", 25), MUTED, W - 128, 1.25, 1)
    fd = font("Inter-Regular", 19)
    d.text((64, H - 52), spec["brand"]["disclosure"], font=fd, fill=MUTED)
    fs = font("Inter-SemiBold", 22)
    label = "Swipe  →"
    d.text((W - 64 - d.textlength(label, font=fs), H - 56), label, font=fs, fill=AMBER)
    return s


# ---------- slide 2: zoning plan ----------
def dashed(draw, pts, color, width, dash, gap):
    carry, on = 0.0, True
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        seg = math.hypot(x1 - x0, y1 - y0)
        pos = 0.0
        while pos < seg:
            step = min((dash if on else gap) - carry, seg - pos)
            if on:
                a, b = pos / seg, (pos + step) / seg
                draw.line([(x0 + (x1 - x0) * a, y0 + (y1 - y0) * a),
                           (x0 + (x1 - x0) * b, y0 + (y1 - y0) * b)], fill=color, width=width)
            pos += step
            carry += step
            if carry >= (dash if on else gap) - 1e-6:
                carry, on = 0.0, not on


def rot_rect(cx, cy, w, h, ang):
    a = math.radians(ang)
    pts = [(-w / 2, -h / 2), (w / 2, -h / 2), (w / 2, h / 2), (-w / 2, h / 2)]
    return [(cx + x * math.cos(a) - y * math.sin(a), cy + x * math.sin(a) + y * math.cos(a)) for x, y in pts]


def draw_plan(plan, size):
    pw, ph = size
    c = Image.new("RGB", (pw * SS, ph * SS), IVORY)
    d = ImageDraw.Draw(c)
    mx, top, bot = 40 * SS, 56 * SS, 60 * SS
    rx0, ry0, rx1, ry1 = mx, top, pw * SS - mx, ph * SS - bot
    rw, rh = rx1 - rx0, ry1 - ry0

    def P(nx, ny):
        return rx0 + nx * rw, ry0 + ny * rh

    def R(box):
        (a, b), (c2, d2) = P(box[0], box[1]), P(box[2], box[3])
        return [a, b, c2, d2]

    lw = 2 * SS
    # rug, furniture first; walls on top
    d.rectangle(R(plan["rug"]), fill=RUG, outline=LINE, width=lw)
    ct = R(plan["coffee_table"])
    d.rounded_rectangle(ct, radius=14 * SS, fill=STONE_PALE, outline=CHAR, width=lw)
    sx0, sy0, sx1, sy1 = R(plan["sofa"])
    d.rounded_rectangle([sx0, sy0, sx1, sy1], radius=12 * SS, fill=UPHOL, outline=CHAR, width=lw)
    back = sx0 + (sx1 - sx0) * 0.28
    d.line([back, sy0 + 10 * SS, back, sy1 - 10 * SS], fill=CHAR, width=lw)
    for k in (1, 2):
        yy = sy0 + (sy1 - sy0) * k / 3
        d.line([back, yy, sx1 - 6 * SS, yy], fill=LINE, width=lw)
    st = plan["side_table"]
    cx, cy = P(*st["center"])
    r = st["radius"] * rw
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=WALNUT_PALE, outline=CHAR, width=lw)
    co = R(plan["console"])
    d.rectangle(co, fill=WALNUT_PALE, outline=CHAR, width=lw)
    sl = R(plan["slat_panel"])
    d.rectangle(sl, fill=WALNUT_PALE, outline=CHAR, width=lw)
    for k in range(1, 6):
        yy = sl[1] + (sl[3] - sl[1]) * k / 6
        d.line([sl[0], yy, sl[2], yy], fill=CHAR, width=SS)
    tv0, tv1 = P(0.985, plan["tv"][0]), P(0.985, plan["tv"][1])
    d.line([tv0, tv1], fill=CHAR, width=7 * SS)
    lc = plan["lounge_chair"]
    lx, ly = P(*lc["center"])
    poly = rot_rect(lx, ly, lc["size"][0] * rw, lc["size"][1] * rw, lc["angle"])
    d.polygon(poly, fill=UPHOL, outline=CHAR, width=lw)
    # chair back = the side away from the sofa (bottom-right edge)
    d.line([poly[2], poly[3]], fill=CHAR, width=6 * SS)
    dn = plan["dining"]
    cx, cy = P(*dn["center"])
    r = dn["radius"] * rw
    for k in range(dn["chairs"]):
        ang = 45 + k * 360 / dn["chairs"]
        ox = cx + math.cos(math.radians(ang)) * (r + 0.035 * rw)
        oy = cy + math.sin(math.radians(ang)) * (r + 0.035 * rw)
        d.polygon(rot_rect(ox, oy, 0.06 * rw, 0.055 * rw, ang + 90), fill=UPHOL, outline=CHAR, width=lw)
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=WALNUT_PALE, outline=CHAR, width=lw)
    # walls: left, right, rear (with glazing gap); front edge open (dashed)
    ww = 7 * SS
    wx0, wx1 = P(plan["window"][0], 0)[0], P(plan["window"][1], 0)[0]
    d.line([rx0, ry1, rx0, ry0, wx0, ry0], fill=CHAR, width=ww, joint="curve")
    d.line([wx1, ry0, rx1, ry0, rx1, ry1], fill=CHAR, width=ww, joint="curve")
    d.line([wx0, ry0 - 4 * SS, wx1, ry0 - 4 * SS], fill=CHAR, width=SS)
    d.line([wx0, ry0 + 4 * SS, wx1, ry0 + 4 * SS], fill=CHAR, width=SS)
    wave = [(wx0 + (wx1 - wx0) * i / 60, ry0 + 14 * SS + math.sin(i * 1.1) * 3 * SS) for i in range(61)]
    d.line(wave, fill=(190, 180, 166), width=SS)
    dashed(d, [(rx0, ry1), (rx1, ry1)], LINE, 2 * SS, 14 * SS, 10 * SS)
    # walking path
    pts = [P(x, y) for x, y in plan["path"]]
    dashed(d, pts, AMBER, 4 * SS, 18 * SS, 12 * SS)
    (ax, ay), (bx, by) = pts[-2], pts[-1]
    ang = math.atan2(by - ay, bx - ax)
    hl = 18 * SS
    d.polygon([(bx, by),
               (bx - hl * math.cos(ang - 0.45), by - hl * math.sin(ang - 0.45)),
               (bx - hl * math.cos(ang + 0.45), by - hl * math.sin(ang + 0.45))], fill=AMBER)
    # labels
    fl = font("Inter-SemiBold", 15 * SS)
    for text, (x, y) in (("WINDOW · SHEER CURTAINS", ((wx0 + wx1) / 2, ry0 - 30 * SS)),
                         ("OPEN SIDE · ENTRY NOT SHOWN", ((rx0 + rx1) / 2, ry1 + 16 * SS))):
        tw = tracked_width(d, text, fl, 3 * SS)
        tracked(d, (x - tw / 2, y), text, fl, MUTED, 3 * SS)
    fm = font("Inter-Bold", 19 * SS)
    for m in plan["markers"]:
        x, y = P(*m["at"])
        rr = 19 * SS
        d.ellipse([x - rr, y - rr, x + rr, y + rr], fill=AMBER, outline=IVORY, width=3 * SS)
        t = str(m["n"])
        d.text((x, y), t, font=fm, fill=WHITE, anchor="mm")
    return c.resize(size, Image.LANCZOS)


def slide_plan(spec):
    plan = spec["plan"]
    s = Image.new("RGB", (W, H), IVORY)
    d = ImageDraw.Draw(s)
    header(d, plan["eyebrow"], plan["title"])
    s.paste(draw_plan(plan, (952, 720)), (64, 196))
    fn = font("Inter-Bold", 18)
    ft = font("Inter-Regular", 23)
    colw = 476
    y0 = 942
    for i, m in enumerate(plan["markers"]):
        col, row = i % 2, i // 2
        x, y = 64 + col * colw, y0 + row * 56
        d.ellipse([x, y, x + 30, y + 30], fill=AMBER)
        d.text((x + 15, y + 15), str(m["n"]), font=fn, fill=WHITE, anchor="mm")
        lines = wrap(d, m["text"], ft, colw - 60)
        if len(lines) > 1:
            raise KitError(f"LEGEND_TOO_LONG:{m['text']}")
        d.text((x + 44, y + 2), m["text"], font=ft, fill=CHAR)
    y = y0 + 3 * 56
    dashed(d, [(64, y + 15), (94, y + 15)], AMBER, 4, 9, 6)
    d.text((64 + 44, y + 2), plan["path_text"], font=ft, fill=CHAR)
    d.text((64, y + 58), plan["note"], font=font("Inter-Regular", 20), fill=MUTED)
    footer(d, spec, 2)
    return s


# ---------- slide 2 (auto_v1): problem -> solution ----------
def slide_problem(src, spec):
    ps = spec["problem_solution"]
    if len(ps["solutions"]) != 3:
        raise KitError("SOLUTION_COUNT")
    s = Image.new("RGB", (W, H), IVORY)
    d = ImageDraw.Draw(s)
    y = header(d, ps["eyebrow"], ps["title"]) + 34
    fp = font("Inter-Regular", 30)
    lines = wrap(d, ps["problem"], fp, W - 208)
    if len(lines) > 3:
        raise KitError("TEXT_OVERFLOW:problem")
    card_h = 76 + len(lines) * 39 + 34
    d.rounded_rectangle([64, y, W - 64, y + card_h], radius=24, fill=(243, 236, 226))
    tracked(d, (104, y + 34), "THE PROBLEM", font("Inter-SemiBold", 19), AMBER, 4)
    block(d, (104, y + 74), ps["problem"], fp, CHAR, W - 208, 1.3, 3)
    y += card_h + 44
    tracked(d, (64, y), "THE FIX IN THIS DESIGN", font("Inter-SemiBold", 19), AMBER, 4)
    y += 50
    fs, fn = font("Inter-Regular", 28), font("Inter-Bold", 19)
    for i, sol in enumerate(ps["solutions"], 1):
        d.ellipse([64, y + 2, 100, y + 38], fill=AMBER)
        d.text((82, y + 20), str(i), font=fn, fill=WHITE, anchor="mm")
        y = block(d, (124, y), sol, fs, CHAR, W - 188, 1.3, 2) + 22
    strip_top, strip_bottom = y + 10, H - 112
    if strip_bottom - strip_top < 150:
        raise KitError("TEXT_OVERFLOW:solutions")
    strip = cover(src, (W - 128, strip_bottom - strip_top), (0.5, 0.55))
    s.paste(rounded(strip, 20), (64, strip_top), rounded(strip, 20))
    footer(d, spec, 2)
    return s


# ---------- slide 3: details ----------
def slide_details(src, spec):
    det = spec["details"]
    s = Image.new("RGB", (W, H), IVORY)
    d = ImageDraw.Draw(s)
    header(d, det["eyebrow"], det["title"])
    cw, ch, gap, y = 440, 292, 44, 214
    for i, it in enumerate(det["items"]):
        check_box(src, it["box"], it["title"])
        crop = cover(src.crop(tuple(it["box"])), (cw, ch))
        s.paste(rounded(crop, 18), (64, y), rounded(crop, 18))
        tx = 64 + cw + 40
        tw = W - 64 - tx
        d.text((tx, y + 34), f"{i + 1:02d}", font=font("InterDisplay-Light", 40), fill=AMBER)
        ny = block(d, (tx, y + 92), it["title"], font("Inter-SemiBold", 29), CHAR, tw, 1.22, 2)
        block(d, (tx, ny + 10), it["text"], font("Inter-Regular", 23), MUTED, tw, 1.35, 4)
        y += ch + gap
    footer(d, spec, 3)
    return s


# ---------- slide 4: materials ----------
def slide_materials(src, spec):
    mat = spec["materials"]
    s = Image.new("RGB", (W, H), IVORY)
    d = ImageDraw.Draw(s)
    header(d, mat["eyebrow"], mat["title"])
    tile, gap = 296, 32
    fname, fuse = font("Inter-SemiBold", 21), font("Inter-Regular", 19)
    if not 3 <= len(mat["tiles"]) <= 6:
        raise KitError("TILE_COUNT")
    for i, t in enumerate(mat["tiles"]):
        check_box(src, t["box"], t["name"])
        col, row = i % 3, i // 3
        x, y = 64 + col * (tile + gap), 204 + row * (tile + 92)
        crop = cover(src.crop(tuple(t["box"])), (tile, tile))
        s.paste(rounded(crop, 16), (x, y), rounded(crop, 16))
        for text, fnt in ((t["name"], fname), (t["use"], fuse)):
            if d.textlength(text, font=fnt) > tile:
                raise KitError(f"TILE_TEXT_TOO_LONG:{text}")
        d.text((x, y + tile + 14), t["name"], font=fname, fill=CHAR)
        d.text((x, y + tile + 44), t["use"], font=fuse, fill=MUTED)
    split = mat["split"]
    if sum(p["pct"] for p in split) != 100:
        raise KitError("SPLIT_NOT_100")
    y = 204 + 2 * (tile + 92) + 4
    tracked(d, (64, y), mat["split_title"], font("Inter-SemiBold", 18), MUTED, 4)
    x, bar_w, used = 64, W - 128, []
    for p in split:
        if "rgb" in p:
            rgb = tuple(int(v) for v in p["rgb"])
        else:
            check_box(src, p["box"], p["name"])
            rgb = tuple(int(v) for v in ImageStat.Stat(src.crop(tuple(p["box"])).convert("RGB")).median)
        w = round(bar_w * p["pct"] / 100)
        d.rectangle([x, y + 34, x + w, y + 78], fill=rgb)
        x += w
        used.append((p, rgb))
    fp, fn, fu = font("Inter-Bold", 21), font("Inter-SemiBold", 21), font("Inter-Regular", 21)
    ry = y + 98
    for p, rgb in used:
        d.rectangle([64, ry + 3, 84, ry + 23], fill=rgb, outline=LINE)
        d.text((100, ry), f"{p['pct']}%", font=fp, fill=CHAR)
        nx = 160
        d.text((nx, ry), p["name"], font=fn, fill=CHAR)
        ux = nx + d.textlength(p["name"], font=fn) + 12
        if p.get("use"):
            line = "— " + p["use"]
            if ux + d.textlength(line, font=fu) > W - 64:
                raise KitError(f"SPLIT_TEXT_TOO_LONG:{p['name']}")
            d.text((ux, ry), line, font=fu, fill=MUTED)
        ry += 36
    footer(d, spec, 4)
    return s, [{"pct": p["pct"], "name": p["name"], "rgb": list(rgb)} for p, rgb in used]


# ---------- slide 5: CTA ----------
def pill(draw, box, text, fnt, fill, outline, color):
    draw.rounded_rectangle(box, radius=(box[3] - box[1]) // 2, fill=fill, outline=outline, width=2)
    cx, cy = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
    draw.text((cx, cy), text, font=fnt, fill=color, anchor="mm")


def slide_cta(src, spec):
    cta = spec["cta"]
    s = Image.new("RGB", (W, H), IVORY)
    s.paste(cover(src, (W, 500), (0.5, 0.62)), (0, 0))
    d = ImageDraw.Draw(s)
    tracked(d, (64, 556), cta["eyebrow"], font("Inter-SemiBold", 21), AMBER, 4)
    y = block(d, (64, 594), cta["title"], font("InterDisplay-Light", 64), CHAR, W - 128, 1.12, 2)
    y = block(d, (64, y + 18), cta["body"], font("Inter-Regular", 27), MUTED, W - 128, 1.3, 2)
    fb = font("Inter-SemiBold", 29)
    by = max(y + 60, 940)
    pill(d, [64, by, W - 64, by + 92], cta["primary"], fb, CHAR, CHAR, WHITE)
    pill(d, [64, by + 116, W - 64, by + 208], cta["secondary"], fb, IVORY, CHAR, CHAR)
    if by + 208 > H - 110:
        raise KitError("CTA_OVERFLOW")
    fh = font("Inter-Medium", 22)
    d.text((64, H - 72), spec["brand"]["handle"], font=fh, fill=CHAR)
    label = f"{SLIDES} / {SLIDES}"
    fm = font("Inter-Medium", 20)
    d.text((W - 64 - d.textlength(label, font=fm), H - 72), label, font=fm, fill=MUTED)
    return s


# ---------- reel ----------
def fit(draw, text, name, size, width, minimum):
    while size > minimum and draw.textlength(text, font=font(name, size)) > width:
        size -= 2
    f = font(name, size)
    if draw.textlength(text, font=f) > width:
        raise KitError(f"REEL_TEXT_TOO_LONG:{text[:30]}")
    return f


def card_layer(title, sub, disclosure=None):
    layer = Image.new("RGBA", (RW, RH), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    ft = fit(d, title, "InterDisplay-Light", 70, RW - 200, 44)
    fs = fit(d, sub, "Inter-Regular", 34, RW - 200, 24)
    box = [64, 1250, RW - 64, 1250 + 250]
    d.rounded_rectangle(box, radius=28, fill=IVORY + (238,))
    d.text((RW / 2, 1335), title, font=ft, fill=CHAR, anchor="mm")
    d.text((RW / 2, 1420), sub, font=fs, fill=MUTED, anchor="mm")
    if disclosure:
        d.text((RW / 2, 1530), disclosure, font=font("Inter-Regular", 24), fill=(245, 240, 232), anchor="mm")
    return layer


def end_layer(spec):
    e = spec["reel"]["end_card"]
    layer = Image.new("RGB", (RW, RH), IVORY)
    d = ImageDraw.Draw(layer)
    fb = font("Inter-SemiBold", 24)
    brand = spec["brand"]["name"]
    tracked(d, ((RW - tracked_width(d, brand, fb, 6)) / 2, 580), brand, fb, AMBER, 6)
    y = 700
    for line in wrap(d, e["title"], font("InterDisplay-Light", 84), RW - 160):
        d.text((RW / 2, y), line, font=font("InterDisplay-Light", 84), fill=CHAR, anchor="mm")
        y += 104
    d.text((RW / 2, y + 30), e["sub"], font=font("Inter-SemiBold", 40), fill=AMBER, anchor="mm")
    y += 150
    fl = font("Inter-SemiBold", 36)
    for i, line in enumerate(e["lines"]):
        box = [120, y, RW - 120, y + 104]
        pill(d, box, line, fl, CHAR if i == 0 else IVORY, CHAR, WHITE if i == 0 else CHAR)
        y += 132
    d.text((RW / 2, y + 40), spec["brand"]["handle"], font=font("Inter-Medium", 30), fill=MUTED, anchor="mm")
    return layer


def ease(t):
    return (1 - math.cos(math.pi * max(0.0, min(1.0, t)))) / 2


def build_reel(src, spec, out):
    big = src.resize((src.width * 2, src.height * 2), Image.LANCZOS)
    cards = [(c["start"], c["end"], card_layer(c["title"], c["sub"], spec["brand"]["disclosure"]))
             for c in spec["reel"]["cards"]]
    end = end_layer(spec)
    pan_end, fade = 5.6, 0.45
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import music   # original procedural score, one per kit (same kit id -> same audio)
    wav = Path(out).with_suffix(".music.wav")
    music.write_wav(wav, music.render(spec["kit_id"], SECS))
    cmd = ["ffmpeg", "-y", "-loglevel", "error",
           "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{RW}x{RH}", "-r", str(FPS), "-i", "-",
           "-i", str(wav),
           "-t", str(SECS), "-c:v", "libx264", "-pix_fmt", "yuv420p", "-profile:v", "high",
           "-crf", "18", "-preset", "medium", "-c:a", "aac", "-b:a", "160k",
           "-movflags", "+faststart", str(out)]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    n = int(SECS * FPS)
    for i in range(n):
        t = i / FPS
        p = ease(t / pan_end)
        z = 1.0 + 0.10 * p
        h = big.height / z
        w = h * RW / RH
        x0 = (big.width - w) * p
        y0 = (big.height - h) / 2
        frame = big.transform((RW, RH), Image.EXTENT, (x0, y0, x0 + w, y0 + h), Image.BICUBIC).convert("RGBA")
        for a, b, layer in cards:
            alpha = min(1.0, max(0.0, (t - a) / 0.35), max(0.0, (b - t) / 0.35))
            if alpha > 0:
                lay = layer.copy()
                lay.putalpha(lay.getchannel("A").point(lambda v, k=alpha: int(v * k)))
                frame = Image.alpha_composite(frame, lay)
        frame = frame.convert("RGB")
        if t >= pan_end - fade:
            k = min(1.0, (t - (pan_end - fade)) / fade)
            frame = Image.blend(frame, end, k)
        proc.stdin.write(frame.tobytes())
    proc.stdin.close()
    code = proc.wait()
    wav.unlink(missing_ok=True)
    if code != 0:
        raise KitError("FFMPEG_FAILED")


def probe(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                          "stream=codec_type,codec_name,width,height,pix_fmt,r_frame_rate:format=duration",
                          "-of", "json", str(path)], capture_output=True, text=True, check=True)
    return json.loads(out.stdout)


# ---------- main ----------
def build(root: Path, spec_path: Path, out_dir: Path, with_reel=True):
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    src_path = root / spec["source"]["path"]
    if sha256(src_path) != spec["source"]["sha256"]:
        raise KitError("SOURCE_SHA256_MISMATCH")
    src = Image.open(src_path).convert("RGB")
    out_dir.mkdir(parents=True, exist_ok=True)
    template = spec.get("template", "concept_v1")
    if template == "concept_v1":
        second = slide_plan(spec)
    elif template == "auto_v1":
        second = slide_problem(src, spec)
    else:
        raise KitError(f"UNKNOWN_TEMPLATE:{template}")
    slides = [slide_hero(src, spec), second, slide_details(src, spec)]
    s4, palette = slide_materials(src, spec)
    slides += [s4, slide_cta(src, spec)]
    outputs = []
    for i, im in enumerate(slides, 1):
        p = out_dir / f"slide{i}.jpg"
        im.save(p, "JPEG", quality=92, optimize=True, progressive=True, subsampling=0)
        outputs.append({"file": p.name, "kind": "carousel_slide", "width": W, "height": H})
    if with_reel:
        reel = out_dir / "reel.mp4"
        build_reel(src, spec, reel)
        outputs.append({"file": reel.name, "kind": "reel", "width": RW, "height": RH, "seconds": SECS})
        (out_dir / "reel_caption.txt").write_text(spec["reel_caption"] + "\n", encoding="utf-8")
        outputs.append({"file": "reel_caption.txt", "kind": "reel_caption"})
    (out_dir / "caption.txt").write_text(spec["caption"] + "\n", encoding="utf-8")
    outputs.append({"file": "caption.txt", "kind": "caption"})
    for o in outputs:
        p = out_dir / o["file"]
        o["sha256"], o["bytes"] = sha256(p), p.stat().st_size
    manifest = {
        "kit_id": spec["kit_id"], "status": spec["status"], "publishing": False, "builder_version": BUILDER_VERSION,
        "built_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "spec": spec_path.name, "spec_sha256": sha256(spec_path),
        "source": spec["source"], "colour_split": palette, "outputs": outputs,
        "pending_views": ["birdview (needs image generation)"],
    }
    (out_dir / "kit.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return manifest


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("spec")
    ap.add_argument("--root", default=str(Path(__file__).resolve().parents[2]))
    ap.add_argument("--out", required=True)
    ap.add_argument("--no-reel", action="store_true")
    a = ap.parse_args()
    try:
        m = build(Path(a.root), Path(a.spec), Path(a.out), not a.no_reel)
    except KitError as e:
        print(json.dumps({"ok": False, "error": str(e)}))
        sys.exit(2)
    print(json.dumps({"ok": True, "kit_id": m["kit_id"], "files": [o["file"] for o in m["outputs"]]}))


if __name__ == "__main__":
    main()
