# AURA2 Department AI Assignment (Updated)

**Date:** 21 August 2026  
**Decided by:** Dr. Victor (Grok)  
**Founder:** Vicky

## Hierarchy (top → down)

```text
Vicky (Human Owner)
    → Dr. Victor / Grok (CEO · performance judge)
        → SENTINEL (DeepSeek)  ← NEW: agent ABOVE AURA runner
            → AURA2 Runner (Gemini)  ← daily content worker
                → Instagram publish / leads
```

## Official Assignment

| Role | AI | Duty |
|------|-----|------|
| **CEO / Manager** | **Grok (Victor)** | Org-level decisions, swap agents if results fail |
| **Department Supervisor (ABOVE AURA)** | **DeepSeek — codename SENTINEL** | Cross-validation, quality gate ≥7, reject bad visuals, audit runner output, daily QC report |
| **Primary Department AI Runner** | **Gemini — AURA2** | Create interior candidates, captions, hooks (must pass Sentinel) |
| **Backup generation** | Groq / free pools | When Gemini limited |
| **Publish** | GitHub Action + IG API | Only after Founder Approve on gate-pass cards |

## Why Sentinel above AURA?
- Problem: wrong images reached approve queue; mock scores without real check
- Fix: **independent agent above the runner** — DeepSeek does not create the post; it only judges
- Creator ≠ final judge (anti-bias)
- Real ping: `scripts/score_with_deepseek.py` + `quality_gate.yml`

## Rules for Sentinel (DeepSeek)
1. Hard reject: animals, pure landscape, railway, food-only, random stock, kids
2. Only interiors (living/kitchen/bedroom/bath/dining/office) can pass
3. Caption must match room + CTA + conversion signal
4. Score ≥7 and `pass: true` required for dashboard queue
5. Write results to `data/gate_results.json`
6. Report failures with reasons — no silent approve

## Rules for AURA2 Runner (Gemini)
1. Only produce Design Infra interior content
2. Never bypass Sentinel
3. Success metric = real_leads > 0 with quality intact
4. Follow `CONTENT_RULES.md` + `DEPARTMENT_AI_INSTRUCTIONS.md`

## Performance Rule
Victor may replace Runner or Sentinel if results stay red (0 leads + quality failures).

**Assignment locked with Supervisor layer.**
