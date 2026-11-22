# designinfra-autopost-cron

Reliable hourly clock for **AURA3 R11 Autopost**. GitHub's own `schedule` fires this repo's
hourly workflows only every few hours, so this Worker's cron (`47 * * * *`, UTC) calls GitHub's
`workflow_dispatch` for `aura3-r11-autopost.yml` with `mode: publish`. The workflow decides
whether anything is due and guards against double posts, so extra or missed ticks are harmless.

- Binding: `KV` → R11 namespace (keys `r11_cron_*`).
- Secret: `GH_DISPATCH_TOKEN`, a fine-grained GitHub token limited to `vickykenin-lang/aura-3.0`
  with **Actions: Read and write**. Entered by the founder in the Cloudflare dashboard only.
- `GET /health` shows version, whether the token is set, and the last dispatch result
  (never the token). `GET /health?test=1` dispatches a read-only dry run (max 3 per hour).

Tests: `node test/t.mjs`
