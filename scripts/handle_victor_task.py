#!/usr/bin/env python3
import json, os
from datetime import datetime, timezone
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]; OUT=ROOT/'integration/results/latest.json'; OUT.parent.mkdir(parents=True,exist_ok=True)
ALLOWED={'STATUS_CHECK','GOVERNANCE_CHECK','CAPABILITY_CATALOG','CERTIFICATION_PROBE'}
def load(p): return json.loads((ROOT/p).read_text(encoding='utf-8'))
def main():
 task_id=os.getenv('VICTOR_TASK_ID','').strip(); task_type=os.getenv('VICTOR_TASK_TYPE','').strip().upper(); raw=os.getenv('VICTOR_TASK_PAYLOAD','{}')
 if not task_id or task_type not in ALLOWED: raise SystemExit('INVALID_OR_UNAUTHORIZED_TASK')
 try: payload=json.loads(raw)
 except Exception: raise SystemExit('INVALID_TASK_PAYLOAD_JSON')
 control=load('state/control.json'); dept=load('state/department_state.json'); contract=load('governance/department_contract.json'); caps=load('governance/capabilities.json'); providers=load('runtime/provider_qualification.json'); cq=load('runtime/capability_qualification.json'); hb=load('runtime/heartbeat_state.json')
 result={'schema_version':2,'message_type':'TASK_RESULT','sender':'aura3','recipient':'victor','task_id':task_id,'task_type':task_type,'observed_at':datetime.now(timezone.utc).isoformat(),'execution_status':'COMPLETED_DIAGNOSTIC','business_execution_performed':False,'public_action_performed':False,'paid_inference_performed':False,'evidence_receipts':[],'validator_verdicts':[],'blockers':[],'next_valid_action':'VICTOR_VERIFY_RESULT'}
 if task_type=='STATUS_CHECK': result['payload']={'department_id':contract.get('department_id'),'department_state':dept.get('department_state'),'kill_switch':control.get('kill_switch'),'business_execution_enabled':control.get('business_execution_enabled'),'heartbeat_runtime_verified':hb.get('runtime_verified'),'providers_all_required_qualified':providers.get('all_required_qualified',False),'capabilities_all_required_qualified':cq.get('all_required_qualified',False)}
 elif task_type=='GOVERNANCE_CHECK': result['payload']={'orchestrator':contract.get('organizational_orchestrator'),'public_publish':load('governance/authority_policy.json').get('rules',{}).get('instagram_publish'),'live_claim_policy':contract.get('live_claim_policy')}
 elif task_type=='CAPABILITY_CATALOG': result['payload']={'capabilities':caps,'runtime_qualification':cq}
 else:
  gates={'constitutional_binding':dept.get('constitutional_binding')=='VERIFIED','heartbeat':hb.get('runtime_verified') is True,'providers':providers.get('all_required_qualified') is True,'capabilities':cq.get('all_required_qualified') is True,'founder_activation':control.get('kill_switch') is False and control.get('business_execution_enabled') is True}
  result['payload']={'gates':gates,'requested_probe':payload}; result['validator_verdicts']=[{'gate':k,'pass':v} for k,v in gates.items()]
  if all(gates.values()): result['execution_status']='CERTIFICATION_READY'; result['next_valid_action']='VICTOR_ACK_ROUND_TRIP'
  else: result['execution_status']='PARTIAL_DIAGNOSTIC'; result['blockers']=[k for k,v in gates.items() if not v]
 OUT.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8'); print(json.dumps(result,indent=2)); print('VICTOR_AURA3_RESULT='+json.dumps(result,separators=(',',':')))
if __name__=='__main__': main()
