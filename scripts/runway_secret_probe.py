#!/usr/bin/env python3
import json, os, urllib.error, urllib.request

secret = (os.environ.get('RUNWAYML_API_SECRET') or '').strip()
if not secret:
    print(json.dumps({'runway_secret_present': False, 'runway_secret_format': 'NOT_VERIFIED'}))
    raise SystemExit(2)
if not secret.startswith('key_'):
    print(json.dumps({'runway_secret_present': True, 'runway_secret_format': 'FAIL'}))
    raise SystemExit(3)

req = urllib.request.Request(
    'https://api.dev.runwayml.com/v1/tasks/00000000-0000-0000-0000-000000000000',
    headers={
        'Authorization': 'Bearer ' + secret,
        'X-Runway-Version': '2024-11-06',
        'Accept': 'application/json',
        'User-Agent': 'AURA3-Secret-Probe/1.0',
    },
    method='GET',
)
try:
    with urllib.request.urlopen(req, timeout=20) as resp:
        code = int(resp.status)
except urllib.error.HTTPError as exc:
    code = int(exc.code)
except Exception as exc:
    print(json.dumps({'runway_secret_present': True, 'runway_secret_format': 'PASS', 'runway_auth': 'NETWORK_ERROR', 'error_type': type(exc).__name__}))
    raise SystemExit(5)

if code in (401, 403):
    print(json.dumps({'runway_secret_present': True, 'runway_secret_format': 'PASS', 'runway_auth': 'FAIL', 'http_status': code}))
    raise SystemExit(4)
print(json.dumps({'runway_secret_present': True, 'runway_secret_format': 'PASS', 'runway_auth': 'PASS', 'http_status': code, 'zero_credit_probe': True}))
