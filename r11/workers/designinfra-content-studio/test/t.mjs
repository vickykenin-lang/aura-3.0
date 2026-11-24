import W, { verifyOidc, AUD, ISS, REPO, DAILY, VERSION } from '../worker.js';
class KV { constructor() { this.m = new Map(); } async get(k) { return this.m.has(k) ? this.m.get(k) : null; } async put(k, v) { this.m.set(k, v); } }
let pass = 0, fail = 0; const ok = (n, c, x) => { if (c) pass++; else { fail++; console.log('FAIL', n, x ?? ''); } };
const enc = o => Buffer.from(JSON.stringify(o)).toString('base64url');
const pair = await crypto.subtle.generateKey({ name: 'RSASSA-PKCS1-v1_5', modulusLength: 2048, publicExponent: new Uint8Array([1, 0, 1]), hash: 'SHA-256' }, true, ['sign', 'verify']);
const other = await crypto.subtle.generateKey({ name: 'RSASSA-PKCS1-v1_5', modulusLength: 2048, publicExponent: new Uint8Array([1, 0, 1]), hash: 'SHA-256' }, true, ['sign', 'verify']);
const pub = { ...(await crypto.subtle.exportKey('jwk', pair.publicKey)), kid: 'k1' };
const getKeys = async () => [pub];
const now = Math.floor(Date.now() / 1000);
const good = { iss: ISS, aud: AUD, exp: now + 300, nbf: now - 5, repository: REPO, ref: 'refs/heads/main' };
async function jwt(claims, key = pair.privateKey, kid = 'k1', alg = 'RS256') {
  const h = enc({ alg, kid, typ: 'JWT' }), p = enc(claims);
  const sig = await crypto.subtle.sign('RSASSA-PKCS1-v1_5', key, new TextEncoder().encode(h + '.' + p));
  return h + '.' + p + '.' + Buffer.from(sig).toString('base64url');
}
ok('J1 valid', (await verifyOidc(await jwt(good), getKeys)).ok === true);
for (const [name, c, why] of [['repo', { ...good, repository: 'evil/aura-3.0' }, 'repository'], ['aud', { ...good, aud: 'other' }, 'audience'],
  ['exp', { ...good, exp: now - 1 }, 'expired'], ['iss', { ...good, iss: 'https://evil' }, 'issuer'], ['ref', { ...good, ref: 'refs/heads/feature' }, 'ref'],
  ['branch ok', { ...good, ref: 'refs/heads/r11/design-kit' }, null]]) {
  const v = await verifyOidc(await jwt(c), getKeys); ok('J2 ' + name, why ? v.why === why : v.ok, v);
}
ok('J3 forged signature', (await verifyOidc(await jwt(good, other.privateKey), getKeys)).why === 'signature');
ok('J4 unknown kid', (await verifyOidc(await jwt(good, pair.privateKey, 'k9'), getKeys)).why === 'unknown_key');
ok('J5 alg none', (await verifyOidc(enc({ alg: 'none', kid: 'k1' }) + '.' + enc(good) + '.', getKeys)).why === 'alg');
ok('J6 garbage', (await verifyOidc('abc', getKeys)).why === 'malformed');

let runs = [];
const AI = { async run(model, input) { runs.push({ model, input });
  if (model.includes('flux')) return { image: 'data:image/jpeg;base64,QUJD' };
  return { response: model.includes('scout') ? '{"ok":true}' : 'hello' }; } };
const env = () => ({ KV: new KV(), AI });
const req = (path, body, token) => new Request('https://x' + path, { method: 'POST', headers: token ? { authorization: 'Bearer ' + token } : {}, body: JSON.stringify(body) });
{ const e = env(); const t = await jwt(good);
  let r = await W.fetch(req('/text', { messages: [{ role: 'user', content: 'hi' }] }, t), e, {}, { getKeys }); let j = await r.json();
  ok('A1 text', r.status === 200 && j.text === 'hello' && runs.at(-1).model.includes('llama-3.3'), j);
  r = await W.fetch(req('/text', { messages: [] }), e, {}, { getKeys }); ok('A2 no token 401', r.status === 401);
  r = await W.fetch(req('/image', { prompt: 'a warm modern living room interior photo' }, t), e, {}, { getKeys }); j = await r.json();
  ok('A3 image', r.status === 200 && j.image_b64 === 'QUJD' && j.width === 1024 && j.height === 1280 && runs.at(-1).input.multipart.contentType.startsWith('multipart/form-data'), j);
  r = await W.fetch(req('/image', { prompt: 'short' }, t), e, {}, { getKeys }); ok('A4 short prompt 502', r.status === 502);
  r = await W.fetch(req('/vision', { prompt: 'rate', images: ['QUJD'], json_schema: { type: 'object' } }, t), e, {}, { getKeys }); j = await r.json();
  const vin = runs.at(-1).input;
  ok('A5 vision', r.status === 200 && j.text === '{"ok":true}' && vin.messages[0].content[1].image_url.url === 'data:image/jpeg;base64,QUJD' && vin.response_format.type === 'json_schema', j);
  for (let i = 0; i < 12; i++) await W.fetch(req('/image', { prompt: 'a warm modern living room interior photo' }, t), e, {}, { getKeys });
  r = await W.fetch(req('/image', { prompt: 'a warm modern living room interior photo' }, t), e, {}, { getKeys }); ok('A6 daily cap', r.status === 429);
  { const e2 = { KV: new KV(), AI: { async run() { throw new Error('4006: daily free allocation used up'); } } };
    for (let i = 0; i < 6; i++) await W.fetch(req('/text', { messages: [{ role: 'user', content: 'x' }] }, t), e2, {}, { getKeys });
    const h2 = await (await W.fetch(new Request('https://x/health'), e2)).json();
    ok('A10 failed calls not counted', h2.used_today.text === '0/' + DAILY.text, h2); }
  r = await W.fetch(new Request('https://x/health'), e); j = await r.json(); ok('A7 health', j.used_today.image === `${DAILY.image}/${DAILY.image}` && j.version === VERSION, j);
  r = await W.fetch(new Request('https://x/'), e); ok('A8 404', r.status === 404);
  r = await W.fetch(req('/text', { messages: [{ role: 'user', content: 'x' }] }, await jwt({ ...good, repository: 'evil/x' })), e, {}, { getKeys }); j = await r.json();
  ok('A9 other repo 401', r.status === 401 && j.why === 'repository'); }
console.log(`pass ${pass} fail ${fail}`);
