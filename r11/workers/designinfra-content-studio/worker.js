// designinfra-content-studio: Workers AI for the R11 content agents.
// Only GitHub Actions runs of vickykenin-lang/aura-3.0 can call it: each request carries a
// GitHub OIDC token (audience "designinfra-content-studio") that is verified here against
// GitHub's public keys. No shared secret exists anywhere. Daily caps keep usage inside the
// Workers AI free allowance.
export const VERSION = '1.3.0';
export const AUD = 'designinfra-content-studio';
export const ISS = 'https://token.actions.githubusercontent.com';
export const REPO = 'vickykenin-lang/aura-3.0';
export const REFS = ['refs/heads/main', 'refs/heads/r11/design-kit'];
export const MODELS = {
  image: '@cf/black-forest-labs/flux-2-klein-9b',
  drawing: '@cf/black-forest-labs/flux-2-klein-4b',   // reference edit: render -> line drawing
  text: '@cf/meta/llama-3.3-70b-instruct-fp8-fast',
  vision: '@cf/meta/llama-4-scout-17b-16e-instruct',
};
// Workers AI free allocation is 10,000 neurons/day for the whole account. Measured cost:
// klein-9b image ~1,409, scout vision ~41, llama-3.3 text ~101. Worst case 4*1409 + 50*41 + 15*101 = 9,201.
// klein-4b drawing (one 512 px reference in): kept to 2 a day until its cost is measured.
export const DAILY = { image: 4, text: 15, vision: 50, drawing: 2 };

const json = (o, status = 200) => new Response(JSON.stringify(o), {
  status, headers: { 'content-type': 'application/json', 'cache-control': 'no-store', 'x-robots-tag': 'noindex' } });

function b64url(s) {
  const t = String(s).replace(/-/g, '+').replace(/_/g, '/');
  const bin = atob(t + '='.repeat((4 - (t.length % 4)) % 4));
  return Uint8Array.from(bin, c => c.charCodeAt(0));
}

let jwksCache = null, jwksAt = 0;
async function githubKeys() {
  if (jwksCache && Date.now() - jwksAt < 3600e3) return jwksCache;
  const r = await fetch(ISS + '/.well-known/jwks');
  if (!r.ok) throw new Error('jwks_unavailable');
  jwksCache = (await r.json()).keys || [];
  jwksAt = Date.now();
  return jwksCache;
}

export async function verifyOidc(token, getKeys = githubKeys, now = Date.now() / 1000) {
  const parts = String(token || '').split('.');
  if (parts.length !== 3) return { ok: false, why: 'malformed' };
  let header, claims;
  try {
    header = JSON.parse(new TextDecoder().decode(b64url(parts[0])));
    claims = JSON.parse(new TextDecoder().decode(b64url(parts[1])));
  } catch { return { ok: false, why: 'malformed' }; }
  if (header.alg !== 'RS256') return { ok: false, why: 'alg' };
  const jwk = (await getKeys()).find(k => k.kid === header.kid);
  if (!jwk) return { ok: false, why: 'unknown_key' };
  const key = await crypto.subtle.importKey('jwk', { kty: 'RSA', n: jwk.n, e: jwk.e, alg: 'RS256', ext: true },
    { name: 'RSASSA-PKCS1-v1_5', hash: 'SHA-256' }, false, ['verify']);
  const good = await crypto.subtle.verify('RSASSA-PKCS1-v1_5', key, b64url(parts[2]),
    new TextEncoder().encode(parts[0] + '.' + parts[1]));
  if (!good) return { ok: false, why: 'signature' };
  const aud = Array.isArray(claims.aud) ? claims.aud : [claims.aud];
  if (claims.iss !== ISS) return { ok: false, why: 'issuer' };
  if (!aud.includes(AUD)) return { ok: false, why: 'audience' };
  if (!(claims.exp > now) || (claims.nbf && claims.nbf > now + 60)) return { ok: false, why: 'expired' };
  if (claims.repository !== REPO) return { ok: false, why: 'repository' };
  if (!REFS.includes(claims.ref)) return { ok: false, why: 'ref' };
  return { ok: true, claims };
}

const usageKey = kind => `r11_studio_${kind}_${new Date().toISOString().slice(0, 10)}`;

async function underCap(env, kind) {
  return Number((await env.KV.get(usageKey(kind))) || 0) < DAILY[kind];
}

// only calls that actually ran are counted (a refused or failed AI call costs no neurons)
async function count(env, kind) {
  const n = Number((await env.KV.get(usageKey(kind))) || 0);
  await env.KV.put(usageKey(kind), String(n + 1), { expirationTtl: 3 * 86400 });
}

function text(result) {
  if (typeof result === 'string') return result;
  const r = result?.response;
  return typeof r === 'string' ? r : JSON.stringify(r ?? result);
}

async function runImage(env, body) {
  const prompt = String(body.prompt || '').slice(0, 2000);
  if (prompt.length < 20) throw new Error('prompt_too_short');
  const width = Math.min(1280, Math.max(512, Number(body.width) || 1024));
  const height = Math.min(1280, Math.max(512, Number(body.height) || 1280));
  const form = new FormData();
  form.append('prompt', prompt);
  form.append('width', String(width));
  form.append('height', String(height));
  const enc = new Response(form);
  const out = await env.AI.run(MODELS.image, { multipart: { body: enc.body, contentType: enc.headers.get('content-type') } });
  if (!out || typeof out.image !== 'string') throw new Error('no_image');
  return { image_b64: out.image.replace(/^data:image\/[^;]+;base64,/, ''), model: MODELS.image, width, height };
}

// Turns a render into a line drawing of the same room: the render goes in as input_image_0
// (FLUX.2 klein multi-reference editing; every input image must be under 512x512).
async function runDrawing(env, body) {
  const prompt = String(body.prompt || '').slice(0, 2000);
  if (prompt.length < 20) throw new Error('prompt_too_short');
  const ref = String(body.image_b64 || '');
  if (!ref || ref.length > 700000) throw new Error('reference_image_required');
  const bytes = Uint8Array.from(atob(ref), c => c.charCodeAt(0));
  const width = Math.min(1280, Math.max(512, Number(body.width) || 1024));
  const height = Math.min(1280, Math.max(512, Number(body.height) || 1280));
  const form = new FormData();
  form.append('prompt', prompt);
  form.append('input_image_0', new Blob([bytes], { type: 'image/jpeg' }), 'render.jpg');
  form.append('width', String(width));
  form.append('height', String(height));
  const enc = new Response(form);
  const out = await env.AI.run(MODELS.drawing, { multipart: { body: enc.body, contentType: enc.headers.get('content-type') } });
  if (!out || typeof out.image !== 'string') throw new Error('no_image');
  return { image_b64: out.image.replace(/^data:image\/[^;]+;base64,/, ''), model: MODELS.drawing, width, height };
}

async function runText(env, body) {
  const messages = Array.isArray(body.messages) ? body.messages.slice(0, 8) : null;
  if (!messages) throw new Error('messages_required');
  const input = { messages, max_tokens: Math.min(1500, Number(body.max_tokens) || 700), temperature: Number(body.temperature ?? 0.7) };
  if (body.json_schema) input.response_format = { type: 'json_schema', json_schema: body.json_schema };
  return { text: text(await env.AI.run(MODELS.text, input)), model: MODELS.text };
}

async function runVision(env, body) {
  const images = Array.isArray(body.images) ? body.images.slice(0, 4) : [];
  if (!images.length) throw new Error('images_required');
  const content = [{ type: 'text', text: String(body.prompt || '').slice(0, 4000) }];
  for (const b of images) content.push({ type: 'image_url', image_url: { url: 'data:image/jpeg;base64,' + String(b) } });
  const input = { messages: [{ role: 'user', content }], max_tokens: Math.min(1200, Number(body.max_tokens) || 600), temperature: 0.1 };
  if (body.json_schema) input.response_format = { type: 'json_schema', json_schema: body.json_schema };
  return { text: text(await env.AI.run(MODELS.vision, input)), model: MODELS.vision };
}

const HANDLERS = { '/image': ['image', runImage], '/drawing': ['drawing', runDrawing], '/text': ['text', runText],
  '/vision': ['vision', runVision] };

export default {
  async fetch(request, env, ctx, deps = {}) {
    const url = new URL(request.url);
    if (url.pathname === '/health' && request.method === 'GET') {
      const day = new Date().toISOString().slice(0, 10);
      const used = {};
      for (const k of Object.keys(DAILY)) used[k] = `${Number((await env.KV.get(`r11_studio_${k}_${day}`)) || 0)}/${DAILY[k]}`;
      return json({ version: VERSION, models: MODELS, used_today: used });
    }
    const h = HANDLERS[url.pathname];
    if (!h || request.method !== 'POST') return json({ error: 'not_found' }, 404);
    const auth = request.headers.get('authorization') || '';
    const v = await verifyOidc(auth.replace(/^Bearer\s+/i, ''), deps.getKeys || githubKeys);
    if (!v.ok) return json({ error: 'unauthorized', why: v.why }, 401);
    let body;
    try { body = await request.json(); } catch { return json({ error: 'bad_json' }, 400); }
    if (!(await underCap(env, h[0]))) return json({ error: 'daily_cap_reached', kind: h[0] }, 429);
    try {
      const out = await h[1](env, body);
      await count(env, h[0]);
      return json(out);
    } catch (e) {
      return json({ error: 'ai_error', detail: String(e?.message || e).slice(0, 200) }, 502);
    }
  },
};
