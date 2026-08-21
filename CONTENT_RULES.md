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

---

## Dashboard queue rules (Approve / Publish)

| Event | Dashboard behaviour |
|-------|---------------------|
| **Approve + publish SUCCESS** | Post **removed** from dashboard (status = published) |
| **Approve + publish FAIL** (or secrets/API error) | Post **stays Pending** (status = failed / pending) — retry allowed |
| **Not yet approved** | Shows as **Pending** |
| **Max cards** | **Maximum 20** posts on dashboard for approval at a time |

Details:
1. Only `pending` and `failed` posts appear on the approval grid.
2. `published` posts never appear again on the shortlist.
3. Queue length capped at **20** (newest / highest priority first).
4. Source of truth for “posted”: `content/published.json` (Instagram id present).
5. Approve starts publish attempt; success writes to `published.json` → next dashboard load hides the card.

---

## Caption rules

1. One clear conversion signal: price band, timeline, inclusions, or process step
2. Strong CTA: Free consultation / WhatsApp / link in bio
3. English + Hindi feel OK
4. No spam; quality over quantity
5. AI image → label “Concept visualisation”

---

## Pipeline rules

1. Daily candidates can be generated; dashboard shows at most **20** pending
2. Only ≥ 7 appear
3. Rejected / < 7 never appear
4. Approve = publish attempt (IG secrets required)
5. Success → remove from queue; fail → keep pending
6. Never mix Vision / drama / kids content into AURA2
7. Image source: interior only — no random picsum
