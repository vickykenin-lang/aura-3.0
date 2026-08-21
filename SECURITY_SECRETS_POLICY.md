# Secrets Policy (Founder lock — 22 Aug 2026)

**AURA2 secrets stay only in `design-infra-aura2`.**  
**No cross connection to Vision or any other department.**

| This repo only | Not shared with |
|----------------|-----------------|
| `GEMINI_API_KEY` / content keys | Vision / `dr-victor-orchestrator` |
| `DEEPSEEK_KEY` (SENTINEL) | Vision |
| `IG_USER_ID`, `IG_ACCESS_TOKEN` | Anywhere else |

Vision must use **its own** repo secrets.  
AURA2 Actions must never assume Vision keys exist here.

**Locked by Founder: sab department ki secret key usme hi rahenge, no cross connections.**
