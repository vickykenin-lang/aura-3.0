#!/usr/bin/env python3
"""AURA2 Quality Gate — ping DeepSeek for each candidate.

Writes data/gate_results.json
Only pass + score >= 7 should appear on dashboard.

Env:
  DEEPSEEK_KEY or DEEPSEEK_API_KEY
"""
from __future__ import annotations

import json
import os
import re
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone, timedelta

ROOT = os.path.join(os.path.dirname(__file__), "..")
IST = timezone(timedelta(hours=5, minutes=30))
API = "https://api.deepseek.com/chat/completions"
# Prefer fast flash for cost; fallback names if account still on older aliases
MODELS = ["deepseek-v4-flash", "deepseek-chat", "deepseek-v4-pro"]

HARD_REJECT_TAGS = {
    "animal", "wildlife", "leopard", "nature-only", "landscape", "railway",
    "food-only", "meme", "kids", "bubblebee",
}

SYSTEM = """You are the AURA2 quality gate for Design Infra (premium turnkey interiors, Delhi NCR).
Score ONE Instagram candidate. Be strict.

HARD FAIL (score must be 0) if image description or URL/tag suggests:
animals, wildlife, pure landscape/nature with no interior, railway/roads as main subject,
food/coffee lifestyle with no room design, random unrelated stock, kids content.

PASS only if clearly interior-related: living, kitchen, bedroom, bathroom, dining, wardrobe,
false ceiling, home office, modular kitchen, storage, lighting design.

Also check: caption matches room type, has conversion signal (price/timeline/process),
has CTA (consultation / link in bio), brand fit Design Infra Delhi NCR.

Reply ONLY valid JSON, no markdown:
{"score":0-10,"pass":true/false,"reasons":["..."],"visual_ok":true/false,"caption_match":true/false,"cta_ok":true/false}"""


def load_json(path, default):
    p = os.path.join(ROOT, path)
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def save_json(path, data):
    p = os.path.join(ROOT, path)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def deepseek_chat(api_key: str, user: str) -> str:
    last_err = None
    for model in MODELS:
        body = {
            "model": model,
            "messages": [
                {"role": "system", "content": SYSTEM},
                {"role": "user", "content": user},
            ],
            "temperature": 0.2,
            "max_tokens": 500,
        }
        req = urllib.request.Request(
            API,
            data=json.dumps(body).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=90) as resp:
                data = json.load(resp)
            text = data["choices"][0]["message"]["content"]
            return text.strip()
        except urllib.error.HTTPError as e:
            last_err = e.read().decode("utf-8", errors="replace")[:300]
            if e.code in (400, 404):
                continue
            raise RuntimeError(f"DeepSeek HTTP {e.code}: {last_err}") from e
        except Exception as e:
            last_err = str(e)
            continue
    raise RuntimeError(f"DeepSeek failed all models: {last_err}")


def parse_score(text: str) -> dict:
    m = re.search(r"\{[^{}]*\}", text, re.DOTALL)
    if not m:
        return {
            "score": 0,
            "pass": False,
            "reasons": ["unparseable_model_reply"],
            "visual_ok": False,
            "caption_match": False,
            "cta_ok": False,
            "raw": text[:400],
        }
    try:
        obj = json.loads(m.group(0))
    except json.JSONDecodeError:
        return {
            "score": 0,
            "pass": False,
            "reasons": ["bad_json"],
            "visual_ok": False,
            "caption_match": False,
            "cta_ok": False,
            "raw": text[:400],
        }
    score = int(obj.get("score", 0))
    score = max(0, min(10, score))
    visual_ok = bool(obj.get("visual_ok", False))
    if not visual_ok:
        score = 0
    passed = bool(obj.get("pass", False)) and score >= 7 and visual_ok
    return {
        "score": score,
        "pass": passed,
        "reasons": obj.get("reasons") or [],
        "visual_ok": visual_ok,
        "caption_match": bool(obj.get("caption_match", False)),
        "cta_ok": bool(obj.get("cta_ok", False)),
    }


def main() -> int:
    key = (os.environ.get("DEEPSEEK_KEY") or os.environ.get("DEEPSEEK_API_KEY") or "").strip()
    if not key:
        print("DEEPSEEK_KEY missing — cannot heart the gate")
        return 1

    cal = load_json("content/calendar.json", {"days": []})
    days = cal.get("days") or []
    if not days:
        print("no candidates in calendar.json")
        return 1

    results = {
        "updated": datetime.now(IST).isoformat(),
        "scorer": "DeepSeek",
        "model_tried": MODELS,
        "posts": {},
    }

    for post in days:
        pid = post.get("id")
        if not pid:
            continue
        tag = (post.get("photo_tag") or post.get("tag") or "").lower()
        if tag in HARD_REJECT_TAGS:
            results["posts"][pid] = {
                "score": 0,
                "pass": False,
                "reasons": [f"hard_reject_tag:{tag}"],
                "visual_ok": False,
                "caption_match": False,
                "cta_ok": False,
            }
            print(pid, "HARD REJECT tag", tag)
            continue

        ig = post.get("ig") or {}
        user = (
            f"post_id: {pid}\n"
            f"room_tag: {tag}\n"
            f"image_url: {post.get('image', '')}\n"
            f"hook_en: {ig.get('hook_en', '')}\n"
            f"caption_hi: {ig.get('caption_hi', '')}\n"
            f"hashtags: {ig.get('hashtags', '')}\n"
            f"pre_score_hint: {post.get('score', 'n/a')}\n"
            "Judge strictly for Design Infra Instagram lead gen."
        )
        try:
            raw = deepseek_chat(key, user)
            scored = parse_score(raw)
            results["posts"][pid] = scored
            print(pid, "score", scored["score"], "pass", scored["pass"], scored.get("reasons"))
        except Exception as e:
            results["posts"][pid] = {
                "score": 0,
                "pass": False,
                "reasons": [f"deepseek_error:{e}"],
                "visual_ok": False,
                "caption_match": False,
                "cta_ok": False,
            }
            print(pid, "ERROR", e)

    save_json("data/gate_results.json", results)

    # Mirror scores into business_report for compatibility
    report = {}
    for pid, g in results["posts"].items():
        report[pid] = {"score": g.get("score", 0), "pass": g.get("pass", False), "gate": g}
    save_json("data/business_report.json", report)

    passed = sum(1 for g in results["posts"].values() if g.get("pass"))
    print(f"Gate done: {passed}/{len(results['posts'])} pass")
    return 0


if __name__ == "__main__":
    sys.exit(main())
