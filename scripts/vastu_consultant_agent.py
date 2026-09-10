#!/usr/bin/env python3
"""Governed Vastu consultant + post-maker lane for AURA3.

This agent researches traditional Vastu ideas on the public web, selects a current
licensed AURA3 interior image, can redevelop it with Amazon Nova Canvas, writes an
image-grounded Hinglish post, cross-reviews it with the alternate provider, and
hands only gate-passed posts into the existing Founder approval calendar.

It never approves or publishes content itself.
"""
from __future__ import annotations

import base64
import html
import json
import os
import re
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlsplit

import boto3

import aura3_nova_runtime as nova
import aura3_resilient_queue as resilient

ROOT = Path(__file__).resolve().parents[1]
IST = timezone(timedelta(hours=5, minutes=30))
CHARTER = ROOT / "governance/vastu_consultant_agent.json"
STATE = ROOT / "data/vastu_agent_state.json"
RESEARCH = ROOT / "data/vastu_research.json"
CALENDAR = ROOT / "content/calendar.json"
GATES = ROOT / "data/gate_results.json"
POOL = ROOT / "data/image_pool.json"
BLACKLIST = ROOT / "data/dead_image_blacklist.json"
ASSET_DIR = ROOT / "assets/vastu"
REPO_RAW = "https://raw.githubusercontent.com/vickykenin-lang/aura-3.0/main/"

TOPIC_BANK = [
    ("main entrance", "entrance", "main entrance vastu direction practical interior design"),
    ("living room seating", "living", "living room vastu seating placement practical interior"),
    ("bedroom mirror", "bedroom", "bedroom mirror placement vastu practical interior"),
    ("bed direction", "bedroom", "bed direction vastu bedroom practical guidance"),
    ("kitchen placement", "kitchen", "kitchen vastu placement stove sink practical interior"),
    ("pooja room", "living", "pooja room vastu placement practical home interior"),
    ("home office desk", "office", "home office desk direction vastu practical workspace"),
    ("office reception", "reception", "office reception vastu practical commercial interior"),
    ("work desk placement", "workspace", "office desk placement vastu productivity traditional guidance"),
    ("meeting room", "meeting", "meeting room vastu practical corporate interior"),
    ("lighting and ventilation", "living", "vastu lighting ventilation home practical interior"),
    ("indoor plants", "living", "indoor plants vastu placement practical home interior"),
    ("colour planning", "living", "vastu colour guidance room practical interior design"),
    ("storage and clutter", "bedroom", "vastu clutter storage practical interior guidance"),
]


def load(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def save(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def strip_tags(value: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html.unescape(str(value or "")))).strip()


def image_key(url: str) -> str:
    try:
        p = urlsplit(str(url or ""))
        return ((p.hostname or "") + p.path.rstrip("/")).lower()
    except ValueError:
        return str(url or "").split("?", 1)[0].lower()


def topic_state() -> tuple[str, str, str, int]:
    state = load(STATE, {})
    idx = int(state.get("topic_index", 0) or 0) % len(TOPIC_BANK)
    topic, tag, query = TOPIC_BANK[idx]
    return topic, tag, query, idx


def ddg_research(query: str, minimum_sources: int = 2, max_sources: int = 5) -> list[dict]:
    url = "https://html.duckduckgo.com/html/?" + urllib.parse.urlencode({"q": query})
    req = urllib.request.Request(url, headers={"User-Agent": "AURA3-VastuResearch/1.0"})
    with urllib.request.urlopen(req, timeout=15) as response:
        text = response.read().decode("utf-8", "replace")

    anchors = list(re.finditer(r'<a[^>]+class="[^"]*result__a[^"]*"[^>]+href="([^"]+)"[^>]*>(.*?)</a>', text, re.I | re.S))
    snippets = [strip_tags(x) for x in re.findall(r'<(?:a|div)[^>]+class="[^"]*result__snippet[^"]*"[^>]*>(.*?)</(?:a|div)>', text, re.I | re.S)]
    results: list[dict] = []
    domains: set[str] = set()
    for i, match in enumerate(anchors):
        href = html.unescape(match.group(1))
        parsed = urllib.parse.urlparse(href)
        qs = urllib.parse.parse_qs(parsed.query)
        if "uddg" in qs:
            href = qs["uddg"][0]
        if not href.startswith("https://"):
            continue
        domain = (urlsplit(href).hostname or "").lower().removeprefix("www.")
        if not domain or domain in domains:
            continue
        title = strip_tags(match.group(2))
        snippet = snippets[i] if i < len(snippets) else ""
        if not title:
            continue
        domains.add(domain)
        results.append({"title": title[:220], "snippet": snippet[:500], "url": href, "domain": domain})
        if len(results) >= max_sources:
            break
    if len(results) < minimum_sources:
        raise RuntimeError(f"internet research returned only {len(results)} independent sources")
    return results


def used_images() -> set[str]:
    cal = load(CALENDAR, {"days": []})
    return {image_key(x.get("image", "")) for x in cal.get("days", []) if x.get("image")}


def blacklisted_images() -> set[str]:
    data = load(BLACKLIST, {"images": {}})
    return set((data.get("images") or {}).keys())


def choose_image(tag: str) -> dict:
    used = used_images()
    blocked = blacklisted_images()
    pool = load(POOL, [])
    if not isinstance(pool, list):
        pool = []
    ranked = sorted(pool, key=lambda x: 0 if str(x.get("photo_tag", "")).lower() == tag else 1)
    for item in ranked:
        url = str(item.get("image", ""))
        key = image_key(url)
        if not url.startswith("https://") or not key or key in used or key in blocked:
            continue
        try:
            vision = resilient.strict_vision((os.environ.get("DEEPSEEK_API_KEY") or "").strip(), url)
        except Exception:
            continue
        if vision.get("visual_ok"):
            return {**item, "vision": vision}
    raise RuntimeError("no eligible current-design image available for Vastu post")


def canvas_enabled() -> bool:
    mode = (os.environ.get("AURA3_VASTU_REDEVELOP") or "auto").strip().lower()
    if mode == "no":
        return False
    creds = bool((os.environ.get("AWS_ACCESS_KEY_ID") or "").strip() and (os.environ.get("AWS_SECRET_ACCESS_KEY") or "").strip())
    return creds if mode == "auto" else True


def download_image(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "AURA3-VastuImage/1.0"})
    with urllib.request.urlopen(req, timeout=20) as response:
        return response.read()


def redevelop_with_canvas(source: dict, topic: str) -> tuple[str, Path, dict] | None:
    if not canvas_enabled():
        return None
    source_bytes = download_image(str(source["image"]))
    vision = source["vision"]
    room = vision.get("room_type", source.get("photo_tag", "interior"))
    features = ", ".join((vision.get("visible_features") or [])[:5])
    positive = (
        f"Photorealistic current premium {room} interior inspired by the reference composition, "
        f"practical Indian interior design suitable for a traditional Vastu tip about {topic}, "
        f"balanced circulation, natural light, contemporary finishes, realistic materials, {features}, "
        "editorial interior photography, clean premium styling"
    )[:850]
    negative = "vintage, retro, heritage, archival, text, typography, watermark, logo, clutter, low resolution, distorted furniture, people"
    body = {
        "taskType": "IMAGE_VARIATION",
        "imageVariationParams": {
            "text": positive,
            "negativeText": negative,
            "images": [base64.b64encode(source_bytes).decode("ascii")],
            "similarityStrength": 0.72,
        },
        "imageGenerationConfig": {
            "numberOfImages": 1,
            "height": 1200,
            "width": 1200,
            "cfgScale": 7.0,
            "seed": int(time.time()) % 2147483647,
        },
    }
    client = boto3.client("bedrock-runtime", region_name=(os.environ.get("AWS_REGION") or "us-east-1").strip())
    model = (os.environ.get("AWS_CANVAS_MODEL_ID") or "amazon.nova-canvas-v1:0").strip()
    response = client.invoke_model(modelId=model, body=json.dumps(body), accept="application/json", contentType="application/json")
    payload = json.loads(response["body"].read())
    images = payload.get("images") or []
    if not images:
        raise RuntimeError("Nova Canvas returned no image")
    output = base64.b64decode(images[0])
    ASSET_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(IST).strftime("%Y%m%d-%H%M%S")
    slug = re.sub(r"[^a-z0-9]+", "-", topic.lower()).strip("-")[:40]
    path = ASSET_DIR / f"{stamp}-{slug}.png"
    path.write_bytes(output)
    raw_url = REPO_RAW + path.relative_to(ROOT).as_posix()
    generated_vision = vision_from_bytes(output)
    if not generated_vision.get("visual_ok"):
        path.unlink(missing_ok=True)
        raise RuntimeError("redeveloped image failed strict current-design visual gate")
    return raw_url, path, generated_vision


def vision_from_bytes(image_bytes: bytes) -> dict:
    prompt = resilient.build_vision_prompt(resilient.load_rulebook())
    result = nova._converse([
        {"role": "user", "content": [
            {"image": {"format": "png", "source": {"bytes": image_bytes}}},
            {"text": prompt},
        ]}
    ], max_tokens=1400)
    if not isinstance(result, dict):
        raise RuntimeError("Nova visual validator returned non-object JSON")
    quality = int(result.get("quality", 0) or 0)
    freshness = str(result.get("design_freshness", "Unclear")).title()
    status = str(result.get("status", "DO_NOT_POST")).upper()
    legal_block = str(result.get("watermarks", "Present")).lower() != "none" or str(result.get("brand_logo_risk", "Unclear")).lower() == "present"
    visual_ok = bool(result.get("visual_ok")) and status == "APPROVED" and quality >= 7 and freshness == "Current" and not legal_block
    return {
        "visual_ok": visual_ok,
        "status": "APPROVED" if visual_ok else "DO_NOT_POST",
        "room_type": str(result.get("room_type", "other")).lower(),
        "quality": quality,
        "design_freshness": freshness,
        "style": str(result.get("style", "")),
        "visible_features": resilient._as_list(result.get("visible_features")),
        "sample_caption_angle": str(result.get("sample_caption_angle", "")),
        "model": nova.model_id(),
    }


def provider_state() -> tuple[str, dict]:
    state = load(STATE, {})
    provider = str(state.get("next_provider") or "deepseek").lower()
    if provider not in {"deepseek", "nova"}:
        provider = "deepseek"
    return provider, state


def deepseek_json(prompt: str, max_tokens: int = 1400) -> dict:
    model = (os.environ.get("DEEPSEEK_MODEL") or "deepseek-v4-flash").strip()
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "response_format": {"type": "json_object"},
        "thinking": {"type": "disabled"},
        "temperature": 0.2,
        "max_tokens": max_tokens,
    }
    result = resilient.core._deepseek_json(payload, "vastu_consultant")
    if not isinstance(result, dict):
        raise RuntimeError("DeepSeek returned non-object JSON")
    return result


def ask(provider: str, prompt: str, max_tokens: int = 1400) -> dict:
    if provider == "nova":
        result = nova._converse([{"role": "user", "content": [{"text": prompt}]}], system="You are AURA3's expert Vastu consultant and responsible interior-content strategist.", max_tokens=max_tokens, temperature=0.2)
        if not isinstance(result, dict):
            raise RuntimeError("Nova returned non-object JSON")
        return result
    return deepseek_json(prompt, max_tokens)


def make_post(topic: str, research: list[dict], image_url: str, vision: dict, provider: str) -> dict:
    evidence = "\n".join(f"- {x['title']} | {x['snippet']} | {x['url']}" for x in research)
    prompt = f"""Act as an experienced Vastu consultant who also understands modern Indian interior design.
Use the internet research evidence below as inspiration and synthesis only. Do not copy wording.
Treat Vastu as traditional guidance, not scientific certainty. Never promise health, wealth, success, fertility, relationship outcomes or guaranteed results. Avoid fear language.

TOPIC: {topic}
ACTUAL IMAGE: room={vision.get('room_type')}; style={vision.get('style')}; visible_features={vision.get('visible_features')}; caption_angle={vision.get('sample_caption_angle')}
RESEARCH:\n{evidence}

Create one practical Instagram post for Design Infra in simple natural Hinglish. The tip must fit the visible room/features. Include a realistic interior-design solution when perfect directional compliance is not practical.
Return JSON only:
{{"tip_title":"...","hook_en":"...","caption_hi":"...","hashtags":"#... #...","traditional_guidance":"...","practical_design_solution":"...","source_synthesis":"..."}}
Caption must clearly signal that this is traditional Vastu guidance and should be adapted to site conditions/personal preference. CTA should invite consultation, not make supernatural guarantees."""
    return ask(provider, prompt, 1800)


def review_post(post_copy: dict, topic: str, research: list[dict], vision: dict, reviewer: str) -> dict:
    sources = "\n".join(f"- {x['title']} | {x['snippet']} | {x['url']}" for x in research)
    prompt = f"""You are the independent AURA3 Vastu-content quality gate.
Review the proposed post against research and actual image evidence.
PASS only when score>=7 and ALL booleans below are true.
Reject scientific certainty, guaranteed health/wealth/success claims, fear claims, unsupported directional certainty, copied-looking source language, image mismatch, or impractical interior advice.

TOPIC={topic}
IMAGE room={vision.get('room_type')}; visible_features={vision.get('visible_features')}
RESEARCH:\n{sources}
POST={json.dumps(post_copy, ensure_ascii=False)}

Return JSON only:
{{"score":0,"pass":true,"vastu_grounded":true,"research_grounded":true,"image_match":true,"practical_design_ok":true,"no_overclaim":true,"cta_ok":true,"reasons":["..."]}}"""
    result = ask(reviewer, prompt, 900)
    score = max(0, min(10, int(result.get("score", 0) or 0)))
    required = ["vastu_grounded", "research_grounded", "image_match", "practical_design_ok", "no_overclaim", "cta_ok"]
    passed = bool(result.get("pass")) and score >= 7 and all(bool(result.get(k)) for k in required)
    result["score"] = score
    result["pass"] = passed
    return result


def next_id(calendar: dict) -> str:
    prefix = "vastu-" + datetime.now(IST).strftime("%Y%m%d") + "-"
    nums = []
    for item in calendar.get("days", []):
        pid = str(item.get("id", ""))
        if pid.startswith(prefix):
            try:
                nums.append(int(pid.rsplit("-", 1)[1]))
            except ValueError:
                pass
    return prefix + f"{(max(nums) + 1 if nums else 1):02d}"


def run_one() -> dict:
    charter = load(CHARTER, {})
    minimum_sources = int((charter.get("research") or {}).get("minimum_independent_sources", 2))
    topic, tag, query, topic_index = topic_state()
    research = ddg_research(query, minimum_sources=minimum_sources, max_sources=5)
    selected = choose_image(tag)
    image_url = str(selected["image"])
    vision = selected["vision"]
    image_source = str(selected.get("source", "governed source"))
    redeveloped = False
    asset_path = ""

    try:
        edited = redevelop_with_canvas(selected, topic)
    except Exception as exc:
        if (os.environ.get("AURA3_VASTU_REDEVELOP") or "auto").lower() == "yes":
            raise
        edited = None
        print(json.dumps({"vastu_image_redevelopment":"FALLBACK_TO_ORIGINAL","reason":type(exc).__name__}))
    if edited:
        image_url, local_path, vision = edited
        redeveloped = True
        asset_path = local_path.relative_to(ROOT).as_posix()
        image_source = "Amazon Nova Canvas redevelopment from governed reference"

    provider, state = provider_state()
    reviewer = "nova" if provider == "deepseek" else "deepseek"
    copy = make_post(topic, research, image_url, vision, provider)
    review = review_post(copy, topic, research, vision, reviewer)
    if not review.get("pass"):
        raise RuntimeError("Vastu expert cross-review did not pass")

    calendar = load(CALENDAR, {"engine": "AURA3", "days": []})
    calendar.setdefault("days", [])
    gates = load(GATES, {"posts": {}})
    gate_posts = gates.setdefault("posts", {})
    post_id = next_id(calendar)
    now = datetime.now(IST)
    post = {
        "id": post_id,
        "date": now.date().isoformat(),
        "photo_tag": str(vision.get("room_type") or tag),
        "image": image_url,
        "image_source": image_source,
        "disclosure": "Inspiration reference",
        "content_pillar": "vastu",
        "vastu": {
            "topic": topic,
            "tip_title": str(copy.get("tip_title", "")).strip(),
            "traditional_guidance": str(copy.get("traditional_guidance", "")).strip(),
            "practical_design_solution": str(copy.get("practical_design_solution", "")).strip(),
            "disclaimer": "Traditional Vastu guidance; adapt to practical site conditions and personal preference.",
            "research_sources": [{"title": x["title"], "url": x["url"], "domain": x["domain"]} for x in research],
            "generator_provider": provider,
            "reviewer_provider": reviewer,
            "image_redeveloped": redeveloped,
            "generated_asset": asset_path,
        },
        "ig": {
            "hook_en": str(copy.get("hook_en", "")).strip(),
            "caption_hi": str(copy.get("caption_hi", "")).strip(),
            "hashtags": str(copy.get("hashtags", "")).strip(),
        },
    }
    calendar["days"].append(post)
    gate_posts[post_id] = {
        "score": int(review["score"]),
        "pass": True,
        "visual_ok": True,
        "vision": vision,
        "vastu_grounded": True,
        "research_grounded": True,
        "caption_match": bool(review.get("image_match")),
        "practical_design_ok": bool(review.get("practical_design_ok")),
        "no_overclaim": bool(review.get("no_overclaim")),
        "research_sources": post["vastu"]["research_sources"],
        "generator_provider": provider,
        "reviewer_provider": reviewer,
        "content_pillar": "vastu",
    }
    gates["batch_complete"] = all(str(x.get("id", "")) in gate_posts for x in calendar.get("days", []) if x.get("id"))
    gates["vastu_updated_at"] = now.isoformat()
    save(CALENDAR, calendar)
    save(GATES, gates)

    research_log = load(RESEARCH, {"schema_version": 1, "department_id": "aura3", "items": []})
    items = list(research_log.get("items") or [])
    items.append({"post_id": post_id, "topic": topic, "query": query, "observed_at": now.isoformat(), "sources": post["vastu"]["research_sources"]})
    research_log["items"] = items[-100:]
    save(RESEARCH, research_log)

    state.update({
        "schema_version": 1,
        "department_id": "aura3",
        "next_provider": reviewer,
        "last_provider": provider,
        "last_reviewer": reviewer,
        "last_post_id": post_id,
        "topic_index": (topic_index + 1) % len(TOPIC_BANK),
        "updated_at": now.isoformat(),
    })
    save(STATE, state)
    return {"status": "VASTU_POST_READY_FOR_FOUNDER_APPROVAL", "post_id": post_id, "topic": topic, "provider": provider, "reviewer": reviewer, "image_redeveloped": redeveloped, "research_sources": len(research)}


def main() -> int:
    count = max(1, min(3, int(os.environ.get("AURA3_VASTU_COUNT", "1") or 1)))
    results = []
    for _ in range(count):
        results.append(run_one())
    print(json.dumps({"agent": "vastu_consultant_post_maker", "results": results}, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
