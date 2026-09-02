#!/usr/bin/env python3
from __future__ import annotations
import argparse, json
from datetime import datetime, timezone
from pathlib import Path


def main() -> int:
    p=argparse.ArgumentParser(); p.add_argument('--input',required=True); p.add_argument('--output',required=True); p.add_argument('--source-sha',required=True); p.add_argument('--run-id',required=True); a=p.parse_args()
    src=json.loads(Path(a.input).read_text(encoding='utf-8'))
    scan=src['aura3_corpus_scan']; pairs=max(int(scan['pairwise_comparisons']),1)
    flagged=int(scan['duplicates'])+int(scan['repetitive_themes']); distinct=int(scan['distinct_pairs'])
    out={
      'schema_version':1,'department_id':'aura3','phase':'HF_PHASE9_BUSINESS_OUTCOME_INSTRUMENTATION','status':'INSTRUMENTED_NOT_BUSINESS_VERIFIED','observed_at':datetime.now(timezone.utc).isoformat(),'source_sha':a.source_sha,'workflow_run_id':a.run_id,
      'mode':'SHADOW_ONLY','decision_authority':False,'production_effect':'NONE','public_action_performed':False,'business_outcome_verified':False,
      'operational_metrics':{'corpus_items':scan['items'],'pairwise_comparisons':scan['pairwise_comparisons'],'duplicate_warnings':scan['duplicates'],'repetitive_theme_warnings':scan['repetitive_themes'],'warnings_surfaced':flagged,'distinct_pairs':distinct,'flagged_pair_rate':round(flagged/pairs,6),'semantic_diversity_rate':round(distinct/pairs,6),'automatic_content_blocks':0},
      'business_metrics':{'content_rewrites_attributed_to_warning':'NOT_MEASURED','review_minutes_saved':'NOT_MEASURED','published_content_diversity_change':'NOT_MEASURED','engagement_change':'NOT_MEASURED','enquiries_change':'NOT_MEASURED','qualified_leads_change':'NOT_MEASURED','revenue_attributed':'NOT_MEASURED'},
      'privacy':src['privacy'],'cost':src['cost'],
      'truth_note':'Instrumentation records observable semantic-warning and diversity signals only. Business outcome remains unverified until longitudinal real-world evidence exists.'}
    Path(a.output).parent.mkdir(parents=True,exist_ok=True); Path(a.output).write_text(json.dumps(out,indent=2),encoding='utf-8'); print(json.dumps(out,indent=2)); return 0
if __name__=='__main__': raise SystemExit(main())
