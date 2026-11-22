// designinfra-autopost-cron: a reliable clock for the R11 autopost.
// GitHub's own schedule fires this repo's hourly workflows only every few hours, so this
// Worker's cron (every hour at :47 UTC) asks GitHub to run "AURA3 R11 Autopost" in publish
// mode. The workflow itself decides whether anything is due and guards against double posts.
// Secret GH_DISPATCH_TOKEN (fine-grained token, aura-3.0 only, Actions: read & write) is
// entered by the founder in the Cloudflare dashboard. It is never returned or logged.
const VERSION = '1.0.0';
const REPO = 'vickykenin-lang/aura-3.0';
const WORKFLOW = 'aura3-r11-autopost.yml';
const TESTS_PER_HOUR = 3;

const json = (o, status = 200) => new Response(JSON.stringify(o, null, 2), {
  status, headers: { 'content-type': 'application/json', 'cache-control': 'no-store', 'x-robots-tag': 'noindex' } });

export async function dispatch(env, mode, source) {
  const token = String(env.GH_DISPATCH_TOKEN || '').trim();
  let result;
  if (!token) {
    result = 'not_configured';
  } else {
    try {
      const r = await fetch(`https://api.github.com/repos/${REPO}/actions/workflows/${WORKFLOW}/dispatches`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${token}`, Accept: 'application/vnd.github+json',
          'X-GitHub-Api-Version': '2022-11-28', 'User-Agent': 'designinfra-autopost-cron', 'Content-Type': 'application/json' },
        body: JSON.stringify({ ref: 'main', inputs: { mode } }),
      });
      if (r.status === 204) result = 'dispatched';
      else {
        let msg = '';
        try { msg = String((await r.json()).message || ''); } catch { /* not JSON */ }
        result = `http_${r.status}${msg ? ': ' + msg.split(token).join('[REDACTED]').slice(0, 160) : ''}`;
      }
    } catch {
      result = 'network_error';
    }
  }
  const rec = { at: new Date().toISOString(), mode, source, result };
  await env.KV.put('r11_cron_last', JSON.stringify(rec));
  if (source === 'cron') await env.KV.put('r11_cron_last_scheduled', JSON.stringify(rec));
  return result;
}

export default {
  async scheduled(event, env, ctx) {
    ctx.waitUntil(dispatch(env, 'publish', 'cron'));
  },
  async fetch(request, env) {
    const url = new URL(request.url);
    if (url.pathname !== '/health') return json({ error: 'not_found' }, 404);
    const read = async (k) => JSON.parse((await env.KV.get(k)) || 'null');
    const out = {
      version: VERSION,
      token_configured: Boolean(String(env.GH_DISPATCH_TOKEN || '').trim()),
      last_scheduled: await read('r11_cron_last_scheduled'),
      last_any: await read('r11_cron_last'),
    };
    if (url.searchParams.get('test') === '1') {   // read-only rehearsal run of the workflow
      const key = `r11_cron_test_${new Date().toISOString().slice(0, 13)}`;
      const n = Number((await env.KV.get(key)) || 0);
      if (n >= TESTS_PER_HOUR) out.test = 'rate_limited';
      else {
        await env.KV.put(key, String(n + 1), { expirationTtl: 7200 });
        out.test = await dispatch(env, 'dry-run', 'test');
      }
    }
    return json(out);
  },
};
