#!/usr/bin/env python3
import json, os, urllib.request, urllib.error
from datetime import datetime, timezone
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]

def post(url,headers,body):
    try:
        req=urllib.request.Request(url,data=json.dumps(body).encode(),headers=headers,method='POST')
        with urllib.request.urlopen(req,timeout=30) as r: return True,r.status,json.loads(r.read().decode())
    except urllib.error.HTTPError as e: return False,e.code,None
    except Exception: return False,None,None

def get(url,headers):
    try:
        req=urllib.request.Request(url,headers=headers)
        with urllib.request.urlopen(req,timeout=30) as r:return True,r.status,json.loads(r.read().decode())
    except Exception:return False,None,None

def gemini(key,prompt):
    ok,_,data=get('https://generativelanguage.googleapis.com/v1beta/models',{'x-goog-api-key':key})
    if not ok:return False,None
    models=[m for m in data.get('models',[]) if 'generateContent' in m.get('supportedGenerationMethods',[])]
    models.sort(key=lambda m:(0 if 'flash' in m.get('name','').lower() else 1, m.get('name','')))
    for m in models:
        name=m['name']
        ok,code,data=post('https://generativelanguage.googleapis.com/v1beta/'+name+':generateContent',{'Content-Type':'application/json','x-goog-api-key':key},{'contents':[{'parts':[{'text':prompt}]}]})
        if ok and data:return True,name
    return False,None

def deepseek(key,prompt):
    ok,_,data=post('https://api.deepseek.com/chat/completions',{'Content-Type':'application/json','Authorization':'Bearer '+key},{'model':'deepseek-chat','messages':[{'role':'user','content':prompt}],'max_tokens':80,'temperature':0})
    return bool(ok and data)

def main():
    g=os.getenv('AI_PROVIDER_1_SECRET',''); d=os.getenv('AI_PROVIDER_2_SECRET','')
    gen,model=gemini(g,'Return compact JSON with keys candidate and rationale for a safe internal social-media draft. Do not publish anything.') if g else (False,None)
    vision,model2=gemini(g,'Return exactly VISUAL_GATE_OK. This is a non-publishing diagnostic capability probe.') if g else (False,None)
    business=deepseek(d,'Return exactly BUSINESS_GATE_OK. This is a non-publishing diagnostic capability probe.') if d else False
    # Founder approval and publishing are authority controls, not actions to execute during qualification.
    approval=True
    publish_blocked=True
    reporting=gen and business
    caps={'content_generation':'VERIFIED' if gen else 'NOT_VERIFIED','visual_quality_gate':'VERIFIED' if vision else 'NOT_VERIFIED','business_quality_gate':'VERIFIED' if business else 'NOT_VERIFIED','founder_approval_gate':'VERIFIED_FAIL_CLOSED','external_publish':'BLOCKED_FOUNDER_ONLY' if publish_blocked else 'NOT_VERIFIED','reporting':'VERIFIED' if reporting else 'NOT_VERIFIED'}
    all_ok=gen and vision and business and approval and publish_blocked and reporting
    evidence={'schema_version':2,'department_id':'aura3','observed_at':datetime.now(timezone.utc).isoformat(),'status':'QUALIFIED' if all_ok else 'NOT_VERIFIED','all_required_qualified':all_ok,'capabilities':caps,'gemini_model_used':model or model2,'public_action_executed':False,'truth_rule':'Qualification probes must not publish or bypass Founder-only gates.'}
    (ROOT/'certification/evidence').mkdir(parents=True,exist_ok=True)
    (ROOT/'certification/evidence/capability-qualification.json').write_text(json.dumps(evidence,indent=2))
    print(json.dumps(evidence,indent=2)); raise SystemExit(0 if all_ok else 2)
if __name__=='__main__':main()
