#!/usr/bin/env python3
import json, os, urllib.request, urllib.parse
from datetime import datetime, timezone
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'certification/evidence/part10-preflight.json'
OUT.parent.mkdir(parents=True, exist_ok=True)

def http_json(req, timeout=45):
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)

def result(name, ok, detail):
    return {'check':name,'pass':bool(ok),'detail':detail}

checks=[]
# Canonical governance
contract=json.load(open(ROOT/'governance/department_contract.json'))
auth=json.load(open(ROOT/'governance/authority_policy.json'))
control=json.load(open(ROOT/'state/control.json'))
hb=json.load(open(ROOT/'runtime/heartbeat_state.json'))
checks.append(result('constitutional_contract',contract.get('department_id')=='aura3' and contract.get('organizational_orchestrator')=='victor','Founder→Victor→AURA3'))
checks.append(result('founder_public_gate',auth.get('rules',{}).get('instagram_publish')=='FOUNDER_ONLY','Instagram publish Founder-only'))
checks.append(result('kill_switch_fail_closed',control.get('kill_switch') is True and control.get('external_execution_enabled') is False,'external execution remains blocked'))
checks.append(result('heartbeat_evidence',hb.get('runtime_verified') is True and hb.get('evidence_source',{}).get('conclusion')=='success','fresh persisted E2 heartbeat evidence present'))

# Credential presence + non-inference connectivity only. No paid generation is invoked here.
gem=os.getenv('AI_PROVIDER_1_SECRET','').strip()
dsp=os.getenv('AI_PROVIDER_2_SECRET','').strip()
checks.append(result('provider1_credential_present',bool(gem),'AI_PROVIDER_1_SECRET present' if gem else 'missing'))
checks.append(result('provider2_credential_present',bool(dsp),'AI_PROVIDER_2_SECRET present' if dsp else 'missing'))

if gem:
    try:
        url='https://generativelanguage.googleapis.com/v1beta/models?key='+urllib.parse.quote(gem,safe='')
        data=http_json(urllib.request.Request(url,method='GET'))
        mids=[m.get('name','') for m in data.get('models',[]) if isinstance(m,dict)]
        ok=any('gemini' in m.lower() for m in mids)
        checks.append(result('provider1_connectivity',ok,f'model_count={len(mids)}'))
    except Exception as e:
        checks.append(result('provider1_connectivity',False,type(e).__name__))
else:
    checks.append(result('provider1_connectivity',False,'credential missing'))

if dsp:
    try:
        req=urllib.request.Request('https://api.deepseek.com/models',headers={'Authorization':'Bearer '+dsp},method='GET')
        data=http_json(req)
        mids=[m.get('id','') for m in data.get('data',[]) if isinstance(m,dict)]
        checks.append(result('provider2_connectivity',bool(mids),f'model_count={len(mids)}'))
    except Exception as e:
        checks.append(result('provider2_connectivity',False,type(e).__name__))
else:
    checks.append(result('provider2_connectivity',False,'credential missing'))

# Contract-level guarded execution / memory / recovery / Victor handover readiness
for path,name in [
 ('runtime/guarded_execution.py','guarded_execution_present'),
 ('memory/MEMORY_POLICY.json','memory_policy_present'),
 ('recovery/RECOVERY_POLICY.json','recovery_policy_present'),
 ('integration/victor_contract.json','victor_contract_present'),
 ('runtime/victor_connection.json','victor_handover_state_present')]:
    checks.append(result(name,(ROOT/path).exists(),path))

victor=json.load(open(ROOT/'runtime/victor_connection.json'))
checks.append(result('victor_not_falsely_live',victor.get('e2e_verified') is not True,'E2E remains unverified until real Victor transport test'))

all_preflight=all(c['pass'] for c in checks)
payload={
 'department_id':'aura3',
 'phase':'PART_10_PREFLIGHT',
 'observed_at':datetime.now(timezone.utc).isoformat(),
 'preflight_pass':all_preflight,
 'production_live':False,
 'paid_inference_invoked':False,
 'public_action_invoked':False,
 'truth_note':'Preflight does not certify provider capability inference, Victor E2E transport, or production LIVE.',
 'checks':checks
}
OUT.write_text(json.dumps(payload,indent=2)+'\n',encoding='utf-8')
print(json.dumps(payload,indent=2))
raise SystemExit(0 if all_preflight else 2)
