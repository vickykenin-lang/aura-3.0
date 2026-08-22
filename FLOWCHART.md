# AURA2 Production Flow

## Daily autonomous path

1. Founder manually starts the Gemini runner from GitHub Actions.
2. Runner selects ten curated interior images and generates honest bilingual copy.
3. Gemini Vision downloads and inspects each actual image.
4. Visual failures receive score zero and never reach DeepSeek.
5. DeepSeek evaluates conversion quality, CTA, caption match, and brand honesty.
6. Dashboard loads current calendar, approvals, gate results, and published records.
7. Founder reviews only dual-pass candidates.
8. Founder submits APPROVE or REJECT through GitHub.
9. Workflow verifies that the command author is the repository owner.
10. Approval validator repeats kill-switch, rejection, visual, and business-score checks.
11. Candidate is marked approved_manual.
12. Founder publishes manually on Instagram.
13. Founder records the verified Instagram media ID or URL in content/published.json.
14. User copies the inquiry summary and continues through the official Design Infra website.

## Fail-closed paths

- Missing Gemini or DeepSeek key: quality workflow fails and dashboard shows no new cards.
- Image download/vision failure: candidate receives score zero.
- Missing gate result: approval validator refuses.
- Non-owner issue: approval job does not run.
- Kill switch enabled: no approval handoff is recorded.
- Instagram credentials are never exposed to GitHub Actions.

## Seven-day pilot exit criteria

- Ten fresh candidates generated daily.
- Actual-image gate completed daily.
- One or two best posts published when approved.
- No unauthorized or duplicate publication.
- Every failure visible in Actions.
- Inquiries manually logged and reviewed daily.
- Unattended daily scheduling remains disabled until separately authorized after the pilot.
