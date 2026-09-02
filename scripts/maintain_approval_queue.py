#!/usr/bin/env python3
"""Maintain a rolling AURA3 Founder-approval queue capped at 20 unique-image posts."""

from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlsplit

import generate_candidates as generator
import score_with_deepseek as quality_gate

ROOT = Path(__file__).resolve().parents[1]
IST = timezone(timedelta(hours=5, minutes=30))
DEFAULT_TARGET = 20
GENERATOR_BATCH = 10
MAX_REFILL_ROUNDS = 6


def load_json(path: str, default):
    try:
        return json.loads((ROOT / path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def save_json(path: str, data) -> None:
    full = ROOT / path
    full.parent.mkdir(parents=True, exist_ok=True)
    full.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def gate_passed(gate: dict | None) -> bool:
    gate = gate or {}
    return bool(gate.get("pass") and gate.get("visual_ok") and int(gate.get("score", 0)) >= 7)


def is_published(published: dict, post_id: str) -> bool:
    item = published.get(post_id) or {}
    ig = item.get("instagram") or {}
    return bool(ig.get("id") or ig.get("url") or ig.get("permalink"))


def approval_state(approvals: dict, post_id: str) -> str:
    return str(approvals.get(post_id, "pending") or "pending").strip().lower()


def image_key(value: str) -> str:
    """Canonicalize image URLs so size/query variants count as the same photo."""
    raw = str(value or "").strip()
    if not raw:
        return ""
    try:
        parsed = urlsplit(raw)
        host = (parsed.hostname or "").lower()
        path = parsed.path.rstrip("/")
        if host and path:
            return f"{host}{path}".lower()
    except ValueError:
        pass
    return raw.split("?", 1)[0].rstrip("/").lower()


def post_image_key(post: dict) -> str:
    return image_key(str(post.get("image", "")))


def approval_ready(post: dict, gates: dict, approvals: dict, published: dict) -> bool:
    post_id = str(post.get("id", "")).strip()
    if not post_id or is_published(published, post_id):
        return False
    if approval_state(approvals, post_id) != "pending":
        return False
    return gate_passed(gates.get(post_id))


def reserved_image_keys(calendar: dict, approvals: dict, published: dict) -> set[str]:
    """Images already decided/published must never re-enter the Founder approval queue."""
    reserved: set[str] = set()
    for post in calendar.get("days", []):
        post_id = str(post.get("id", "")).strip()
        key = post_image_key(post)
        if not key or not post_id:
            continue
        if is_published(published, post_id) or approval_state(approvals, post_id) != "pending":
            reserved.add(key)
    return reserved


def approval_ready_ids(calendar: dict, gate_results: dict, approvals: dict, published: dict) -> list[str]:
    """Return only one approval-ready post per unique image."""
    gates = gate_results.get("posts") or {}
    blocked = reserved_image_keys(calendar, approvals, published)
    seen: set[str] = set()
    ready: list[str] = []
    for post in calendar.get("days", []):
        if not approval_ready(post, gates, approvals, published):
            continue
        key = post_image_key(post)
        if not key or key in blocked or key in seen:
            continue
        seen.add(key)
        ready.append(str(post.get("id")))
    return ready


def reconcile_duplicate_pending_images(calendar: dict, gate_results: dict, approvals: dict, published: dict) -> list[str]:
    """Remove repeated pending cards, preferring a gate-passed keeper for each photo."""
    days = list(calendar.get("days", []))
    gates = gate_results.setdefault("posts", {})
    blocked = reserved_image_keys(calendar, approvals, published)
    pending_by_key: dict[str, list[dict]] = {}
    for post in days:
        post_id = str(post.get("id", "")).strip()
        if not post_id or is_published(published, post_id) or approval_state(approvals, post_id) != "pending":
            continue
        key = post_image_key(post)
        if key:
            pending_by_key.setdefault(key, []).append(post)

    remove_ids: set[str] = set()
    for key, posts in pending_by_key.items():
        if key in blocked:
            remove_ids.update(str(post.get("id")) for post in posts)
            continue
        passing = [post for post in posts if gate_passed(gates.get(str(post.get("id"))))]
        keeper = (passing or posts)[0]
        keeper_id = str(keeper.get("id"))
        remove_ids.update(str(post.get("id")) for post in posts if str(post.get("id")) != keeper_id)

    if remove_ids:
        calendar["days"] = [post for post in days if str(post.get("id")) not in remove_ids]
        for post_id in remove_ids:
            gates.pop(post_id, None)
    return sorted(remove_ids)


def queue_target() -> int:
    rules = load_json("data/queue_rules.json", {})
    try:
        target = int(rules.get("max_pending_on_dashboard", DEFAULT_TARGET))
    except (TypeError, ValueError):
        target = DEFAULT_TARGET
    return max(1, min(20, target))


def next_daily_sequence(calendar: dict, day_id: str) -> int:
    pattern = re.compile(rf"^{re.escape(day_id)}-(\d+)$")
    highest = 0
    for post in calendar.get("days", []):
        match = pattern.match(str(post.get("id", "")))
        if match:
            highest = max(highest, int(match.group(1)))
    return highest + 1


def fresh_pool_items(calendar: dict) -> list[dict]:
    """Return unique pool images that have never been used by the current content registry."""
    used = {post_image_key(post) for post in calendar.get("days", []) if post_image_key(post)}
    unique: list[dict] = []
    seen: set[str] = set()
    for item in load_json("data/image_pool.json", []):
        key = image_key(str(item.get("image", "")))
        if not key or key in seen or key in used:
            continue
        seen.add(key)
        unique.append(item)
    return unique


def build_generated_posts(api_key: str, calendar: dict, requested: int, round_index: int) -> tuple[list[dict], str]:
    del round_index  # selection is freshness-based, never circular/repeating.
    available = fresh_pool_items(calendar)
    selected = available[: min(requested, GENERATOR_BATCH)]
    if not selected:
        return [], ""

    generated, used_model = generator.gemini_generate(api_key, selected)
    by_slot = {int(item.get("slot", 0)): item for item in generated}
    expected_slots = set(range(1, len(selected) + 1))
    if set(by_slot) != expected_slots:
        raise RuntimeError("Gemini generator returned invalid slot coverage")

    now = datetime.now(IST)
    batch_date = now.date().isoformat()
    day_id = now.strftime("%Y%m%d")
    sequence = next_daily_sequence(calendar, day_id)
    posts: list[dict] = []
    for slot, image in enumerate(selected, start=1):
        copy = generator.normalize_copy(by_slot[slot])
        if not generator.valid_copy(copy):
            errors = ",".join(generator.copy_validation_errors(copy))
            raise RuntimeError(f"candidate {slot} failed local copy validation: {errors}")
        post_id = f"{day_id}-{sequence:02d}"
        sequence += 1
        posts.append({
            "id": post_id,
            "date": batch_date,
            "photo_tag": image["photo_tag"],
            "image": image["image"],
            "image_source": image.get("source", "curated"),
            "disclosure": "Inspiration reference",
            "ig": {
                "hook_en": str(copy["hook_en"]).strip(),
                "caption_hi": str(copy["caption_hi"]).strip(),
                "hashtags": str(copy["hashtags"]).strip(),
            },
        })
    return posts, used_model


def qualify_post(post: dict, gemini_key: str, deepseek_key: str) -> dict:
    tag = str(post.get("photo_tag") or "").lower().strip()
    if tag in quality_gate.HARD_REJECT_TAGS:
        return quality_gate.rejected(f"hard_reject_tag:{tag}")
    vision = quality_gate.gemini_vision(gemini_key, str(post.get("image", "")))
    if not vision.get("visual_ok"):
        return quality_gate.rejected("gemini_visual_reject", vision)
    business = quality_gate.deepseek_business(deepseek_key, post, vision)
    business["visual_ok"] = True
    business["vision"] = vision
    return business


def refresh_gate_metadata(gate_results: dict, calendar: dict) -> None:
    gates = gate_results.setdefault("posts", {})
    gate_results.update({
        "updated": datetime.now(IST).isoformat(),
        "pipeline": "Gemini Vision -> DeepSeek Business Gate",
        "vision_models": list(quality_gate.GEMINI_MODELS),
        "business_model": quality_gate.DEEPSEEK_MODEL,
        "batch_complete": all(str(post.get("id", "")) in gates for post in calendar.get("days", []) if post.get("id")),
    })


def write_status(
    status: str,
    target: int,
    ready: int,
    generated_ids: list[str],
    passed_ids: list[str],
    rejected_ids: list[str],
    errors: list[dict],
    models: list[str],
    removed_duplicate_ids: list[str],
    unique_pool_available: int,
) -> None:
    save_json("data/approval_queue_status.json", {
        "schema_version": 2,
        "department_id": "aura3",
        "status": status,
        "target": target,
        "approval_ready": ready,
        "deficit": max(0, target - ready),
        "unique_image_required": True,
        "unique_pool_available": unique_pool_available,
        "removed_duplicate_post_ids": removed_duplicate_ids,
        "generated_this_run": len(generated_ids),
        "generated_ids": generated_ids,
        "gate_pass_ids": passed_ids,
        "gate_reject_ids": rejected_ids,
        "technical_errors": errors,
        "generator_models": sorted(set(models)),
        "observed_at": datetime.now(IST).isoformat(),
        "disclosure_standard": "Inspiration reference",
        "truth_note": "Each Founder-approval card must use a unique image. Decided/published images and duplicate pending images are not eligible for refill. If fresh unique images are unavailable, the queue remains below 20 rather than repeating photos.",
    })


def persist_queue_state(calendar: dict, gate_results: dict) -> None:
    calendar["engine"] = "AURA3"
    calendar["mode"] = "rolling_approval_queue"
    calendar["batch_date"] = datetime.now(IST).date().isoformat()
    calendar["generator"] = "Gemini rolling queue maintainer"
    calendar["notes"] = "Maintain up to 20 dual-gate-passed posts awaiting Founder approval; one unique image per card. Disclosure: Inspiration reference."
    refresh_gate_metadata(gate_results, calendar)
    save_json("content/calendar.json", calendar)
    save_json("data/gate_results.json", gate_results)


def main() -> int:
    gemini_key = (os.environ.get("GEMINI_API_KEY") or "").strip()
    deepseek_key = (os.environ.get("DEEPSEEK_KEY") or os.environ.get("DEEPSEEK_API_KEY") or "").strip()
    if not gemini_key or not deepseek_key:
        print("REFILL BLOCKED: Gemini and DeepSeek provider secrets are required")
        return 1

    target = queue_target()
    calendar = load_json("content/calendar.json", {"engine": "AURA3", "mode": "rolling_approval_queue", "days": []})
    calendar.setdefault("days", [])
    approvals = load_json("data/approvals.json", {})
    published = load_json("content/published.json", {})
    gate_results = load_json("data/gate_results.json", {"posts": {}})
    gates = gate_results.setdefault("posts", {})

    generated_ids: list[str] = []
    passed_ids: list[str] = []
    rejected_ids: list[str] = []
    errors: list[dict] = []
    models: list[str] = []

    removed_duplicates = reconcile_duplicate_pending_images(calendar, gate_results, approvals, published)
    ready = len(approval_ready_ids(calendar, gate_results, approvals, published))
    available = len(fresh_pool_items(calendar))

    if ready >= target:
        persist_queue_state(calendar, gate_results)
        write_status("QUEUE_FULL_UNIQUE_IMAGES", target, ready, [], [], [], [], [], removed_duplicates, available)
        print(f"Unique-image approval queue full: {ready}/{target}")
        return 0

    if available == 0:
        persist_queue_state(calendar, gate_results)
        write_status("QUEUE_WAITING_FOR_UNIQUE_IMAGES", target, ready, [], [], [], [], [], removed_duplicates, 0)
        print(json.dumps({"status": "QUEUE_WAITING_FOR_UNIQUE_IMAGES", "approval_ready": ready, "target": target, "removed_duplicates": removed_duplicates}, indent=2))
        return 0

    try:
        quality_gate.deepseek_preflight(deepseek_key)
    except Exception as error:
        persist_queue_state(calendar, gate_results)
        write_status("REFILL_BLOCKED_PROVIDER_PREFLIGHT", target, ready, [], [], [], [{"type": type(error).__name__}], [], removed_duplicates, available)
        print(f"REFILL BLOCKED: {type(error).__name__}")
        return 1

    generation_failed = False
    pool_exhausted = False
    for round_index in range(MAX_REFILL_ROUNDS):
        ready = len(approval_ready_ids(calendar, gate_results, approvals, published))
        deficit = target - ready
        if deficit <= 0:
            break
        requested = min(deficit, GENERATOR_BATCH)
        try:
            new_posts, model = build_generated_posts(gemini_key, calendar, requested, round_index)
            if not new_posts:
                pool_exhausted = True
                break
            if model:
                models.append(model)
        except Exception as error:
            errors.append({"stage": "generation", "type": type(error).__name__})
            generation_failed = True
            break

        for post in new_posts:
            post_id = post["id"]
            calendar["days"].append(post)
            generated_ids.append(post_id)
            try:
                result = qualify_post(post, gemini_key, deepseek_key)
                gates[post_id] = result
                if gate_passed(result):
                    passed_ids.append(post_id)
                else:
                    rejected_ids.append(post_id)
            except Exception as error:
                errors.append({"stage": "qualification", "post_id": post_id, "type": type(error).__name__})
                continue

        if generation_failed:
            break
        if not fresh_pool_items(calendar):
            pool_exhausted = True
            break

    persist_queue_state(calendar, gate_results)
    ready = len(approval_ready_ids(calendar, gate_results, approvals, published))
    available = len(fresh_pool_items(calendar))
    if ready >= target:
        status = "QUEUE_REFILLED_UNIQUE_IMAGES"
    elif pool_exhausted or available == 0:
        status = "QUEUE_WAITING_FOR_UNIQUE_IMAGES"
    elif errors:
        status = "QUEUE_PARTIAL_TECHNICAL_ERROR"
    else:
        status = "QUEUE_PARTIAL_MAX_ROUNDS"
    write_status(status, target, ready, generated_ids, passed_ids, rejected_ids, errors, models, removed_duplicates, available)
    print(json.dumps({"status": status, "approval_ready": ready, "target": target, "generated": len(generated_ids), "passed": len(passed_ids), "rejected": len(rejected_ids), "removed_duplicates": removed_duplicates, "unique_pool_available": available, "technical_errors": errors}, indent=2))
    return 0 if status in {"QUEUE_REFILLED_UNIQUE_IMAGES", "QUEUE_WAITING_FOR_UNIQUE_IMAGES"} else 1


if __name__ == "__main__":
    sys.exit(main())
