import W, { dispatch } from '../worker.js';
class KV { constructor() { this.m = new Map(); } async get(k) { return this.m.has(k) ? this.m.get(k) : null; } async put(k, v) { this.m.set(k, v); } }
let pass = 0, fail = 0; const ok = (n, c, x) => { if (c) pass++; else { fail++; console.log('FAIL', n, x ?? ''); } };
let calls = [], mode = 'ok';
globalThis.fetch = async (u, i) => { calls.push({ u: String(u), i });
  if (mode === 'bad') return new Response(JSON.stringify({ message: 'Bad credentials' }), { status: 401 });
  if (mode === 'down') throw new Error('net');
  return new Response(null, { status: 204 }); };
const env = (o = {}) => ({ KV: new KV(), ...o });

{ const e = env(); ok('C1 no token', (await dispatch(e, 'publish', 'cron')) === 'not_configured' && calls.length === 0); }
{ calls = []; const e = env({ GH_DISPATCH_TOKEN: ' tok123 ' }); let waited; await W.scheduled({}, e, { waitUntil: p => { waited = p; } }); await waited;
  const c = calls[0]; const b = JSON.parse(c.i.body);
  ok('C2 cron dispatches publish', calls.length === 1 && c.u === 'https://api.github.com/repos/vickykenin-lang/aura-3.0/actions/workflows/aura3-r11-autopost.yml/dispatches'
    && c.i.headers.Authorization === 'Bearer tok123' && b.ref === 'main' && b.inputs.mode === 'publish', c);
  const last = JSON.parse(e.KV.m.get('r11_cron_last_scheduled')); ok('C3 recorded', last.result === 'dispatched' && last.source === 'cron'); }
{ mode = 'bad'; const e = env({ GH_DISPATCH_TOKEN: 'tok123' }); ok('C4 bad token reason', (await dispatch(e, 'publish', 'cron')) === 'http_401: Bad credentials'); mode = 'ok'; }
{ mode = 'down'; const e = env({ GH_DISPATCH_TOKEN: 'tok123' }); ok('C5 network', (await dispatch(e, 'publish', 'cron')) === 'network_error'); mode = 'ok'; }
{ calls = []; const e = env({ GH_DISPATCH_TOKEN: 'tok123' }); let j = await (await W.fetch(new Request('https://x/health'), e)).json();
  ok('H1 health no secret', j.token_configured === true && !JSON.stringify(j).includes('tok123') && calls.length === 0, j);
  for (let i = 0; i < 3; i++) { j = await (await W.fetch(new Request('https://x/health?test=1'), e)).json(); }
  ok('H2 test is dry-run', j.test === 'dispatched' && JSON.parse(calls[0].i.body).inputs.mode === 'dry-run' && calls.length === 3);
  j = await (await W.fetch(new Request('https://x/health?test=1'), e)).json(); ok('H3 rate limited', j.test === 'rate_limited' && calls.length === 3);
  ok('H4 404', (await W.fetch(new Request('https://x/'), e)).status === 404); }
console.log(`pass ${pass} fail ${fail}`);
