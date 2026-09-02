#!/usr/bin/env python3
from __future__ import annotations
import argparse, json
from pathlib import Path

def main() -> int:
    p=argparse.ArgumentParser(); p.add_argument('--input',required=True); a=p.parse_args(); d=json.loads(Path(a.input).read_text(encoding='utf-8'))
    op=d.get('operational_metrics') or {}; bm=d.get('business_metrics') or {}; privacy=d.get('privacy') or {}
    checks={
      'instrumented_not_business_verified':d.get('status')=='INSTRUMENTED_NOT_BUSINESS_VERIFIED' and d.get('business_outcome_verified') is False,
      'shadow_only':d.get('mode')=='SHADOW_ONLY','no_authority':d.get('decision_authority') is False,'production_effect_none':d.get('production_effect')=='NONE','public_action_false':d.get('public_action_performed') is False,
      'warnings_nonnegative':int(op.get('warnings_surfaced',-1))>=0,'no_automatic_blocks':op.get('automatic_content_blocks')==0,'diversity_rate_valid':0<=float(op.get('semantic_diversity_rate',-1))<=1,
      'real_business_metrics_not_fabricated':all(bm.get(k)=='NOT_MEASURED' for k in ['content_rewrites_attributed_to_warning','review_minutes_saved','published_content_diversity_change','engagement_change','enquiries_change','qualified_leads_change','revenue_attributed']),
      'privacy_minimized':privacy.get('raw_text_persisted') is False and privacy.get('embedding_vectors_persisted') is False and privacy.get('lead_or_contact_data_used') is False and privacy.get('confidential_client_data_used') is False
    }
    failures=[k for k,v in checks.items() if not v]; print(json.dumps({'checks':checks,'failures':failures},indent=2)); return 0 if not failures else 1
if __name__=='__main__': raise SystemExit(main())
