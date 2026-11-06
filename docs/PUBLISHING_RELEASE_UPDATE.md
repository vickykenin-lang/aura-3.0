# Publishing release checks — 6 November 2026

This update addresses the reviewed release-control, content-approval and account-target gaps. It preserves Founder authority, current activation settings, old decisions, source-quality rules and all existing generation budgets.

## What changes

- The publisher and shared runtime guard enforce canonical `state/control.json`, the legacy kill switch, Founder publishing authority and a successful standalone certificate observed within 24 hours. Certification is bound to the release implementation files. The certificate generator also requires fresh heartbeat/provider/capability evidence, rather than restamping old records.
- `governance/publishing_target.json` records the Founder-supplied target `designinfra.interiors`. Token discovery must agree with the configured account ID, and a read-only identity lookup must agree with the username before any media container is created. Secret values stay in their existing Actions environment.
- New source-image downloads capture byte hashes and dimensions. Passing QA binds the exact image URL/bytes, caption, format and target in a release manifest. The shared DeepSeek/Nova downloader path captures source proof without adding provider calls. The normal qualification path attaches the binding; missing proof remains ineligible for release.
- The dashboard includes the reviewed manifest fingerprint in `APPROVE` commands. The Founder workflow forwards it, and manual approval persists a separate manifest record alongside the existing string decision. Legacy approvals are retained but are not silently upgraded to content-bound authority.
- Approval and publishing each verify current source bytes. Content, target or source changes require fresh QA and Founder approval. Existing media receipts cause an idempotent no-op without new requests or state writes.
- Publish jobs check out the event's source commit, independently regenerate local certification evidence, and verify the branch head has not changed immediately before attempting release. A changed branch requires validation of the current controls/content, including revocations. Disarmed requests remain disarmed. The validation workflow uses no social/provider credentials.
- Queue preflight/revalidation failures persist a bounded category, underlying HTTP status when available, stage and run ID. Exception text, URLs, tokens and provider response bodies are excluded. The failure artifact does not add retries, switch providers or claim recovery.

## Existing state is intentionally not migrated

`state/control.json`, `data/control.json`, the historical calendar, decisions, published registry, qualification records, provider rotation and image rulebook remain unchanged. No certificate or Founder decision is manufactured. `data/approval_manifests.json` starts empty. Old unpublished posts require fresh content-bound QA followed by the Founder dashboard action. Current off/uncertified states still block release.

Certification output must be present at `certification/evidence/live-certification.json`. The publishing workflow generates it within the job; an authorized direct invocation must provide the same current evidence. Successful qualification does not set activation flags automatically.

## Remaining integration requirements

- Current Meta credentials and the `designinfra.interiors` mapping still need a live read-only diagnostic in the authorized credential environment. This patch changes no credential.
- The observed DeepSeek revalidation failure has not been recovered by a live provider call. The new sanitized failure record is intended to expose the next bounded failure accurately.
- The nine R11 PNG sources remain 1122 × 1402, below the unchanged 1200-pixel minimum source width. They are not silently upscaled, reapproved or imported into the production calendar by this change.
- The reviewed publisher remains a single-image Instagram implementation. R08's five-image comparison and Facebook Page publication need their own supported integration; a Facebook Graph hostname is not proof of Page publishing.
- A pre-publish byte check detects changes before release. Instagram fetches `image_url` separately; use retained, immutable media hosting for production to avoid changes between verification and platform ingestion. A remote byte check alone cannot prove the later ingestion bytes.
- No live publication, outreach, paid provider test, production activation or verified business outcome is claimed.

## Review and validation

The tests exercise the actual publisher/approval entrypoints with temporary files and mocked network boundaries, including rejected mismatches and a successful mocked flow. The validation workflow checks the release/approval/account guards, provider error sanitization, existing publisher/approval behavior, dashboard contract and caption/vision parsing. Full independent visual QA and live-provider qualification remain separate evidence stages.

The five governance contract checks now follow the current Founder-governed standalone contract and distinguish shadow qualification from production authority. Their former Victor-orchestrator and unconditional kill-switch assertions were obsolete; current activation files and provider qualifications are not changed by the test correction.
