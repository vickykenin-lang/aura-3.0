# R11 Design Kit agents (unattended)

One concept image becomes a 5-slide carousel and an 8-second reel, which are posted to
Instagram automatically on schedule. All text, labels and the layout plan are drawn by
code, so spelling, the phone number and brand details are always exact.

| Agent | File | Job |
|---|---|---|
| A5 packager | `build_kit.py` | `slide1..5.jpg` (1080×1350), `reel.mp4` (1080×1920, 8 s), captions, `kit.json` (sha256 of every file) |
| A4 reviewer | `review_kit.py` | Code checks (sizes, formats, caption has WhatsApp number + disclosure, ≤30 hashtags); OCR (Tesseract, free) reads every slide back and must find each intended line and the exact WhatsApp number; Amazon Nova adds an AI check when its key works |
| A1+A2 content agent | `content_agent.py` | Every run keeps the next 48 h filled: picks room + style, writes a validated brief, generates the concept image (FLUX.2 klein 9B) with OCR + vision QA (premium look, quality ≥ 8), picks detail crops and material swatches, computes the colour split, writes the kit spec and the schedule items |
| A6 autopost | `autopost.py` | Builds/reviews due kits into `campaigns/r11/kits/<kit>/`, posts at most one due item per run, records it in `published.json` |

Slides: 1 hero · 2 zoning plan (code-drawn, "not to scale") · 3 three detail crops ·
4 material palette + 60/30/10 split · 5 CTA (enquiry form + WhatsApp).

## Daily schedule (IST)

- **07:00** reel and **19:00** carousel of that day's new concept (a lone free slot gets the carousel).
- AI runs on the `designinfra-content-studio` Worker (Workers AI free tier). The only credential is the
  workflow's GitHub OIDC token; the Worker checks repository and branch. Daily caps: 12 images, 80 text,
  120 vision calls.
- A failed concept is logged in `concepts.json`; its accepted image and brief stay in `drafts/` so the next
  hourly run retries without a new image (3 failures → start over). Posting of ready items is never blocked.
- Captions, WhatsApp number, CTA and the "AI-generated design concept" disclosure are written by code.

## How posting works

Workflow **AURA3 R11 Autopost** runs every hour at :47 UTC (:17 IST).

1. Tests, then build + review every kit named in `schedule.json` (skipped if unchanged).
2. Picks the earliest due item not yet posted. Posts only if: review verdict is `READY_*`,
   every file matches its sha256, the public image URLs serve the same bytes, the token is
   the confirmed `@designinfra.interiors` account, quota is left, no recent post has the same
   caption, and the last R11 post was at least 12 h ago.
3. Carousel: 5 image containers → carousel → publish. Reel: resumable upload → publish.
4. Writes the result (permalink, or the error and attempt count; max 3 attempts) to `published.json`.

Live posting only happens on `main` from the hourly schedule or a manual run with
`mode: publish`. Pushes and other branches do a read-only rehearsal (`--dry-run --preview-next`).

The gate is code + OCR: any missing line or a wrong phone number on a slide means `REJECTED`.
Nova is optional: if it cannot run (for example an invalid AWS key) the kit is
`READY_CODE_CHECKED`; if it runs and objects, the kit is blocked (`REJECTED_BY_VISION_REVIEW`).
Bump `REVIEWER_VERSION` in `review_kit.py` when checks change; committed kits are then re-reviewed.

## Add content

1. Add the concept image and a spec in `kits/` (copy `p001-warm-modern-luxury.json`).
2. Add items to `schedule.json` (`format`: `carousel` or `reel`, `at` with `+05:30`).
3. Push to `main`. The next hourly run builds, reviews and posts when due.

## Run locally

```
python3 r11/design_kit/build_kit.py r11/design_kit/kits/p001-warm-modern-luxury.json --out /tmp/kit
python3 r11/design_kit/review_kit.py r11/design_kit/kits/p001-warm-modern-luxury.json --out /tmp/kit
python3 -m unittest r11/design_kit/test_design_kit.py r11/design_kit/test_autopost.py
```

Needs `fonts-inter`, `ffmpeg`, `tesseract-ocr`, Pillow; `boto3` only for Nova.
