"""Line drawing of a concept render, made by FLUX.2 klein from the render itself.

The filter-made drawing (build_kit.sketch) turned rug and fluted-panel texture into noise and was
rejected by the founder on 27 Nov 2026. Here the render goes to the model as a reference image and
comes back as a clean ink drawing of the same room. check_drawing() keeps obviously wrong results
(a photo, a grey wash, a blank page) out of a kit.

    python r11/design_kit/drawing.py campaigns/r11/concepts/auto-20261126.jpg --out out
"""
import argparse
import io
import json
import sys
from pathlib import Path

from PIL import Image

PROMPT = ("Redraw image 0 as an interior designer's hand-drafted concept drawing of exactly the same room, "
          "seen from exactly the same camera position and angle. Clean black ink line art on plain white "
          "paper: crisp straight architectural lines for the walls, ceiling, floor edges, cabinetry, panels "
          "and openings; simple confident outlines for furniture, lights, curtains and decor. Keep every "
          "object in the same place and the same proportions. No colour, no grey shading, no hatching, no "
          "texture fill, no text, no labels, no dimensions, no people.")
REF_MAX = 511   # Workers AI: every input image must be smaller than 512 x 512


def reference_jpeg(img: Image.Image) -> bytes:
    ref = img.convert("RGB")
    ref.thumbnail((REF_MAX, REF_MAX), Image.LANCZOS)
    buf = io.BytesIO()
    ref.save(buf, "JPEG", quality=90)
    return buf.getvalue()


def check_drawing(img: Image.Image) -> list[str]:
    """Deterministic checks: white paper, real ink lines, no colour."""
    small = img.convert("RGB").resize((256, 320))
    lum = small.convert("L").histogram()
    n = sum(lum)
    issues = []
    if sum(lum[200:]) / n < 0.55:
        issues.append("DRAWING_NOT_ON_WHITE_PAPER")
    if sum(lum[:110]) / n < 0.015:
        issues.append("DRAWING_HAS_NO_LINES")
    if sum(lum[110:200]) / n > 0.30:
        issues.append("DRAWING_HAS_GREY_SHADING")
    hsv = small.convert("HSV").getdata()
    if sum(1 for h, s, v in hsv if s > 60 and v > 60) / n > 0.04:
        issues.append("DRAWING_HAS_COLOUR")
    return issues


def make_drawing(studio, render: Image.Image) -> tuple[Image.Image, list[str]]:
    w, h = render.size
    scale = 1024 / max(w, h) if max(w, h) > 1024 else 1
    ow, oh = int(w * scale) // 16 * 16, int(h * scale) // 16 * 16
    raw = studio.drawing(PROMPT, reference_jpeg(render), ow, oh)
    out = Image.open(io.BytesIO(raw)).convert("RGB").resize((w, h), Image.LANCZOS)
    return out, check_drawing(out)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("images", nargs="+")
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from content_agent import Studio
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    report, studio = {}, Studio()
    for p in a.images:
        render = Image.open(p).convert("RGB")
        try:
            drawing, issues = make_drawing(studio, render)
        except Exception as e:   # one failed image must not hide the others
            report[p] = {"error": f"{type(e).__name__}: {e}"[:300]}
            continue
        stem = Path(p).stem
        drawing.save(out / f"{stem}-drawing.jpg", quality=92)
        pair = Image.new("RGB", (render.width * 2 + 24, render.height), "white")
        pair.paste(render, (0, 0))
        pair.paste(drawing, (render.width + 24, 0))
        pair.save(out / f"{stem}-pair.jpg", quality=88)
        report[p] = {"issues": issues}
    (out / "report.json").write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))
    return 0 if any("issues" in v for v in report.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
