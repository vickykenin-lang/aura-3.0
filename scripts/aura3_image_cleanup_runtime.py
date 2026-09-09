#!/usr/bin/env python3
from __future__ import annotations
import hashlib, json, os, time, urllib.error, urllib.request
from pathlib import Path

RUNWAY_API = "https://api.dev.runwayml.com/v1"
RUNWAY_VERSION = "2024-11-06"
RUNWAY_MODEL = os.environ.get("AURA3_IMAGE_CLEANUP_MODEL", "seedream5_pro")
RUNWAY_RATIO = os.environ.get("AURA3_IMAGE_CLEANUP_RATIO", "auto_1k")
POLL_DELAYS = (5,5,7,7,10,10,15,15,20,20)
_CLEANED_URLS: dict[str,str] = {}
_INSTALLED = False

def _json_request(url, method="GET", payload=None, timeout=60):
    secret=(os.environ.get("RUNWAYML_API_SECRET") or "").strip()
    if not secret: raise RuntimeError("RUNWAYML_API_SECRET is required for image cleanup")
    req=urllib.request.Request(url,data=json.dumps(payload).encode() if payload is not None else None,headers={"Authorization":f"Bearer {secret}","Content-Type":"application/json","X-Runway-Version":RUNWAY_VERSION},method=method)
    with urllib.request.urlopen(req,timeout=timeout) as r: out=json.loads(r.read().decode())
    if not isinstance(out,dict): raise RuntimeError("cleanup provider returned non-object JSON")
    return out

def _cleanup_candidate(v):
    if v.get("visual_ok"): return False
    try: q=int(v.get("quality",0) or 0)
    except: q=0
    return q>=7 and str(v.get("design_freshness","")).lower()=="current" and str(v.get("copyright_status","")).lower()!="flagged" and (str(v.get("watermarks","")).lower()=="present" or str(v.get("brand_logo_risk","")).lower()=="present")

def _create_task(source_url):
    data=_json_request(f"{RUNWAY_API}/text_to_image",method="POST",timeout=90,payload={"model":RUNWAY_MODEL,"ratio":RUNWAY_RATIO,"promptText":"Edit @source only. Remove the visible watermark, small logo and unwanted text overlay. Preserve the exact interior scene, crop, camera angle, geometry, furniture, materials, lighting and colors. Do not add objects, text, logos, people or new styling.","referenceImages":[{"uri":source_url,"tag":"source"}]})
    tid=str(data.get("id") or "").strip()
    if not tid: raise RuntimeError("cleanup provider did not return task id")
    return tid

def _wait(task_id):
    for delay in POLL_DELAYS:
        t=_json_request(f"{RUNWAY_API}/tasks/{task_id}",timeout=45); s=str(t.get("status") or "").upper()
        if s=="SUCCEEDED":
            o=t.get("output") or []
            if isinstance(o,list) and o and str(o[0]).startswith("https://"): return str(o[0])
            raise RuntimeError("cleanup task succeeded without image output")
        if s in {"FAILED","CANCELED","CANCELLED"}: raise RuntimeError(f"cleanup task ended with {s}")
        time.sleep(delay)
    raise TimeoutError("cleanup task timeout")

def _download(url):
    req=urllib.request.Request(url,headers={"User-Agent":"AURA3-Image-Cleanup/1.0"})
    with urllib.request.urlopen(req,timeout=90) as r:
        ct=str(r.headers.get("Content-Type") or "").split(";",1)[0].lower(); b=r.read()
    if not ct.startswith("image/") or not b: raise ValueError("invalid cleanup image bytes")
    return ct,b

def _persist(source_url, output_url):
    ct,b=_download(output_url); ext=".png" if ct=="image/png" else ".webp" if ct=="image/webp" else ".jpg"
    d=hashlib.sha256(source_url.encode()+b).hexdigest()[:20]
    root=Path(__file__).resolve().parents[1]; rel=Path("assets")/"cleaned"/f"aura3-clean-{d}{ext}"; p=root/rel; p.parent.mkdir(parents=True,exist_ok=True); p.write_bytes(b)
    owner,repo=(os.environ.get("GITHUB_REPOSITORY") or "vickykenin-lang/aura-3.0").split("/",1)
    return f"https://{owner}.github.io/{repo}/{rel.as_posix()}"

def cleanup_image(source_url):
    if not str(source_url).startswith("https://"): raise ValueError("cleanup source must use HTTPS")
    output=_wait(_create_task(source_url)); return output,_persist(source_url,output)

def install_into_resilient_runtime(resilient):
    global _INSTALLED
    if _INSTALLED: return
    original_strict=resilient.strict_vision; original_generate=resilient.image_grounded_generate
    def strict(api_key,image_url):
        v=original_strict(api_key,image_url)
        if not _cleanup_candidate(v): return v
        if not (os.environ.get("RUNWAYML_API_SECRET") or "").strip():
            resilient._record_incident("IMG_CLEANUP_CREDENTIALS_UNAVAILABLE","image_cleanup","cleanup candidate retained as visual reject",image_url); return v
        try:
            provider_url,stable_url=cleanup_image(image_url); cleaned=original_strict(api_key,provider_url)
        except (urllib.error.HTTPError,urllib.error.URLError,TimeoutError,ValueError,RuntimeError) as exc:
            resilient._record_incident("IMG_CLEANUP_FAILED","image_cleanup",type(exc).__name__,image_url); return v
        if not cleaned.get("visual_ok"):
            resilient._record_incident("IMG_CLEANUP_REVALIDATION_REJECT","image_cleanup","strict gate rejected cleaned output",image_url); return v
        cleaned=dict(cleaned); cleaned.update({"cleanup_applied":True,"cleanup_provider":"runway","cleanup_original_image":image_url,"cleanup_stable_image":stable_url})
        _CLEANED_URLS[image_url]=stable_url; resilient._VISUAL_CACHE[stable_url]=dict(cleaned)
        resilient._record_incident("IMG_CLEANUP_REVALIDATED_PASS","image_cleanup","cleaned output passed strict visual gate",image_url)
        return cleaned
    def generate(key,selected):
        result=original_generate(key,selected)
        for item in selected:
            src=str(item.get("image") or ""); stable=_CLEANED_URLS.get(src)
            if stable:
                item["original_image"]=src; item["image"]=stable; item["image_cleanup"]={"applied":True,"provider":"runway","revalidated":True}
        return result
    resilient.strict_vision=strict; resilient.image_grounded_generate=generate; _INSTALLED=True
