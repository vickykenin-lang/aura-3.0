# designinfra-leads (R11 lead capture)

Cloudflare Worker `designinfra-leads`: enquiry form + WhatsApp click-to-chat for Design Infra (Delhi NCR residential interiors).

- Live: https://designinfra-leads.vickykenin.workers.dev/enquiry?src=ig_bio
- Routes: `/enquiry` (form, GET/POST), `/wa` (WhatsApp redirect with click count), `/leads?k=ADMIN_KEY` (private lead list + funnel), `/diag` (setup check, no lead data; `?send=1` sends one test alert, max 3/hour), `/health`.
- Bindings: `LEADS` KV (R11 namespace, keys `r11_lead_*`), `WHATSAPP_NUMBER` (plain text).
- Secrets (set by the Founder in the Cloudflare dashboard, never in code or chat): `ADMIN_KEY`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`.
- Qualified lead rule: NCR area, budget ₹3 lakh+, timeline within 3 months.

Tests: `node test/t.mjs` (no install needed).
