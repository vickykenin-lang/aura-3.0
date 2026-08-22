# AURA2 — Controlled-Pilot Lead Engine

**Founder:** Vicky Gautam

**Business:** Design Infra, Delhi NCR turnkey interiors

**Current status:** Controlled pilot — not yet production-autonomous

## Objective

Generate ten credible interior-content candidates daily, validate the actual image and business
quality independently, let the Founder publish only the best one or two, and convert traffic into
privacy-safe inquiries through the official website.

## Working pipeline

1. Founder manually starts the pilot generator; Gemini creates ten captions against a curated
   interior image pool.
2. Gemini Vision inspects the actual downloaded image.
3. DeepSeek independently judges caption match, CTA, conversion signal, honesty, and brand fit.
4. Only dual-pass candidates scoring at least 7 appear on the dashboard.
5. Only a Founder-created APPROVE issue or manual workflow dispatch can approve a candidate.
6. The approval validator checks the gate again and marks the post for manual Instagram publishing.
7. Founder publishes manually and records the confirmed Instagram reference.

## Safety rules

- No public GitHub user can trigger Founder approval.
- A pre-written score cannot bypass the dual gate.
- Rejected candidates remain hidden.
- Stock/reference images must be disclosed and must never be presented as completed Design Infra work.
- No Instagram credential or external-posting action exists in GitHub Actions during the pilot.
- The kill switch in data/control.json stops approval handoff.

## Main files

- scripts/generate_candidates.py — daily Gemini content runner
- scripts/score_with_deepseek.py — Gemini Vision plus DeepSeek business gate
- scripts/approve_manual.py — strict manual-publish approval validator
- .github/workflows/daily_content.yml — manual pilot generation
- .github/workflows/quality_gate.yml — manual pilot dual gate
- .github/workflows/aura2.yml — Founder approval/rejection
- OPERATIONS_RUNBOOK.md — operating and recovery steps
- IMPLEMENTATION_STATUS.md — honest readiness status

## Live pages

- Dashboard: https://vickykenin-lang.github.io/design-infra-aura2/
- Lead form: https://vickykenin-lang.github.io/design-infra-aura2/leads.html

## Pilot rule

Generate ten candidates per pilot day, but normally publish only the best one or two. Run a
seven-day controlled pilot before requesting authorization for unattended scheduling or declaring
the department production-ready.
