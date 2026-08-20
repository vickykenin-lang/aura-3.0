# AURA2 setup (Founder checklist)

Secrets page:  
`https://github.com/vickykenin-lang/design-infra-aura2/settings/secrets/actions`

## Required keys (status as of 20 Aug 2026)

| Secret Name         | Purpose                        | Status          |
|---------------------|--------------------------------|-----------------|
| `GEMINI_API_KEY`    | Vision + creative + Department AI | **Added**      |
| `DEEPSEEK_KEY`      | Hard score gate ≥7              | **Added**      |
| `IG_USER_ID`        | Instagram publish              | Still needed   |
| `IG_ACCESS_TOKEN`   | Instagram publish              | Still needed   |

## Strongly recommended (later)
- `UNSPLASH_ACCESS_KEY`
- `KIMI_API_KEY`
- Cloudflare / Pinterest keys if needed

## Pages
- Settings → Pages → Deploy from `main` / `/ (root)`
- Bio link = this repo’s `leads.html` when Pages is live

## Note on secret names
Founder added `DEEPSEEK_KEY` (not `DEEPSEEK_API_KEY`).  
All code and docs now use `DEEPSEEK_KEY` to match.
