import W, {phone, qualified} from '../leads.js';
class KV{constructor(){this.m=new Map();this.meta=new Map()}async get(k){return this.m.has(k)?this.m.get(k):null}async put(k,v,o){this.m.set(k,v);if(o?.metadata)this.meta.set(k,o.metadata)}
 async list({prefix,limit}){return {keys:[...this.m.keys()].filter(k=>k.startsWith(prefix)).sort().slice(0,limit).map(name=>({name,metadata:this.meta.get(name)}))}}}
let pass=0,fail=0;const ok=(n,c,x)=>{if(c)pass++;else{fail++;console.log('FAIL',n,x??'')}};
let tg=[];let tgMode='ok';globalThis.fetch=async(u,i)=>{u=String(u);tg.push({u,body:JSON.parse(i.body)});if(tgMode==='badchat'&&/(sendMessage|getChat)$/.test(u))return new Response(JSON.stringify({ok:false,description:'Bad Request: chat not found'}),{status:400});if(/getMe$/.test(u))return new Response(JSON.stringify({ok:true,result:{id:777,username:'di_leads_bot'}}),{status:200});if(tgMode==='selfchat'&&/sendMessage$/.test(u))return new Response(JSON.stringify({ok:false,description:"Forbidden: bot can't send messages to bots"}),{status:403});if(/getChat$/.test(u))return new Response(JSON.stringify({ok:true,result:{type:'private'}}),{status:200});return new Response('{"ok":true}',{status:200})};
const env=(o={})=>({LEADS:new KV(),WHATSAPP_NUMBER:'919800000000',ADMIN_KEY:'a'.repeat(32),...o});
const form=(f,ip='1.1.1.1')=>new Request('https://x/enquiry',{method:'POST',headers:{'cf-connecting-ip':ip},body:new URLSearchParams(f)});
const good={name:'Ravi Kumar',phone:'+91 98111-22233',area:'Noida',home:'3BHK',scope:'Full home interiors',budget:'₹6–10 lakh',timeline:'1–3 months',consent:'yes',src:'ig',post:'p001'};
const leads=e=>[...e.LEADS.m.entries()].filter(([k])=>/^r11_lead_2/.test(k)).map(([,v])=>JSON.parse(v));

// phone + qualification rules
ok('P1 phone forms',phone('+91 98111-22233')==='9811122233'&&phone('09811122233')==='9811122233'&&phone('919811122233')==='9811122233');
ok('P2 bad phones',phone('12345')===null&&phone('5811122233')===null&&phone('')===null);
ok('Q1 qualified',qualified({area:'Noida',budget:'₹6–10 lakh',timeline:'1–3 months'})&&!qualified({area:'Other',budget:'₹6–10 lakh',timeline:'1–3 months'})&&!qualified({area:'Noida',budget:'Under ₹3 lakh',timeline:'Within 1 month'})&&!qualified({area:'Noida',budget:'₹10 lakh+',timeline:'Just exploring'}));
// form page
{const e=env();const r=await W.fetch(new Request('https://x/enquiry?src=IG&post=p001<x>'),e);const h=await r.text();
 ok('F1 page',r.status===200&&h.includes('Free interior consultation')&&h.includes('value="ig"')&&h.includes('value="p001x"')&&h.includes('href="/wa?src=ig&amp;post=p001x"')===false&&h.includes('/wa?src=ig&post=p001x'));
 ok('F2 headers',r.headers.get('content-security-policy').includes("default-src 'none'")&&r.headers.get('x-robots-tag')==='noindex');
 ok('F3 view counted',[...e.LEADS.m.keys()].some(k=>/^r11_lead_count_\d{4}-\d\d-\d\d_view$/.test(k)));}
// valid submit
{tg=[];const e=env({TELEGRAM_BOT_TOKEN:'t',TELEGRAM_CHAT_ID:'c'});const r=await W.fetch(form(good),e);const h=await r.text();const l=leads(e);
 ok('S1 stored',r.status===200&&l.length===1&&l[0].phone==='9811122233'&&l[0].qualified===true&&l[0].consent===true&&l[0].src==='ig'&&l[0].post==='p001',l);
 ok('S2 thanks + wa',h.includes('Thank you, Ravi!')&&h.includes('https://wa.me/919800000000?text=')&&h.includes('+91 9811122233'));
 ok('S3 alert',tg.length===1&&tg[0].u==='https://api.telegram.org/bott/sendMessage'&&/qualified/.test(tg[0].body.text)&&/Ravi Kumar · \+91 9811122233/.test(tg[0].body.text)&&l[0].alert==='sent',tg[0]?.body?.text);
 ok('S4 no raw ip',!JSON.stringify(l[0]).includes('1.1.1.1'));}
// no alert configured -> still stored, alert state recorded
{const e=env();await W.fetch(form(good),e);ok('S5 alert not configured',leads(e)[0].alert==='not_configured');}
// validation
{const e=env();let r=await W.fetch(form({...good,phone:'123'}),e);ok('V1 bad phone',r.status===400&&(await r.text()).includes('valid 10-digit')&&leads(e).length===0);
 r=await W.fetch(form({...good,consent:''}),e);ok('V2 no consent',r.status===400&&leads(e).length===0);
 r=await W.fetch(form({...good,area:'Mumbai'}),e);ok('V3 bad option',r.status===400&&leads(e).length===0);
 r=await W.fetch(form({...good,name:'<b>x</b>',phone:'1'}),e);ok('V4 escaped',!(await r.text()).includes('<b>x</b>'));}
// honeypot + rate limit
{const e=env();const r=await W.fetch(form({...good,website:'spam.com'}),e);ok('H1 honeypot',r.status===200&&leads(e).length===0);
 for(let i=0;i<5;i++)await W.fetch(form(good,'2.2.2.2'),e);const r2=await W.fetch(form(good,'2.2.2.2'),e);ok('R1 rate limit',r2.status===429&&leads(e).length===5);
 const r3=await W.fetch(form(good,'3.3.3.3'),e);ok('R2 other ip ok',r3.status===200&&leads(e).length===6);}
// whatsapp redirect
{const e=env();const r=await W.fetch(new Request('https://x/wa?src=ig&post=p002'),e);ok('W1 redirect',r.status===302&&r.headers.get('location').startsWith('https://wa.me/919800000000?text='));
 ok('W2 counted',[...e.LEADS.m.keys()].some(k=>/_ig_p002$/.test(k))&&[...e.LEADS.m.keys()].some(k=>/_wa$/.test(k)));
 const r2=await W.fetch(new Request('https://x/wa'),env({WHATSAPP_NUMBER:''}));ok('W3 unconfigured',r2.status===503);}
// admin
{const e=env();await W.fetch(new Request('https://x/enquiry'),e);await W.fetch(form(good),e);
 let r=await W.fetch(new Request('https://x/leads?k=wrong'),e);ok('A1 gated',r.status===404);
 r=await W.fetch(new Request('https://x/leads'),env({ADMIN_KEY:''}));ok('A2 no key configured',r.status===404);
 r=await W.fetch(new Request(`https://x/leads?k=${'a'.repeat(32)}`),e);const h=await r.text();ok('A3 list',r.status===200&&h.includes('Ravi Kumar')&&h.includes('+91 9811122233')&&/Form leads 7d \/ 30d<b>1 \/ 1/.test(h)&&/Page views 7d \/ 30d<b>1 \/ 1/.test(h)&&/Qualified \(30d\)<b>1/.test(h),h.slice(0,0));}
// health
{const r=await W.fetch(new Request('https://x/health'),env());const j=await r.json();ok('HL',j.version==='1.0.4'&&j.whatsapp===true&&j.alerts===false);}
// diag: token/chat checks, last alert, no PII or secrets
{tgMode='ok';tg=[];const e=env({TELEGRAM_BOT_TOKEN:' t ',TELEGRAM_CHAT_ID:'c'});let j=await (await W.fetch(new Request('https://x/diag'),e)).json();
 ok('D1 empty',j.token_valid===true&&j.chat_reachable===true&&j.bot_username==='di_leads_bot'&&j.last_lead_at===null&&tg[0].u==='https://api.telegram.org/bott/getMe',j);
 tgMode='badchat';await W.fetch(form(good),e);j=await (await W.fetch(new Request('https://x/diag'),e)).json();
 ok('D2 bad chat',j.chat_reachable===false&&/chat not found/.test(j.chat_error)&&/^http_400: Bad Request: chat not found/.test(j.last_alert),j);
 ok('D3 no pii',!JSON.stringify(j).includes('Ravi')&&!JSON.stringify(j).includes('9811122233')&&!JSON.stringify(j).includes(' t '));tgMode='ok';}
// admin key tolerant of stray spaces
{const e=env({ADMIN_KEY:' '+'b'.repeat(32)+'\n'});const r=await W.fetch(new Request(`https://x/leads?k=${'b'.repeat(32)}%20`),e);ok('A4 trimmed key',r.status===200);}
// diag: self-chat detection + test message with Telegram's reason, rate limited
{tgMode='selfchat';const e=env({TELEGRAM_BOT_TOKEN:'t',TELEGRAM_CHAT_ID:'777'});let j=await (await W.fetch(new Request('https://x/diag?send=1'),e)).json();
 ok('D4 self chat',j.chat_id_is_the_bot_itself===true&&/^http_403: Forbidden: bot can't send messages to bots/.test(j.test_message),j);
 for(let i=0;i<3;i++)await W.fetch(new Request('https://x/diag?send=1'),e);j=await (await W.fetch(new Request('https://x/diag?send=1'),e)).json();ok('D5 rate limit',j.test_message==='rate_limited',j);
 tgMode='ok';const e2=env({TELEGRAM_BOT_TOKEN:'t',TELEGRAM_CHAT_ID:'123'});j=await (await W.fetch(new Request('https://x/diag?send=1'),e2)).json();ok('D6 sent',j.test_message==='sent'&&j.chat_id_is_the_bot_itself===false,j);
 j=await (await W.fetch(new Request('https://x/diag'),e2)).json();ok('D7 no send without flag',!('test_message' in j));}
console.log(`pass ${pass} fail ${fail}`);
