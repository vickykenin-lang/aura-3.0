#!/usr/bin/env python3
import json, os, urllib.request, urllib.error
from datetime import datetime, timezone


def post(url, headers, body):
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            data = json.loads(r.read().decode())
            return True, r.status, data
    except urllib.error.HTTPError as e:
        return False, e.code, None
    except Exception:
        return False, None, None


def main():
    g = os.getenv("AI_PROVIDER_1_SECRET", "")
    d = os.getenv("AI_PROVIDER_2_SECRET", "")
    results = {}

    if g:
        ok, code, data = post(
            "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key=" + g,
            {"Content-Type": "application/json"},
            {"contents": [{"parts": [{"text": "Reply exactly: AURA3_PROVIDER_OK"}]}], "generationConfig": {"maxOutputTokens": 20}},
        )
        results["AI_PROVIDER_1"] = {"mapping":"Gemini","credential_present":True,"connectivity":ok,"capability_test":bool(ok and data),"http_status":code,"qualification":"QUALIFIED" if ok and data else "FAILED"}
    else:
        results["AI_PROVIDER_1"] = {"mapping":"Gemini","credential_present":False,"connectivity":False,"capability_test":False,"qualification":"FAILED"}

    if d:
        ok, code, data = post(
            "https://api.deepseek.com/chat/completions",
            {"Content-Type":"application/json","Authorization":"Bearer " + d},
            {"model":"deepseek-chat","messages":[{"role":"user","content":"Reply exactly: AURA3_PROVIDER_OK"}],"max_tokens":20,"temperature":0},
        )
        results["AI_PROVIDER_2"] = {"mapping":"DeepSeek","credential_present":True,"connectivity":ok,"capability_test":bool(ok and data),"http_status":code,"qualification":"QUALIFIED" if ok and data else "FAILED"}
    else:
        results["AI_PROVIDER_2"] = {"mapping":"DeepSeek","credential_present":False,"connectivity":False,"capability_test":False,"qualification":"FAILED"}

    all_ok = all(x["qualification"] == "QUALIFIED" for x in results.values())
    evidence = {"schema_version":2,"department_id":"aura3","observed_at":datetime.now(timezone.utc).isoformat(),"status":"QUALIFIED" if all_ok else "NOT_VERIFIED","all_required_qualified":all_ok,"providers":results,"secret_values_recorded":False}
    os.makedirs("certification/evidence", exist_ok=True)
    with open("certification/evidence/provider-qualification.json","w") as f: json.dump(evidence,f,indent=2)
    print(json.dumps(evidence,indent=2))
    raise SystemExit(0 if all_ok else 2)

if __name__ == "__main__": main()
