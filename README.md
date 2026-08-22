# AURA2 — Controlled-Pilot Lead Engine

**Founder:** Vicky Gautam

**Business:** Design Infra, Delhi NCR turnkey interiors

**Current status:** Controlled pilot — automatic publishing after Founder approval

## Objective

Generate ten credible interior-content candidates daily, validate the actual image and business
quality independently, let the Founder publish only the best one or two, and convert traffic into
privacy-safe inquiries through the official website.

## Working pipeline

1. Founder opens an issue titled `RUN AURA2 PILOT` (or manually dispatches the combined pilot
   workflow); Gemini creates ten captions against a curated interior image pool.
2. Gemini Vision inspects the actual downloaded image.
3. DeepSeek independently judges caption match, CTA, conversion signal, honesty, and brand fit.
4. Only dual-pass candidates scoring at least 7 appear on the dashboard.
5. Only a Founder-created APPROVE issue or manual workflow dispatch can approve a candidate.
6. The approval validator checks the gate again before any external action.
7. AURA2 creates and verifies the Instagram media container, publishes it, and records the media ID.

## Safety rules

- No public GitHub user can trigger Founder approval.
- A pre-written score cannot bypass the dual gate.
- Rejected candidates remain hidden.
- Stock/reference images must be disclosed and must never be presented as completed Design Infra work.
- Instagram credentials remain only in GitHub Actions Secrets and are never written to source or logs.
- The kill switch in data/control.json stops both approval handoff and Instagram publishing.

## Main files

- scripts/generate_candidates.py — daily Gemini content runner
- scripts/score_with_deepseek.py — Gemini Vision plus DeepSeek business gate
- scripts/approve_manual.py — strict Founder approval validator
- scripts/publish_instagram.py — controlled Instagram container, publish, and verification runner
- .github/workflows/daily_content.yml — manual pilot generation
- .github/workflows/quality_gate.yml — manual pilot dual gate
- .github/workflows/pilot_run.yml — Founder-only combined mobile-friendly pilot command
- .github/workflows/aura2.yml — Founder approval/rejection
- OPERATIONS_RUNBOOK.md — operating and recovery steps
- IMPLEMENTATION_STATUS.md — honest readiness status
- PILOT_LOG.md — dated pilot attempts, evidence, failures, and corrective actions

## Live pages

- Dashboard: https://vickykenin-lang.github.io/design-infra-aura2/
- Lead form: https://vickykenin-lang.github.io/design-infra-aura2/leads.html

## Pilot rule

Generate ten candidates per pilot day, but normally publish only the best one or two. Run a
seven-day controlled pilot before requesting authorization for unattended scheduling or declaring
the department production-ready.
