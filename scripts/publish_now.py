#!/usr/bin/env python3
"""AURA2 — publish ONE approved post to Instagram immediately."""
import json, os, sys, time, urllib.parse, urllib.request, urllib.error
from datetime import datetime, timezone, timedelta

ROOT = os.path.join(os.path.dirname(__file__), "..")
IST = timezone(timedelta(hours=5, minutes=30))
POST_ID = os.environ.get("POST_ID", "").strip()

def jload(p, default):
    try:
        return json.load(open(os.path.join(ROOT, p), encoding="utf-8"))
    except Exception:
        return default

if not POST_ID:
    print("POST_ID missing"); sys.exit(1)

control = jload("data/control.json", {"kill_switch": False})
if control.get("kill_switch"):
    print("KILL SWITCH ON"); sys.exit(0)

approvals = jload("data/approvals.json", {})
cal = jload("content/calendar.json", {"days": []})
post = next((d for d in cal.get("days", []) if d.get("id") == POST_ID), None)
if not post:
    print("unknown post", POST_ID); sys.exit(1)

score = (jload("data/business_report.json", {}) or {}).get(POST_ID, {}).get("score", post.get("score", 0))
if score < 7:
    print("score < 7 — refuse publish"); sys.exit(1)

approvals[POST_ID] = "approved"
json.dump(approvals, open(os.path.join(ROOT, "data/approvals.json"), "w"), indent=2)

published = jload("content/published.json", {})
if published.get(POST_ID, {}).get("instagram"):
    print("already published", POST_ID); sys.exit(0)

IG_ID, IG_TOK = os.environ.get("IG_USER_ID"), os.environ.get("IG_ACCESS_TOKEN")
if not (IG_ID and IG_TOK):
    print("IG secrets missing on AURA2 — marked approved, not posted")
    json.dump(published, open(os.path.join(ROOT, "content/published.json"), "w"), indent=2)
    sys.exit(0)

img = post.get("image")
ig = post.get("ig", {})
caption = f"{ig.get('hook_en','')}\n\n{ig.get('caption_hi','')}\n\n{ig.get('hashtags','')}"

def api(url, data=None):
    body = urllib.parse.urlencode(data).encode() if data else None
    return json.load(urllib.request.urlopen(urllib.request.Request(url), body, timeout=60))

def api_get(url, params):
    q = urllib.parse.urlencode(params)
    return json.load(urllib.request.urlopen(urllib.request.Request(f"{url}?{q}"), timeout=60))

try:
    c = api(f"https://graph.instagram.com/v21.0/{IG_ID}/media",
            {"image_url": img, "caption": caption, "access_token": IG_TOK})
    for _ in range(10):
        st = api_get(f"https://graph.instagram.com/v21.0/{c['id']}",
                     {"fields": "status_code", "access_token": IG_TOK})
        if st.get("status_code") == "FINISHED":
            break
        if st.get("status_code") == "ERROR":
            raise RuntimeError(st)
        time.sleep(5)
    r = api(f"https://graph.instagram.com/v21.0/{IG_ID}/media_publish",
            {"creation_id": c["id"], "access_token": IG_TOK})
    published[POST_ID] = {"instagram": {"id": r.get("id"), "at": datetime.now(IST).isoformat()}}
    print("instagram published", r.get("id"))
except Exception as e:
    print("instagram failed", e)
    sys.exit(1)

json.dump(published, open(os.path.join(ROOT, "content/published.json"), "w"), indent=2, ensure_ascii=False)
