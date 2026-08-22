#!/usr/bin/env python3
"""Publish one Founder-approved AURA2 image post through the Instagram API."""

from __future__ import annotations

import hashlib
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
POST_ID = os.environ.get("POST_ID", "").strip()
API_VERSION = os.environ.get("IG_GRAPH_API_VERSION", "v25.0").strip() or "v25.0"
REQUEST_TIMEOUT = 45
STATUS_POLL_SECONDS = 60
STATUS_POLLS = 5


class PublishError(RuntimeError):
    """A safe-to-log Instagram publishing failure."""


def load_json(path: str, default):
    try:
        with open(os.path.join(ROOT, path), encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, json.JSONDecodeError):
        return default


def save_json(path: str, data) -> None:
    with open(os.path.join(ROOT, path), "w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2, ensure_ascii=False)
        handle.write("\n")


def fail(message: str) -> int:
    print(f"REFUSED: {message}")
    return 1


def api_bases() -> list[str]:
    configured = os.environ.get("IG_GRAPH_HOST", "").strip().rstrip("/")
    if configured:
        return [configured]
    # Facebook Login uses graph.facebook.com; Instagram Login uses graph.instagram.com.
    return ["https://graph.facebook.com", "https://graph.instagram.com"]


def request_json(base: str, method: str, path: str, token: str, params: dict) -> dict:
    safe_path = path.strip("/")
    url = f"{base}/{API_VERSION}/{safe_path}"
    values = {**params, "access_token": token}
    data = None
    if method == "GET":
        url = f"{url}?{urllib.parse.urlencode(values)}"
    else:
        data = urllib.parse.urlencode(values).encode("utf-8")
    request = urllib.request.Request(url, data=data, method=method)
    request.add_header("Content-Type", "application/x-www-form-urlencoded")
    try:
        with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        try:
            payload = json.loads(exc.read().decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            raise PublishError(f"Instagram API HTTP {exc.code}") from None
    except urllib.error.URLError:
        raise PublishError("Instagram API network request failed") from None
    except json.JSONDecodeError:
        raise PublishError("Instagram API returned invalid JSON") from None

    if isinstance(payload, dict) and payload.get("error"):
        error = payload["error"]
        code = error.get("code", "unknown")
        subcode = error.get("error_subcode")
        message = str(error.get("message", "request rejected")).replace(token, "[REDACTED]")[:300]
        suffix = f"/{subcode}" if subcode else ""
        raise PublishError(f"Instagram API error {code}{suffix}: {message}")
    if not isinstance(payload, dict):
        raise PublishError("Instagram API returned an unexpected response")
    return payload


def build_caption(post: dict) -> str:
    instagram = post.get("ig") or {}
    parts = [
        instagram.get("hook_en", "").strip(),
        instagram.get("caption_hi", "").strip(),
        post.get("disclosure", "").strip(),
        instagram.get("hashtags", "").strip(),
    ]
    caption = "\n\n".join(part for part in parts if part)
    if not caption:
        raise PublishError("caption is empty")
    if len(caption) > 2200:
        raise PublishError("caption exceeds Instagram's 2,200 character limit")
    return caption


def discover_target(token: str) -> tuple[str, str] | None:
    """Resolve one unambiguous Professional account from the supplied token."""
    instagram_base = "https://graph.instagram.com"
    facebook_base = "https://graph.facebook.com"

    # Instagram Login tokens are scoped directly to one Professional account.
    try:
        payload = request_json(
            instagram_base,
            "GET",
            "me",
            token,
            {"fields": "id,username"},
        )
        user_id = str(payload.get("id", "")).strip()
        if user_id:
            return instagram_base, user_id
    except PublishError:
        pass

    # A Page access token can expose its single linked Instagram account directly.
    try:
        payload = request_json(
            facebook_base,
            "GET",
            "me",
            token,
            {"fields": "id,instagram_business_account"},
        )
        account = payload.get("instagram_business_account") or {}
        user_id = str(account.get("id", "")).strip()
        if user_id:
            return facebook_base, user_id
    except PublishError:
        pass

    # A User access token may manage pages. Auto-select only when exactly one IG account exists.
    try:
        payload = request_json(
            facebook_base,
            "GET",
            "me/accounts",
            token,
            {"fields": "instagram_business_account"},
        )
        ids = {
            str((page.get("instagram_business_account") or {}).get("id", "")).strip()
            for page in payload.get("data", [])
        }
        ids.discard("")
        if len(ids) == 1:
            return facebook_base, ids.pop()
        if len(ids) > 1:
            raise PublishError(
                "token manages multiple Instagram accounts; IG_ID_USER must identify one account"
            )
    except PublishError as exc:
        if "multiple Instagram accounts" in str(exc):
            raise
    return None


def create_container(
    image_url: str, caption: str, user_id: str, token: str
) -> tuple[str, str, str]:
    failures = []
    discovered = discover_target(token)
    targets = [discovered] if discovered else [(base, user_id) for base in api_bases()]
    for base, target_user_id in targets:
        try:
            payload = request_json(
                base,
                "POST",
                f"{target_user_id}/media",
                token,
                {"image_url": image_url, "caption": caption},
            )
            container_id = str(payload.get("id", "")).strip()
            if not container_id:
                raise PublishError("media container ID was missing")
            return base, target_user_id, container_id
        except PublishError as exc:
            failures.append(str(exc))
    raise PublishError("container creation failed: " + " | ".join(failures))


def wait_until_ready(base: str, container_id: str, token: str) -> None:
    for attempt in range(STATUS_POLLS + 1):
        payload = request_json(
            base,
            "GET",
            container_id,
            token,
            {"fields": "status_code"},
        )
        status = str(payload.get("status_code", "")).upper()
        if status in {"FINISHED", "PUBLISHED"}:
            return
        if status in {"ERROR", "EXPIRED"}:
            raise PublishError(f"media container status is {status}")
        if attempt == STATUS_POLLS:
            break
        time.sleep(STATUS_POLL_SECONDS)
    raise PublishError("media container did not become ready within five minutes")


def publish_to_instagram(post: dict, user_id: str, token: str) -> dict:
    image_url = str(post.get("image", "")).strip()
    if not image_url.startswith(("https://", "http://")):
        raise PublishError("image must have a public HTTP URL")
    caption = build_caption(post)
    base, target_user_id, container_id = create_container(image_url, caption, user_id, token)
    wait_until_ready(base, container_id, token)
    published = request_json(
        base,
        "POST",
        f"{target_user_id}/media_publish",
        token,
        {"creation_id": container_id},
    )
    media_id = str(published.get("id", "")).strip()
    if not media_id:
        raise PublishError("published media ID was missing")

    details = {}
    try:
        details = request_json(
            base,
            "GET",
            media_id,
            token,
            {"fields": "id,permalink,timestamp,media_type"},
        )
    except PublishError:
        # The returned media ID is authoritative even if optional metadata lookup fails.
        pass

    return {
        "id": media_id,
        "url": details.get("permalink", ""),
        "at": details.get("timestamp") or datetime.now(timezone.utc).isoformat(),
        "container_id": container_id,
        "media_type": details.get("media_type", "IMAGE"),
        "caption_sha256": hashlib.sha256(caption.encode("utf-8")).hexdigest(),
    }


def main() -> int:
    control = load_json("data/control.json", {"kill_switch": True})
    if control.get("kill_switch"):
        return fail("KILL SWITCH ON — Instagram publishing is disabled")

    approvals = load_json("data/approvals.json", {})
    calendar = load_json("content/calendar.json", {"days": []})
    gate_results = load_json("data/gate_results.json", {"posts": {}})
    published = load_json("content/published.json", {})

    post_id = POST_ID
    if not post_id:
        post_id = next(
            (
                post.get("id", "")
                for post in calendar.get("days", [])
                if approvals.get(post.get("id")) == "approved_manual"
                and post.get("id") not in published
            ),
            "",
        )
    if not post_id:
        return fail("no approved unpublished post is available")

    existing = published.get(post_id)
    if existing and (existing.get("instagram") or {}).get("id"):
        approvals[post_id] = "published"
        save_json("data/approvals.json", approvals)
        print(f"ALREADY PUBLISHED: {post_id}")
        return 0

    if approvals.get(post_id) != "approved_manual":
        return fail(f"{post_id} is not Founder-approved for publishing")

    post = next((item for item in calendar.get("days", []) if item.get("id") == post_id), None)
    if not post:
        return fail(f"unknown current-calendar post id: {post_id}")

    if not gate_results.get("batch_complete"):
        return fail("latest dual-gate batch is incomplete")
    gate = gate_results.get("posts", {}).get(post_id) or {}
    if not gate.get("pass") or not gate.get("visual_ok") or int(gate.get("score", 0)) < 7:
        return fail("post no longer passes the strict dual gate")

    token = os.environ.get("IG_TOKEN_USER", "").strip()
    user_id = os.environ.get("IG_ID_USER", "").strip()
    if not token or not user_id:
        return fail("IG_TOKEN_USER and IG_ID_USER secrets are required")

    try:
        instagram = publish_to_instagram(post, user_id, token)
    except PublishError as exc:
        return fail(str(exc))

    published[post_id] = {
        "instagram": instagram,
        "source": "AURA2 automatic owner-approved publish",
    }
    approvals[post_id] = "published"
    save_json("content/published.json", published)
    save_json("data/approvals.json", approvals)
    print(f"INSTAGRAM POSTED: {post_id} -> media {instagram['id']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
