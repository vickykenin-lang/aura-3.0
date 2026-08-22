# AURA2 Controlled-Pilot Log

## Day 1 — 22 August 2026

### Outcome

Day 1 completed with an authoritative ten-candidate batch. Gemini Vision inspected every actual
image and DeepSeek scored every visually acceptable caption. Nine candidates passed both gates;
one kitchen lifestyle image was correctly rejected because people, rather than the interior,
dominated the image. No candidate was approved and nothing was published.

### Execution record

| Run | Issue | Result | Corrective action |
|---|---:|---|---|
| 1 | #8 | Gemini reply was not the expected JSON array | Added an explicit ten-item response schema and robust parsing |
| 2 | #10 | Gemini HTTP 503 | Added bounded retry/backoff |
| 3 | #12 | Retry recovered; one candidate failed minor copy validation | Added deterministic CTA/hashtag normalization while retaining hard validation |
| 4 | #14 | Gemini 3.7 remained unavailable after retries | Added current Gemini Flash model fallbacks for generation and vision |
| 5 | #16 | Ten candidates generated; dual gate blocked | Replaced three unavailable images, schema-constrained vision, and surfaced DeepSeek 401 clearly |
| 6 | #19 | Ten candidates generated; replacement key still returned DeepSeek 401 | Added a DeepSeek `/models` preflight and hardened Gemini handling for empty/malformed responses |
| 7 | #23 | DeepSeek connected; 3/10 passed but seven technical responses remained | Enforced complete-batch safety and updated the retired Gemini fallback model |
| 8 | #25 | 5 dual passes, 1 visual reject, 4 technical errors | Kept the batch fail-closed and added bounded Gemini semantic retries |
| 9 | #27 | Generation response hit `MAX_TOKENS` | Bounded caption length and raised structured-output budget |
| 10 | #29 | 7 dual passes, 1 visual reject, 2 technical errors | Extended bounded response recovery while preserving strict completion |
| 11 | #31 | 8 dual passes, 1 visual reject, 1 technical error | Added a strict compact Gemini vision fallback |
| 12 | #33 | 6 dual passes, 1 visual reject; remaining malformed replies traced to DeepSeek | Added provider-specific DeepSeek JSON retries and diagnostics |
| 13 | #35 | **Complete: 9 dual passes, 1 visual reject, 0 technical errors** | Authoritative results committed; Founder issue closed automatically |

### Verified

- Founder-only mobile issue command triggers the combined workflow.
- Gemini secret is present and candidate generation can complete.
- Ten candidates are produced with unique slots and local copy validation.
- Transient provider errors retry with bounded backoff.
- Gemini can fall back to another current Flash model after HTTP, empty-response, or malformed-JSON failures.
- DeepSeek authentication/model availability is checked before image scoring to avoid wasting Gemini quota.
- DeepSeek malformed JSON is retried with bounded backoff and explicit provider labeling.
- Authoritative Day 1 result: `batch_complete=true`, 9/10 dual PASS, 1/10 Gemini visual reject.
- The workflow fails closed: no gate commit, approval, or publication occurs after an error.
- At Day 1 batch closeout, Instagram publishing was manual and the approval kill switch was ON.

### Day 1 closeout state

Day 1 completed with nine passing candidates available for Founder review. At that closeout point,
approval was disabled and publishing was manual. The later activation record below supersedes that
operating state; unattended daily scheduling still requires separate Founder authorization.

## Automatic publishing activation — 22 August 2026

The Founder explicitly authorized automatic Instagram posting. The controlled publisher now:

- revalidates current calendar membership, Founder approval, dual-gate pass, and kill switch;
- creates a public-image media container through the current Instagram API;
- waits for container readiness before publishing;
- records the returned Instagram media ID, permalink when available, and timestamp;
- updates the approval state to `published`, which changes the dashboard to Instagram Posted; and
- refuses missing credentials, duplicate media IDs, unsafe images, or unclear container states.

Candidate `20260822-01` is the first authorized live publish. Production autonomy remains unapproved;
only explicit Founder approvals may trigger external posting.
