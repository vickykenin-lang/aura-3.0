# AURA3 × Hugging Face — Phase 0 Baseline Lock

**Baseline ID:** `HF_BASELINE_V1`  
**Scope:** Pre-Hugging-Face AURA3 baseline  
**Frozen against main SHA:** `db90240102b75903b435b40eec3cc71fa277292d`  
**Phase status:** `BASELINE_VERIFIED`

## 1. Fresh runtime evidence

Fresh AURA3 Heartbeat run #37 (`run_id=33590969111`) completed successfully on 2026-09-02 and observed AURA3 as `HEALTHY`.

- runtime verified: true
- cadence: 60 minutes
- miss count: 0
- miss state: NONE
- business execution allowed: true
- kill switch: false
- constitutional binding checked: true

Truth boundary: heartbeat evidence proves runtime liveness only. It does not independently prove provider qualification, capability qualification, Victor transport, business outcome, or LIVE certification.

## 2. Canonical department state

Source: `state/department_state.json`

- department state: `LIVE_CERTIFIED`
- live certification: `VERIFIED`
- business execution: `ENABLED_BY_FOUNDER`
- Victor connection: `CONNECTED_VERIFIED`
- provider health: `VERIFIED_BY_RUNTIME_WORKFLOW`
- capability health: `VERIFIED_BY_RUNTIME_WORKFLOW`
- operating mode: `GOVERNED_SELF_MODE`
- qualified leads: `0`
- business outcome: `LIVE_RUNTIME_CERTIFIED_NO_BUSINESS_OUTCOME_CLAIM`

## 3. Existing provider baseline

Source: `runtime/provider_qualification.json`

Persisted qualification evidence shows:

- `AI_PROVIDER_1` = Gemini — QUALIFIED
- `AI_PROVIDER_2` = DeepSeek — QUALIFIED

These qualifications were not re-run during Phase 0; Phase 0 preserves their existing persisted evidence rather than fabricating fresh qualification.

## 4. Existing capability baseline

Source: `runtime/capability_qualification.json`

Persisted evidence records:

- content generation — VERIFIED
- visual quality gate — VERIFIED
- business quality gate — VERIFIED
- founder approval gate — VERIFIED_FAIL_CLOSED
- external publish — FOUNDER_ONLY_ACTIVATED
- reporting — VERIFIED

## 5. Historical quality benchmark

Source: `data/gate_results.json`, updated 2026-08-22.

Pipeline: `Gemini Vision -> DeepSeek Business Gate`

- evaluated cases: 10
- passed: 9
- rejected: 1
- pass rate: 90%
- accepted-post average business score: 8.33/10
- overall average including rejection: 7.50/10

This is historical technical/quality evidence. It is not current real-world business-outcome evidence.

## 6. Publication and business baseline

`content/published.json` currently contains no canonical published entries.

Canonical `state/department_state.json` records:

- qualified leads: 0
- real business outcome verified: no

No revenue, enquiry, conversion, or lead outcome should be inferred beyond this evidence.

## 7. Metrics not currently instrumented

The following are explicitly locked as `NOT_MEASURED`, not zero:

- AI cost per post
- provider cost split
- inference latency per post
- manual review minutes per post
- engagement rate
- saves
- profile visits
- website clicks
- enquiries
- lead-to-meeting conversion
- revenue attribution

Future HF business-outcome claims must not claim improvement on any of these metrics unless measurement evidence is added.

## 8. Repository truth notes

For Phase 0 comparison, `state/department_state.json` plus fresh runtime evidence is treated as canonical state.

Known stale/legacy sources:

- `README.md` still contains older PAUSED / LIVE NOT_VERIFIED wording.
- `data/status.json` contains legacy AURA2 controlled-pilot state.

These sources must not override current canonical AURA3 state.

## 9. Hugging Face starting state

Repository searches for `huggingface` and `HF_` returned no source matches on the current main baseline.

Therefore:

- HF source implemented: NO
- HF test passed: NO
- HF production deployed: NO
- HF live verified: NO
- HF business outcome verified: NO

## 10. Comparison contract

All future Hugging Face work must preserve this evidence ladder:

`SOURCE IMPLEMENTED -> TEST PASSED -> PRODUCTION DEPLOYED -> LIVE VERIFIED -> REAL BUSINESS OUTCOME VERIFIED`

No later stage may be inferred from an earlier stage.

## Phase 0 exit decision

`BASELINE_VERIFIED`

Phase 0 is complete. This branch contains baseline evidence only and does not modify AURA3 production runtime, provider selection, credentials, publishing behavior, or Hugging Face integration.
