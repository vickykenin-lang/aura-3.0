# R11 Design Kit agents

One concept image becomes one week of content: a 5-slide carousel and an 8-second reel.
All text, labels and the layout plan are drawn by code, so spelling, the phone number
and brand details are always exact. Nothing here publishes to Instagram.

| Agent | File | Job |
|---|---|---|
| A5 packager | `build_kit.py` | Builds `slide1..5.jpg` (1080×1350), `reel.mp4` (1080×1920, 8 s), `caption.txt`, `kit.json` (sha256 of every file) |
| A4 reviewer | `review_kit.py` | File checks + Amazon Nova reads all 5 slides; writes `review.json` with a verdict |

Slides: 1 hero · 2 zoning plan (code-drawn, "not to scale") · 3 three detail crops ·
4 material palette + 60/30/10 split · 5 CTA (enquiry form + WhatsApp).

## Add a new kit

1. Put the approved concept image in the repo and note its sha256.
2. Copy `kits/p001-warm-modern-luxury.json`, change the source, copy, crop boxes and plan zones.
3. Push to the `r11/design-kit` branch. The **AURA3 R11 Design Kit** workflow builds and reviews
   every kit and uploads them as the `r11-design-kits` artifact.

Verdicts: `READY_FOR_FOUNDER_APPROVAL`, `READY_PENDING_VISION_REVIEW` (Nova not run),
`REJECTED` (file/caption problem), `REJECTED_BY_VISION_REVIEW`.

## Run locally

```
python3 r11/design_kit/build_kit.py r11/design_kit/kits/p001-warm-modern-luxury.json --out /tmp/kit
python3 r11/design_kit/review_kit.py r11/design_kit/kits/p001-warm-modern-luxury.json --out /tmp/kit
RUN_REEL=1 python3 -m unittest r11/design_kit/test_design_kit.py -v
```

Needs `fonts-inter`, `ffmpeg`, Pillow; `boto3` only for `--nova`.

Pending: a generated bird's-eye view (needs an image model), and carousel publishing after
founder approval.
