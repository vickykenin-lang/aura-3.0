#!/usr/bin/env python3
import json, os, urllib.request, urllib.error
from datetime import datetime, timezone


def request_json(url, headers=None, body=None, method=None):
    headers = headers or {}
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, headers=headers, method=method or ("POST" if data else "GET"))
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return True, r.status, json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        return False, e.code, None
    except Exception:
        return False, None, None


def qualify_gemini(key):
    base = "https://generativelanguage.googleapis.com/v1beta"
    headers = {"x-goog-api-key": key}
    ok, list_code, data = request_json(base + "/models?pageSize=1000", headers=headers)
    if not ok or not data:
        return {"mapping":"Gemini","credential_present":True,"discovery":False,"connectivity":False,"capability_test":False,"http_status":list_code,"qualification":"FAILED"}

    candidates = []
    for m in data.get("models", []):
        methods = m.get("supportedGenerationMethods", [])
        name = m.get("name", "")
        if "generateContent" in methods and name.startswith("models/gemini-"):
            candidates.append(name)

    # Prefer stable Flash-class text models, but only among models actually
    # advertised to this API key/project. Fall back to any Gemini model that
    # explicitly supports generateContent.
    def rank(name):
        n = name.lower()
        preview_penalty = 1 if ("preview" in n or "exp" in n) else 0
        flash_penalty = 0 if "flash" in n else 1
        image_penalty = 1 if ("image" in n or "tts" in n or "live" in n) else 0
        return (image_penalty, flash_penalty, preview_penalty, n)

    candidates.sort(key=rank)
    attempts = []
    for resource_name in candidates:
        url = base + "/" + resource_name + ":generateContent"
        ok, code, response = request_json(
            url,
            headers={"Content-Type":"application/json", "x-goog-api-key":key},
            body={"contents":[{"parts":[{"text":"Reply exactly: AURA3_PROVIDER_OK"}]}]},
        )
        attempts.append({"model":resource_name.removeprefix("models/"),"http_status":code})
        if ok and response and response.get("candidates"):
            return {"mapping":"Gemini","model":resource_name.removeprefix("models/"),"credential_present":True,"discovery":True,"available_generate_content_models":len(candidates),"connectivity":True,"capability_test":True,"http_status":code,"qualification":"QUALIFIED"}

    return {"mapping":"Gemini","credential_present":True,"discovery":True,"available_generate_content_models":len(candidates),"connectivity":False,"capability_test":False,"attempts":attempts[:10],"qualification":"FAILED"}


def main():
    g = os.getenv("AI_PROVIDER_1_SECRET", "")
    d = os.getenv("AI_PROVIDER_2_SECRET", "")
    results = {}

    results["AI_PROVIDER_1"] = qualify_gemini(g) if g else {"mapping":"Gemini","credential_present":False,"connectivity":False,"capability_test":False,"qualification":"FAILED"}

    if d:
        ok, code, data = request_json(
            "https://api.deepseek.com/chat/completions",
            headers={"Content-Type":"application/json","Authorization":"Bearer " + d},
            body={"model":"deepseek-chat","messages":[{"role":"user","content":"Reply exactly: AURA3_PROVIDER_OK"}],"max_tokens":20,"temperature":0},
        )
        results["AI_PROVIDER_2"] = {"mapping":"DeepSeek","model":"deepseek-chat","credential_present":True,"connectivity":ok,"capability_test":bool(ok and data),"http_status":code,"qualification":"QUALIFIED" if ok and data else "FAILED"}
    else:
        results["AI_PROVIDER_2"] = {"mapping":"DeepSeek","model":"deepseek-chat","credential_present":False,"connectivity":False,"capability_test":False,"qualification":"FAILED"}

    all_ok = all(x["qualification"] == "QUALIFIED" for x in results.values())
    evidence = {"schema_version":3,"department_id":"aura3","observed_at":datetime.now(timezone.utc).isoformat(),"status":"QUALIFIED" if all_ok else "NOT_VERIFIED","all_required_qualified":all_ok,"providers":results,"secret_values_recorded":False}
    os.makedirs("certification/evidence", exist_ok=True)
    with open("certification/evidence/provider-qualification.json","w") as f: json.dump(evidence,f,indent=2)
    print(json.dumps(evidence,indent=2))
    raise SystemExit(0 if all_ok else 2)

if __name__ == "__main__": main()
