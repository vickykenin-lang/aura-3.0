# AURA2 Controlled-Pilot Log

## Day 1 — 22 August 2026

### Outcome

Gemini candidate generation completed successfully after code hardening. The dual quality gate did
not complete because the configured DeepSeek credential returned HTTP 401 Unauthorized. No gate
result was committed, no candidate was approved, and nothing was published.

### Execution record

| Run | Issue | Result | Corrective action |
|---|---:|---|---|
| 1 | #8 | Gemini reply was not the expected JSON array | Added an explicit ten-item response schema and robust parsing |
| 2 | #10 | Gemini HTTP 503 | Added bounded retry/backoff |
| 3 | #12 | Retry recovered; one candidate failed minor copy validation | Added deterministic CTA/hashtag normalization while retaining hard validation |
| 4 | #14 | Gemini 3.7 remained unavailable after retries | Added current Gemini Flash model fallbacks for generation and vision |
| 5 | #16 | Ten candidates generated; dual gate blocked | Replaced three unavailable images, schema-constrained vision, and surfaced DeepSeek 401 clearly |
| 6 | #19 | Ten candidates generated; replacement key still returned DeepSeek 401 | Added a DeepSeek `/models` preflight and hardened Gemini handling for empty/malformed responses |

### Verified

- Founder-only mobile issue command triggers the combined workflow.
- Gemini secret is present and candidate generation can complete.
- Ten candidates are produced with unique slots and local copy validation.
- Transient provider errors retry with bounded backoff.
- Gemini can fall back to another current Flash model after HTTP, empty-response, or malformed-JSON failures.
- DeepSeek authentication/model availability is checked before image scoring to avoid wasting Gemini quota.
- The workflow fails closed: no gate commit, approval, or publication occurs after an error.
- Instagram publishing remains manual and the approval kill switch remains ON.

### Blocker

The replacement repository secret reached Actions, but DeepSeek rejected the masked key ending in
`5f3e` as invalid. Replace `DEEPSEEK_KEY` with a newly created key from the official DeepSeek API
platform, then create a new issue with the exact title `RUN AURA2 PILOT`. Do not count Day 1 as
completed until the dual gate commits results successfully.
