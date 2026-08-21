# AURA2 Content Rules + Quality Gate (Locked)

**Brand:** Design Infra — premium turnkey interiors, Delhi NCR  
**Success metric:** Real qualified leads (WhatsApp / email)

---

## Hard visual rules (must pass before score)

A candidate is **AUTO-REJECT** if the image is primarily:

- Animals / wildlife
- Pure landscape / nature / mountains / beach with no interior
- Railway / roads / vehicles as main subject
- Food / coffee / product lifestyle with no room design
- Random stock unrelated to home/office design
- Kids / Bubblebee content
- Text-only memes

**Allowed (must be clear in frame):**

- Living room, bedroom, kitchen, bathroom, dining, wardrobe, false ceiling
- Home office / study interior
- Modular kitchen, storage, lighting design
- Before/after interior (if labeled)
- Concept visualisation of interiors (must say “Concept visualisation” in caption)

---

## Scoring gate (DeepSeek / Gemini)

Score **0–10**. Dashboard shows **only ≥ 7**.

| Check | Fail action |
|-------|-------------|
| Image is interior-related | If no → score = 0, never show |
| Caption matches image room type | Mismatch → max score 5 |
| Conversion signal (price / timeline / process) | Missing → max 6 |
| Clear CTA (consultation / link in bio) | Missing → max 6 |
| Design Infra brand fit (Delhi NCR turnkey) | Weak → reduce 1–2 points |
| Final business score | Must be ≥ 7 to appear |

**Rule:** Same model should not be sole creator and sole final reviewer when live scoring is on. Prefer DeepSeek for business score, Gemini for multimodal image check when available.

---

## Caption rules

1. One clear conversion signal: price band, timeline, inclusions, or process step
2. Strong CTA: Free consultation / WhatsApp / link in bio
3. English + Hindi feel OK
4. No spam; quality over quantity
5. AI image → label “Concept visualisation”

---

## Pipeline rules

1. Daily target: up to 10 candidates submitted
2. Only ≥ 7 appear on dashboard
3. Rejected / < 7 never appear
4. Approve = publish attempt (IG secrets required)
5. Never mix Vision / drama / kids content into AURA2
6. Image source must be interior URL or verified interior asset — **no random picsum/placeholder**

---

## Enforcement note (2026-08-21)

Dashboard previously used `picsum.photos` random seeds → animals/landscapes appeared with interior captions.  
**Fixed policy:** only curated interior image URLs; quality gate rejects non-interior subjects.
