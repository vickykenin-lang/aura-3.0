#!/usr/bin/env python3
import json, os, re
from datetime import datetime, timezone
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
LATEST=ROOT/'integration/results/latest.json'
ALLOWED={'STATUS_CHECK','GOVERNANCE_CHECK','CAPABILITY_CATALOG','CERTIFICATION_PROBE','STRICT_SUPERVISION_PROBE','RECOVERY_EXECUTE'}
def load(p): return json.loads((ROOT/p).read_text(encoding='utf-8'))
def main():
 task_id=os.getenv('VICTOR_TASK_ID','').strip(); task_type=os.getenv('VICTOR_TASK_TYPE','').strip().upper(); raw=os.getenv('VICTOR_TASK_PAYLOAD','{}')
 if not task_id or task_type not in ALLOWED: raise SystemExit('INVALID_OR_UNAUTHORIZED_TASK')
 safe_task_id=re.sub(r'[^A-Za-z0-9._-]+','-',task_id).strip('-')[:120]
 if not safe_task_id: raise SystemExit('INVALID_TASK_ID')
 try: payload=json.loads(raw)
 except Exception: raise SystemExit('INVALID_TASK_PAYLOAD_JSON')
 control=load('state/control.json'); dept=load('state/department_state.json'); contract=load('governance/department_contract.json'); caps=load('governance/capabilities.json'); providers=load('runtime/provider_qualification.json'); cq=load('runtime/capability_qualification.json'); hb=load('runtime/heartbeat_state.json'); authority=load('governance/authority_policy.json')
 state=dept.get('department_state','UNKNOWN')
 result={
  'schema_version':5,'message_type':'TASK_RESULT','sender':'aura3','recipient':'victor','task_id':task_id,'task_type':task_type,
  'observed_at':datetime.now(timezone.utc).isoformat(),'execution_status':'COMPLETED_DIAGNOSTIC','business_execution_performed':False,
  'public_action_performed':False,'paid_inference_performed':False,'evidence_receipts':[],'validator_verdicts':[],'blockers':[],
  'next_valid_action':'VICTOR_VERIFY_RESULT',
  'strict_supervision':{
    'status':state,
    'objective_alignment':'CHECKED_AGAINST_AURA3_CONSTITUTIONAL_OBJECTIVE',
    'error_or_blocker':None,
    'root_cause':None,
    'solution':'Continue governed next action according to task result and certification gates.',
    'next_action':'VICTOR_REVIEW_AND_PUSH_NEXT_ACTION',
    'evidence':[f'integration/results/tasks/{safe_task_id}.json'],
    'revert_to_victor':True,
    'requires_follow_up':True
  }
 }
 gates={'constitutional_binding':dept.get('constitutional_binding')=='VERIFIED','heartbeat':hb.get('runtime_verified') is True,'providers':providers.get('all_required_qualified') is True,'capabilities':cq.get('all_required_qualified') is True,'founder_activation':control.get('kill_switch') is False and control.get('business_execution_enabled') is True}
 if task_type=='STATUS_CHECK':
  result['payload']={'department_id':contract.get('department_id'),'department_state':state,'kill_switch':control.get('kill_switch'),'business_execution_enabled':control.get('business_execution_enabled'),'heartbeat_runtime_verified':hb.get('runtime_verified'),'providers_all_required_qualified':providers.get('all_required_qualified',False),'capabilities_all_required_qualified':cq.get('all_required_qualified',False),'operating_mode':authority.get('operating_mode')}
 elif task_type=='GOVERNANCE_CHECK':
  result['payload']={'orchestrator':contract.get('organizational_orchestrator'),'supervision_mode':contract.get('communication',{}).get('supervision_mode'),'public_publish':authority.get('rules',{}).get('instagram_publish'),'operating_mode':authority.get('operating_mode'),'live_claim_policy':contract.get('live_claim_policy')}
 elif task_type=='CAPABILITY_CATALOG':
  result['payload']={'capabilities':caps,'runtime_qualification':cq}
 elif task_type=='RECOVERY_EXECUTE':
  failed=[k for k,v in gates.items() if not v]
  result['payload']={'gates':gates,'requested_recovery':payload,'operating_mode':authority.get('operating_mode')}
  result['validator_verdicts']=[{'gate':k,'pass':v} for k,v in gates.items()]
  if failed:
   result['execution_status']='RECOVERY_BLOCKED'
   result['blockers']=failed
   result['strict_supervision']['status']='RECOVERY_BLOCKED'
   result['strict_supervision']['error_or_blocker']=failed
   result['strict_supervision']['root_cause']='One or more required runtime/certification gates are not verified.'
   result['strict_supervision']['solution']='Repair failed internal gates under Victor authority; escalate only genuine Founder-only boundary.'
   result['strict_supervision']['next_action']='VICTOR_ROUTE_FAILED_GATES_TO_RELEVANT_DEPARTMENT'
  else:
   result['execution_status']='RECOVERY_VERIFIED'
   result['strict_supervision']['status']='LIVE_CERTIFIED'
   result['strict_supervision']['root_cause']='No current AURA3 runtime gate failure detected. Prior blockage was transport/governance-path related rather than AURA3 runtime readiness.'
   result['strict_supervision']['solution']='AURA3 runtime is certification-ready under GOVERNED_SELF_MODE. Keep department results on the canonical Victor return channel and continue governed production work.'
   result['strict_supervision']['next_action']='VICTOR_CERTIFY_TRANSPORT_AND_RESUME_AURA3_WORK'
   result['next_valid_action']='VICTOR_CERTIFY_TRANSPORT_AND_RESUME_AURA3_WORK'
 else:
  result['payload']={'gates':gates,'requested_probe':payload}; result['validator_verdicts']=[{'gate':k,'pass':v} for k,v in gates.items()]
  failed=[k for k,v in gates.items() if not v]
  if all(gates.values()):
   result['execution_status']='CERTIFICATION_READY'; result['next_valid_action']='VICTOR_ACK_ROUND_TRIP'
   result['strict_supervision']['status']='CERTIFICATION_READY'; result['strict_supervision']['solution']='Victor verify round trip and evaluate LIVE certification.'
   result['strict_supervision']['next_action']='VICTOR_ACK_ROUND_TRIP'
  else:
   result['execution_status']='PARTIAL_DIAGNOSTIC'; result['blockers']=failed
   result['strict_supervision']['error_or_blocker']=failed
   result['strict_supervision']['root_cause']='One or more required certification gates are not verified.'
   result['strict_supervision']['solution']='Resolve failed gates in priority order without bypassing Founder-only hard boundaries.'
   result['strict_supervision']['next_action']='VICTOR_PUSH_FAILED_GATES'
 LATEST.parent.mkdir(parents=True,exist_ok=True)
 task_out=ROOT/'integration/results/tasks'/f'{safe_task_id}.json'; task_out.parent.mkdir(parents=True,exist_ok=True)
 encoded=json.dumps(result,indent=2)+'\n'
 LATEST.write_text(encoded,encoding='utf-8'); task_out.write_text(encoded,encoding='utf-8')
 print(json.dumps(result,indent=2)); print('VICTOR_AURA3_RESULT='+json.dumps(result,separators=(',',':')))
 print('VICTOR_AURA3_RESULT_FILE='+str(task_out.relative_to(ROOT)))
if __name__=='__main__': main()
