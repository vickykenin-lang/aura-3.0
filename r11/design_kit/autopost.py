#!/usr/bin/env python3
"""R11 autopost (agent A6): turns the schedule into live Instagram posts, unattended.

  prepare  Build + review every kit named in schedule.json into campaigns/r11/kits/<kit>/.
           A kit that already matches its spec and source image is left untouched.
  publish  Post at most ONE due item per run (carousel or reel) and record it in
           published.json. Guards before any write call to Instagram:
             - kit review verdict is READY_*, every file matches its sha256
             - each public image URL serves exactly those bytes
             - the token's account is the confirmed @username and account id
             - the 24 h publishing quota is not used up
             - no recent post already carries the same caption (no double posts)
             - at least MIN_GAP since the previous R11 post
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import build_kit  # noqa: E402
import review_kit  # noqa: E402

SCHEDULE = "r11/design_kit/schedule.json"
STATE = "r11/design_kit/published.json"
SPECS = "r11/design_kit/kits"
KITS = "campaigns/r11/kits"
TARGET = "governance/publishing_target.json"
API = "https://graph.instagram.com"
VERSION = (os.environ.get("IG_GRAPH_API_VERSION") or "v25.0").strip()
MAX_ATTEMPTS = 3
RETRY_GAP = timedelta(minutes=50)
MIN_GAP = timedelta(hours=12)
TIMEOUT = 60


class Refused(Exception):
    pass


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def load(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def save(path: Path, data) -> None:
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def when(value: str) -> datetime:
    t = datetime.fromisoformat(value)
    if t.tzinfo is None:
        raise Refused(f"TIME_WITHOUT_ZONE:{value}")
    return t


def iso(t: datetime) -> str:
    return t.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------- prepare ----------------
def files_are_current(spec_path: Path, out: Path) -> bool:
    m = load(out / "kit.json", None)
    if not m or m.get("spec_sha256") != sha(spec_path.read_bytes()):
        return False
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    if m["source"]["sha256"] != spec["source"]["sha256"]:
        return False
    for o in m["outputs"]:
        p = out / o["file"]
        if not p.exists() or sha(p.read_bytes()) != o["sha256"]:
            return False
    return True


def review_is_current(out: Path) -> bool:
    return load(out / "review.json", {}).get("reviewer_version") == review_kit.REVIEWER_VERSION


def prepare(root: Path, use_nova=False, converse=None) -> list[dict]:
    sched = load(root / SCHEDULE, {"items": []})
    report = []
    for kit in sorted({i["kit"] for i in sched["items"]}):
        spec_path, out = root / SPECS / f"{kit}.json", root / KITS / kit
        if files_are_current(spec_path, out):
            if review_is_current(out):
                report.append({"kit": kit, "action": "current",
                               "verdict": load(out / "review.json", {}).get("verdict")})
            else:   # reviewer got new checks: re-review the same files, no rebuild
                r = review_kit.review(out, spec_path, use_nova, converse)
                report.append({"kit": kit, "action": "re-reviewed", "verdict": r["verdict"]})
            continue
        if out.exists():
            shutil.rmtree(out)
        build_kit.build(root, spec_path, out, with_reel=True)
        r = review_kit.review(out, spec_path, use_nova, converse)
        report.append({"kit": kit, "action": "built", "verdict": r["verdict"]})
    return report


# ---------------- Instagram ----------------
class Graph:
    def __init__(self, token: str, sleep=time.sleep):
        self.token, self.sleep = token, sleep

    def _clean(self, text: str) -> str:
        return str(text).replace(self.token, "[REDACTED]")[:300] if self.token else str(text)[:300]

    def call(self, method: str, path: str, params: dict | None = None) -> dict:
        values = {**(params or {}), "access_token": self.token}
        url = f"{API}/{VERSION}/{path.strip('/')}"
        data = None
        if method == "GET":
            url += "?" + urllib.parse.urlencode(values)
        else:
            data = urllib.parse.urlencode(values).encode()
        req = urllib.request.Request(url, data=data, method=method)
        return self._send(req)

    def upload(self, uri: str, blob: bytes) -> dict:
        req = urllib.request.Request(uri, data=blob, method="POST", headers={
            "Authorization": f"OAuth {self.token}", "offset": "0", "file_size": str(len(blob))})
        return self._send(req)

    def _send(self, req) -> dict:
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
                payload = json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            try:
                payload = json.loads(e.read().decode())
            except (ValueError, UnicodeDecodeError):
                raise Refused(f"IG_HTTP_{e.code}") from None
        except urllib.error.URLError:
            raise Refused("IG_NETWORK") from None
        if isinstance(payload, dict) and payload.get("error"):
            err = payload["error"]
            raise Refused(f"IG_ERROR_{err.get('code')}/{err.get('error_subcode', '')}: "
                          + self._clean(err.get("message", "")))
        return payload


def fetch_url(url: str) -> bytes:
    try:
        with urllib.request.urlopen(url, timeout=TIMEOUT) as r:
            return r.read()
    except (urllib.error.URLError, OSError):
        raise Refused("PUBLIC_URL_UNREACHABLE:" + url.rsplit("/", 1)[1]) from None


def wait_ready(g: Graph, cid: str, polls: int, gap: int):
    for i in range(polls):
        st = str(g.call("GET", cid, {"fields": "status_code"}).get("status_code", "")).upper()
        if st in ("FINISHED", "PUBLISHED"):
            return
        if st in ("ERROR", "EXPIRED"):
            raise Refused(f"CONTAINER_{st}")
        g.sleep(gap)
    raise Refused("CONTAINER_NOT_READY")


# ---------------- publish ----------------
def due_item(sched: dict, state: dict, now: datetime):
    item = _first_due(sched, state, now)
    if item is None:
        return None, "NOTHING_DUE"
    done = [when(s["published_at"]) for s in state["items"].values() if s["status"] in ("PUBLISHED", "RECOVERED")]
    if done and now - max(done) < MIN_GAP:
        return None, "MIN_GAP_SINCE_LAST_POST"
    return item, None


def _first_due(sched: dict, state: dict, now: datetime):
    for it in sorted(sched["items"], key=lambda i: when(i["at"])):
        if when(it["at"]) > now:
            continue
        st = state["items"].get(it["id"])
        if st and st["status"] in ("PUBLISHED", "RECOVERED"):
            continue
        if st and st["status"] == "FAILED":
            if st["attempts"] >= MAX_ATTEMPTS or now - when(st["last_attempt"]) < RETRY_GAP:
                continue
        return it
    return None


def kit_payload(root: Path, item: dict, repo: str, commit: str, fetch) -> dict:
    out = root / KITS / item["kit"]
    review = load(out / "review.json", {})
    if not str(review.get("verdict", "")).startswith("READY"):
        raise Refused(f"KIT_NOT_READY:{review.get('verdict')}")
    m = load(out / "kit.json", None)
    if not m:
        raise Refused("KIT_MISSING")
    by_name = {o["file"]: o for o in m["outputs"]}
    if item["format"] == "carousel":
        names, cap_name = [f"slide{i}.jpg" for i in range(1, 6)], "caption.txt"
    elif item["format"] == "reel":
        names, cap_name = ["reel.mp4"], "reel_caption.txt"
    else:
        raise Refused(f"UNKNOWN_FORMAT:{item['format']}")
    for n in names + [cap_name]:
        if n not in by_name or sha((out / n).read_bytes()) != by_name[n]["sha256"]:
            raise Refused(f"FILE_CHANGED:{n}")
    caption = (out / cap_name).read_text(encoding="utf-8").strip()
    urls = []
    if item["format"] == "carousel":
        for n in names:
            url = f"https://raw.githubusercontent.com/{repo}/{commit}/{KITS}/{item['kit']}/{n}"
            if sha(fetch(url)) != by_name[n]["sha256"]:
                raise Refused(f"PUBLIC_URL_BYTES_DIFFER:{n}")
            urls.append(url)
    return {"caption": caption, "urls": urls,
            "video": (out / "reel.mp4").read_bytes() if item["format"] == "reel" else None}


def same_kind(media: dict, fmt: str) -> bool:
    if fmt == "carousel":
        return media.get("media_type") == "CAROUSEL_ALBUM"
    return media.get("media_product_type") == "REELS" or media.get("media_type") == "VIDEO"


def preflight(g: Graph, ig_id: str, username: str, caption: str, fmt: str, info: dict | None = None):
    me = g.call("GET", "me", {"fields": "user_id,username"})
    uid = str(me.get("user_id") or me.get("id") or "")
    if uid != ig_id:
        raise Refused("ACCOUNT_ID_MISMATCH")
    if str(me.get("username", "")).lower() != username:
        raise Refused("USERNAME_MISMATCH")
    limit = (g.call("GET", f"{uid}/content_publishing_limit",
                    {"fields": "quota_usage,config"}).get("data") or [{}])[0]
    total = (limit.get("config") or {}).get("quota_total")
    if total is not None and limit.get("quota_usage", 0) >= total:
        raise Refused("PUBLISHING_QUOTA_USED_UP")
    recent = g.call("GET", f"{uid}/media", {
        "fields": "id,caption,media_type,media_product_type,permalink,timestamp", "limit": "15"})
    if info is not None:   # shown in dry runs: proof the connection works end to end
        posts = recent.get("data", [])
        info.update(account="@" + username, account_id_matches=True, publish_quota_24h=
                    f"{limit.get('quota_usage', 0)}/{total}", recent_posts_read=len(posts),
                    latest_post_at=posts[0].get("timestamp") if posts else None)
    want = sha(caption.encode())
    for media in recent.get("data", []):
        if sha(str(media.get("caption", "")).strip().encode()) == want and same_kind(media, fmt):
            return uid, media
    return uid, None


def post(g: Graph, uid: str, item: dict, pay: dict) -> str:
    if item["format"] == "carousel":
        kids = [g.call("POST", f"{uid}/media", {"image_url": u, "is_carousel_item": "true"})["id"]
                for u in pay["urls"]]
        for k in kids:
            wait_ready(g, k, 10, 6)
        cid = g.call("POST", f"{uid}/media", {"media_type": "CAROUSEL", "children": ",".join(kids),
                                               "caption": pay["caption"]})["id"]
        wait_ready(g, cid, 20, 6)
    else:
        c = g.call("POST", f"{uid}/media", {"media_type": "REELS", "upload_type": "resumable",
                                             "caption": pay["caption"], "share_to_feed": "true"})
        cid = c["id"]
        uri = c.get("uri") or f"https://rupload.facebook.com/ig-api-upload/{VERSION}/{cid}"
        up = g.upload(uri, pay["video"])
        if up.get("success") is False:
            raise Refused("REEL_UPLOAD_FAILED")
        wait_ready(g, cid, 60, 15)
    return str(g.call("POST", f"{uid}/media_publish", {"creation_id": cid})["id"])


def publish(root: Path, now: datetime, g: Graph | None, ig_id: str, repo: str, commit: str,
            dry_run=True, fetch=fetch_url, preview_next=False) -> dict:
    sched = load(root / SCHEDULE, {"items": []})
    state = load(root / STATE, {"items": {}})
    if preview_next and not dry_run:
        raise Refused("PREVIEW_NEXT_NEEDS_DRY_RUN")
    if preview_next:   # read-only rehearsal of the next unpublished item, whatever its time
        pending = [i for i in sorted(sched["items"], key=lambda i: when(i["at"]))
                   if state["items"].get(i["id"], {}).get("status") not in ("PUBLISHED", "RECOVERED")]
        item, why = (pending[0], None) if pending else (None, "NOTHING_PENDING")
    else:
        item, why = due_item(sched, state, now)
    if not item:
        return {"result": why}
    username = load(root / TARGET, {}).get("instagram_username", "")
    if not username:
        raise Refused("TARGET_USERNAME_MISSING")
    pay = kit_payload(root, item, repo, commit, fetch)
    if g is None:
        raise Refused("IG_TOKEN_MISSING")
    info: dict = {}
    uid, existing = preflight(g, ig_id, username, pay["caption"], item["format"], info)
    if existing:
        if not dry_run:
            try:
                at = iso(datetime.strptime(existing["timestamp"], "%Y-%m-%dT%H:%M:%S%z"))
            except (KeyError, ValueError):
                at = iso(now)
            state["items"][item["id"]] = {"status": "RECOVERED", "kit": item["kit"], "format": item["format"],
                                          "media_id": existing.get("id"), "permalink": existing.get("permalink"),
                                          "published_at": at}
            save(root / STATE, state)
        return {"result": "ALREADY_ON_INSTAGRAM", "item": item["id"]}
    if dry_run:
        return {"result": "DRY_RUN_OK", "item": item["id"], "format": item["format"], "instagram": info,
                "would_post": pay["urls"] or ["reel.mp4"], "caption_chars": len(pay["caption"])}
    prev = state["items"].get(item["id"], {})
    try:
        media_id = post(g, uid, item, pay)
    except Refused as e:
        state["items"][item["id"]] = {"status": "FAILED", "kit": item["kit"], "format": item["format"],
                                      "attempts": prev.get("attempts", 0) + 1, "last_attempt": iso(now),
                                      "error": str(e)}
        save(root / STATE, state)
        raise
    rec = {"status": "PUBLISHED", "kit": item["kit"], "format": item["format"], "media_id": media_id,
           "published_at": iso(now), "caption_sha256": sha(pay["caption"].encode())}
    try:
        rec["permalink"] = g.call("GET", media_id, {"fields": "permalink"}).get("permalink")
    except Refused:
        pass
    state["items"][item["id"]] = rec
    save(root / STATE, state)
    return {"result": "PUBLISHED", "item": item["id"], "permalink": rec.get("permalink")}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("command", choices=["prepare", "publish"])
    ap.add_argument("--root", default=str(HERE.parents[1]))
    ap.add_argument("--nova", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--commit", default="")
    ap.add_argument("--now", default="")
    ap.add_argument("--preview-next", action="store_true")
    a = ap.parse_args()
    root = Path(a.root)
    try:
        if a.command == "prepare":
            out = {"prepared": prepare(root, a.nova)}
        else:
            now = when(a.now) if a.now else datetime.now(timezone.utc)
            token = os.environ.get("IG_TOKEN", "").strip()
            if not a.commit:
                raise Refused("COMMIT_SHA_REQUIRED")
            out = publish(root, now, Graph(token) if token else None, os.environ.get("IG_ID", "").strip(),
                          os.environ.get("GITHUB_REPOSITORY", "vickykenin-lang/aura-3.0"), a.commit,
                          dry_run=a.dry_run, preview_next=a.preview_next)
    except (Refused, build_kit.KitError) as e:
        print(json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False))
        sys.exit(4)
    print(json.dumps({"ok": True, **out}, ensure_ascii=False))


if __name__ == "__main__":
    main()
