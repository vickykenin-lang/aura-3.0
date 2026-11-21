// R11 lead capture: enquiry form + WhatsApp click-to-chat for Design Infra (Delhi NCR residential interiors).
// Bindings: LEADS (KV). Vars: WHATSAPP_NUMBER (e.g. 91XXXXXXXXXX). Secrets: ADMIN_KEY, optional TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID for new-lead alerts.
const VERSION = '1.0.4';
const HANDLE = '@designinfra.interiors';
const AREAS = ['Delhi', 'Noida', 'Greater Noida', 'Gurugram', 'Ghaziabad', 'Faridabad', 'Other'];
const HOMES = ['1BHK', '2BHK', '3BHK', '4BHK+', 'Villa / Independent house'];
const SCOPES = ['Full home interiors', 'Modular kitchen', 'Wardrobes', 'Living room', 'Bedroom', 'Other'];
const BUDGETS = ['Under ₹3 lakh', '₹3–6 lakh', '₹6–10 lakh', '₹10 lakh+', 'Not sure yet'];
const TIMELINES = ['Within 1 month', '1–3 months', '3–6 months', 'Just exploring'];
const CONSENT_TEXT = 'I agree that Design Infra may contact me on WhatsApp or phone about this enquiry.';
const RATE_LIMIT = 5; // submissions per IP per hour
const headersBase = {'cache-control': 'no-store', 'x-content-type-options': 'nosniff', 'referrer-policy': 'no-referrer', 'x-robots-tag': 'noindex'};
const CSP = "default-src 'none'; style-src 'unsafe-inline'; img-src 'self' data:; form-action 'self'; base-uri 'none'; frame-ancestors 'none'";

const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
const hex = buf => [...new Uint8Array(buf)].map(b => b.toString(16).padStart(2, '0')).join('');
const sha = async s => hex(await crypto.subtle.digest('SHA-256', new TextEncoder().encode(s)));
function same(a, b) { a = String(a || ''); b = String(b || ''); if (!a || a.length !== b.length) return false; let d = 0; for (let i = 0; i < a.length; i++) d |= a.charCodeAt(i) ^ b.charCodeAt(i); return d === 0; }
const json = (d, s = 200) => new Response(JSON.stringify(d), {status: s, headers: {...headersBase, 'content-type': 'application/json'}});
const html = (body, s = 200) => new Response(body, {status: s, headers: {...headersBase, 'content-type': 'text/html; charset=utf-8', 'content-security-policy': CSP}});
const day = (d = new Date()) => d.toISOString().slice(0, 10);
const tag = v => String(v || '').toLowerCase().replace(/[^a-z0-9_-]/g, '').slice(0, 40) || 'direct';

// Indian mobile: accepts +91 / 91 / 0 prefixes, spaces and dashes; returns 10 digits or null.
function phone(v) {
  let d = String(v || '').replace(/[^\d]/g, '');
  if (d.length === 12 && d.startsWith('91')) d = d.slice(2);
  else if (d.length === 11 && d.startsWith('0')) d = d.slice(1);
  return /^[6-9]\d{9}$/.test(d) ? d : null;
}
// Default qualification rule (Founder can change): NCR area, budget band known and >= ₹3 lakh, timeline within 3 months.
function qualified(l) {
  return l.area !== 'Other' && ['₹3–6 lakh', '₹6–10 lakh', '₹10 lakh+'].includes(l.budget) && ['Within 1 month', '1–3 months'].includes(l.timeline);
}
function waLink(env, text) {
  const n = String(env.WHATSAPP_NUMBER || '').replace(/[^\d]/g, '');
  return n ? `https://wa.me/${n}?text=${encodeURIComponent(text)}` : null;
}
async function bump(env, key) { const n = Number(await env.LEADS.get(key)) || 0; await env.LEADS.put(key, String(n + 1), {expirationTtl: 60 * 60 * 24 * 400}); }

const STYLE = `:root{--ivory:#faf7f2;--ink:#1f2937;--muted:#6b7280;--amber:#b45309;--line:#e7e1d8}*{box-sizing:border-box}body{margin:0;background:var(--ivory);color:var(--ink);font:16px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif}
main{max-width:520px;margin:0 auto;padding:20px 16px 40px}.brand{display:flex;align-items:center;gap:10px;margin-bottom:14px}.logo{width:38px;height:38px;border-radius:10px;background:var(--amber);color:#fff;display:grid;place-items:center;font-weight:700}
.brand small{display:block;color:var(--muted);font-size:12px}h1{font-size:24px;line-height:1.25;margin:6px 0}p.lead{color:var(--muted);margin:0 0 16px}.wa{display:block;text-align:center;background:#15803d;color:#fff;text-decoration:none;font-weight:600;padding:13px;border-radius:12px;margin:12px 0 18px}
.or{text-align:center;color:var(--muted);font-size:13px;margin:4px 0 12px}form{background:#fff;border:1px solid var(--line);border-radius:14px;padding:16px}label{display:block;font-size:14px;font-weight:600;margin:12px 0 5px}
input,select{width:100%;font:inherit;padding:11px 12px;border:1px solid #d6cfc4;border-radius:10px;background:#fff;color:var(--ink)}.row{display:grid;grid-template-columns:1fr 1fr;gap:10px}.consent{display:flex;gap:9px;align-items:flex-start;font-weight:400;font-size:13px;color:var(--muted)}.consent input{width:auto;margin-top:3px}
button{width:100%;margin-top:16px;font:inherit;font-weight:700;color:#fff;background:var(--amber);border:0;border-radius:12px;padding:13px}.hp{position:absolute;left:-9999px}.err{background:#fef2f2;color:#991b1b;border-radius:10px;padding:10px 12px;font-size:14px}
.foot{color:var(--muted);font-size:12px;text-align:center;margin-top:16px}@media(max-width:380px){.row{grid-template-columns:1fr}}`;

function opts(list, sel) { return ['<option value="">Select</option>', ...list.map(v => `<option${v === sel ? ' selected' : ''}>${esc(v)}</option>`)].join(''); }
function page(title, body) {
  return `<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="robots" content="noindex"><title>${esc(title)}</title><style>${STYLE}</style></head><body><main>
<div class="brand"><div class="logo">DI</div><div><b>Design Infra</b><small>Turnkey interiors · Delhi NCR</small></div></div>${body}<p class="foot">${esc(HANDLE)} · Your details are used only to reply to this enquiry.</p></main></body></html>`;
}
function formPage(env, src, post, values = {}, error = '') {
  const wa = `/wa?src=${encodeURIComponent(src)}&post=${encodeURIComponent(post)}`;
  return page('Free consultation · Design Infra', `<h1>Free interior consultation</h1><p class="lead">Tell us about your home. Our designer will call or WhatsApp you within 24 hours.</p>
${env.WHATSAPP_NUMBER ? `<a class="wa" href="${wa}">Chat on WhatsApp</a><div class="or">or share details below</div>` : ''}
${error ? `<p class="err">${esc(error)}</p>` : ''}<form method="post" action="/enquiry">
<input type="hidden" name="src" value="${esc(src)}"><input type="hidden" name="post" value="${esc(post)}"><div class="hp"><label>Website<input name="website" tabindex="-1" autocomplete="off"></label></div>
<label for="n">Name</label><input id="n" name="name" required maxlength="80" autocomplete="name" value="${esc(values.name)}">
<label for="p">WhatsApp number</label><input id="p" name="phone" required inputmode="tel" autocomplete="tel" placeholder="98XXXXXXXX" value="${esc(values.phone)}">
<div class="row"><div><label for="a">Area</label><select id="a" name="area" required>${opts(AREAS, values.area)}</select></div><div><label for="h">Home</label><select id="h" name="home" required>${opts(HOMES, values.home)}</select></div></div>
<label for="s">What do you need?</label><select id="s" name="scope" required>${opts(SCOPES, values.scope)}</select>
<div class="row"><div><label for="b">Budget</label><select id="b" name="budget" required>${opts(BUDGETS, values.budget)}</select></div><div><label for="t">When?</label><select id="t" name="timeline" required>${opts(TIMELINES, values.timeline)}</select></div></div>
<label class="consent"><input type="checkbox" name="consent" value="yes" required${values.consent ? ' checked' : ''}> ${esc(CONSENT_TEXT)}</label>
<button type="submit">Book free consultation</button></form>`);
}

async function alert(env, lead) {
  if (!env.TELEGRAM_BOT_TOKEN || !env.TELEGRAM_CHAT_ID) return 'not_configured';
  const text = [`New Design Infra enquiry${lead.qualified ? ' (qualified)' : ''}`, `${lead.name} · +91 ${lead.phone}`, `${lead.area} · ${lead.home} · ${lead.scope}`, `${lead.budget} · ${lead.timeline}`, `Source: ${lead.src}${lead.post !== 'direct' ? ` / ${lead.post}` : ''}`].join('\n');
  try {
    const r = await fetch(`https://api.telegram.org/bot${String(env.TELEGRAM_BOT_TOKEN).trim()}/sendMessage`, {method: 'POST', headers: {'content-type': 'application/json'}, body: JSON.stringify({chat_id: String(env.TELEGRAM_CHAT_ID).trim(), text})});
    if (r.ok) return 'sent';
    const j = await r.json().catch(() => ({}));
    return `http_${r.status}${j.description ? `: ${String(j.description).slice(0, 120)}` : ''}`;
  } catch { return 'failed'; }
}

async function submit(request, env) {
  const f = await request.formData();
  const v = Object.fromEntries(['name', 'phone', 'area', 'home', 'scope', 'budget', 'timeline', 'consent', 'src', 'post', 'website'].map(k => [k, String(f.get(k) || '').trim()]));
  const src = tag(v.src), post = tag(v.post);
  if (v.website) return html(page('Thank you', '<h1>Thank you</h1>')); // honeypot: bots get a silent success
  const ipHash = (await sha(`${request.headers.get('cf-connecting-ip') || ''}|${env.ADMIN_KEY || ''}`)).slice(0, 16);
  const rlKey = `r11_lead_rl_${ipHash}_${new Date().toISOString().slice(0, 13)}`;
  if ((Number(await env.LEADS.get(rlKey)) || 0) >= RATE_LIMIT) return html(formPage(env, src, post, v, 'Too many submissions. Please try again in an hour or use WhatsApp.'), 429);
  const p = phone(v.phone);
  const bad = !v.name || v.name.length > 80 ? 'Please enter your name.' : !p ? 'Please enter a valid 10-digit Indian mobile number.'
    : !AREAS.includes(v.area) || !HOMES.includes(v.home) || !SCOPES.includes(v.scope) || !BUDGETS.includes(v.budget) || !TIMELINES.includes(v.timeline) ? 'Please answer all questions.'
    : v.consent !== 'yes' ? 'Please tick the consent box so we can contact you.' : '';
  if (bad) return html(formPage(env, src, post, v, bad), 400);
  const now = new Date();
  const lead = {id: crypto.randomUUID(), created_at: now.toISOString(), name: v.name, phone: p, area: v.area, home: v.home, scope: v.scope, budget: v.budget, timeline: v.timeline,
    consent: true, consent_text: CONSENT_TEXT, src, post, ip_hash: ipHash, status: 'NEW'};
  lead.qualified = qualified(lead);
  const key = `r11_lead_${now.toISOString().replace(/[-:.TZ]/g, '')}_${lead.id.slice(0, 8)}`;
  await env.LEADS.put(key, JSON.stringify(lead), {metadata: {created_at: lead.created_at, qualified: lead.qualified, src, post}});
  await bump(env, rlKey);
  await bump(env, `r11_lead_count_${day(now)}_form`);
  // Lead is saved before the alert so a failed alert never loses it; the alert result is then recorded on it.
  lead.alert = await alert(env, lead);
  await env.LEADS.put(key, JSON.stringify(lead), {metadata: {created_at: lead.created_at, qualified: lead.qualified, src, post}});
  const wa = waLink(env, `Hi Design Infra, I just booked a free consultation for my ${lead.home} in ${lead.area} (${lead.scope}).`);
  return html(page('Thank you · Design Infra', `<h1>Thank you, ${esc(lead.name.split(' ')[0])}!</h1><p class="lead">Our designer will contact you within 24 hours on +91 ${esc(p)}.</p>${wa ? `<a class="wa" href="${esc(wa)}">Say hi on WhatsApp now</a>` : ''}`));
}

async function adminPage(env, url) {
  const list = await env.LEADS.list({prefix: 'r11_lead_2', limit: 1000});
  const keys = list.keys.slice(-100).reverse();
  const leads = (await Promise.all(keys.map(k => env.LEADS.get(k.name)))).map(v => { try { return JSON.parse(v); } catch { return null; } }).filter(Boolean);
  const since = d => new Date(Date.now() - d * 864e5).toISOString().slice(0, 10);
  const sum = async (kind, d) => { let n = 0; for (let i = 0; i < d; i++) n += Number(await env.LEADS.get(`r11_lead_count_${since(i)}_${kind}`)) || 0; return n; };
  const [v7, w7, f7, v30, w30, f30] = await Promise.all([sum('view', 7), sum('wa', 7), sum('form', 7), sum('view', 30), sum('wa', 30), sum('form', 30)]);
  const q30 = list.keys.filter(k => k.metadata?.qualified && k.metadata.created_at >= since(29)).length;
  const rows = leads.map(l => `<tr><td>${esc(l.created_at.slice(0, 16).replace('T', ' '))}</td><td>${esc(l.name)}</td><td><a href="https://wa.me/91${esc(l.phone)}">+91 ${esc(l.phone)}</a></td><td>${esc(l.area)}</td><td>${esc(l.home)}</td><td>${esc(l.scope)}</td><td>${esc(l.budget)}</td><td>${esc(l.timeline)}</td><td>${l.qualified ? 'Yes' : ''}</td><td>${esc(l.src)}/${esc(l.post)}</td></tr>`).join('');
  return html(`<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Leads</title><style>${STYLE}main{max-width:1100px}table{border-collapse:collapse;width:100%;font-size:13px;background:#fff}td,th{border-bottom:1px solid var(--line);padding:6px 8px;text-align:left;vertical-align:top}.k{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px;margin:12px 0}.k div{background:#fff;border:1px solid var(--line);border-radius:12px;padding:10px}.k b{display:block;font-size:22px}.wrap{overflow-x:auto}</style></head><body><main>
<h1>R11 leads</h1><div class="k"><div>Page views 7d / 30d<b>${v7} / ${v30}</b></div><div>WhatsApp clicks 7d / 30d<b>${w7} / ${w30}</b></div><div>Form leads 7d / 30d<b>${f7} / ${f30}</b></div><div>Qualified (30d)<b>${q30}</b></div><div>Target<b>30 / month</b></div></div>
<div class="wrap"><table><tr><th>Time (UTC)</th><th>Name</th><th>WhatsApp</th><th>Area</th><th>Home</th><th>Scope</th><th>Budget</th><th>When</th><th>Qualified</th><th>Source</th></tr>${rows || '<tr><td colspan="10">No leads yet</td></tr>'}</table></div></main></body></html>`);
}

// Setup check with no lead details and no secrets: is the Telegram bot token valid, can the bot reach the chat, what happened to the last alert.
async function diag(env, url) {
  const out = {version: VERSION, whatsapp: Boolean(env.WHATSAPP_NUMBER), admin_key_set: Boolean(env.ADMIN_KEY), telegram_configured: Boolean(env.TELEGRAM_BOT_TOKEN && env.TELEGRAM_CHAT_ID)};
  if (out.telegram_configured) {
    const tg = async (m, body) => { try { const r = await fetch(`https://api.telegram.org/bot${String(env.TELEGRAM_BOT_TOKEN).trim()}/${m}`, {method: 'POST', headers: {'content-type': 'application/json'}, body: JSON.stringify(body || {})}); const j = await r.json().catch(() => ({})); return {ok: Boolean(j.ok), status: r.status, description: j.description || null, result: j.result || null}; } catch { return {ok: false, status: 0, description: 'network_error'}; } };
    const me = await tg('getMe');
    out.token_valid = me.ok; out.token_error = me.ok ? null : me.description; out.bot_username = me.result?.username || null;
    if (me.ok) {
      const chatId = String(env.TELEGRAM_CHAT_ID).trim();
      out.chat_id_is_the_bot_itself = chatId === String(me.result?.id); // a bot cannot message itself: Telegram answers 403
      const chat = await tg('getChat', {chat_id: chatId}); out.chat_reachable = chat.ok; out.chat_type = chat.result?.type || null; out.chat_error = chat.ok ? null : chat.description;
      // ?send=1 sends one test message and reports Telegram's answer; at most 3 an hour so the public URL cannot spam the chat
      if (url.searchParams.get('send') === '1') {
        const rl = `r11_lead_diag_send_${new Date().toISOString().slice(0, 13)}`;
        if ((Number(await env.LEADS.get(rl)) || 0) >= 3) out.test_message = 'rate_limited';
        else { await bump(env, rl); const t = await tg('sendMessage', {chat_id: chatId, text: 'Design Infra leads: test alert. If you can read this, new-lead alerts work.'}); out.test_message = t.ok ? 'sent' : `http_${t.status}: ${t.description || ''}`; }
      }
    }
  }
  const list = await env.LEADS.list({prefix: 'r11_lead_2', limit: 1000});
  const last = list.keys[list.keys.length - 1];
  if (last) { try { const l = JSON.parse(await env.LEADS.get(last.name)); out.last_lead_at = l.created_at; out.last_alert = l.alert || null; } catch {} }
  else out.last_lead_at = null;
  return out;
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (!env.LEADS) return json({error: 'kv_binding_missing'}, 503);
    if (url.pathname === '/health') return json({worker: 'designinfra-leads', version: VERSION, whatsapp: Boolean(env.WHATSAPP_NUMBER), alerts: Boolean(env.TELEGRAM_BOT_TOKEN && env.TELEGRAM_CHAT_ID), admin: Boolean(env.ADMIN_KEY)});
    if (url.pathname === '/' || url.pathname === '/enquiry') {
      if (request.method === 'POST') return submit(request, env);
      if (request.method !== 'GET') return json({error: 'method_not_allowed'}, 405);
      await bump(env, `r11_lead_count_${day()}_view`);
      return html(formPage(env, tag(url.searchParams.get('src')), tag(url.searchParams.get('post'))));
    }
    if (url.pathname === '/diag') return json(await diag(env, url));
    if (url.pathname === '/wa') {
      const wa = waLink(env, 'Hi Design Infra, I would like a free interior consultation.');
      if (!wa) return json({error: 'whatsapp_not_configured'}, 503);
      await bump(env, `r11_lead_count_${day()}_wa`);
      await bump(env, `r11_lead_wa_${day()}_${tag(url.searchParams.get('src'))}_${tag(url.searchParams.get('post'))}`);
      return new Response(null, {status: 302, headers: {...headersBase, location: wa}});
    }
    if (url.pathname === '/leads') {
      if (!env.ADMIN_KEY || !same(String(url.searchParams.get('k') || '').trim(), String(env.ADMIN_KEY).trim())) return json({error: 'not_found'}, 404);
      return adminPage(env, url);
    }
    return json({error: 'not_found'}, 404);
  }
};
export {phone, qualified};
