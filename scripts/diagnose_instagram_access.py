#!/usr/bin/env python3
"""Read-only Meta/Instagram credential diagnostics without exposing secret values."""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "evaluation/results/aura3-instagram-credential-diagnostic.json"
API_VERSION = os.environ.get("IG_GRAPH_API_VERSION", "v25.0").strip() or "v25.0"
TOKEN = os.environ.get("IG_TOKEN", "").strip()
ACCOUNT_ID = os.environ.get("IG_ID", "").strip()


def call(base: str, path: str, fields: str) -> tuple[bool, dict, dict]:
    params = urllib.parse.urlencode({"fields": fields, "access_token": TOKEN})
    url = f"{base}/{API_VERSION}/{path.lstrip('/')}?{params}"
    try:
        with urllib.request.urlopen(url, timeout=30) as response:
            payload = json.loads(response.read().decode("utf-8"))
        return True, payload if isinstance(payload, dict) else {}, {}
    except urllib.error.HTTPError as exc:
        try:
            payload = json.loads(exc.read().decode("utf-8"))
        except Exception:
            payload = {}
        err = payload.get("error") if isinstance(payload, dict) else {}
        return False, {}, {
            "http_status": exc.code,
            "meta_code": err.get("code") if isinstance(err, dict) else None,
            "meta_subcode": err.get("error_subcode") if isinstance(err, dict) else None,
            "error_type": err.get("type") if isinstance(err, dict) else None,
        }
    except Exception as exc:
        return False, {}, {"error_type": type(exc).__name__}


fb_me_ok, fb_me, fb_me_err = call("https://graph.facebook.com", "me", "id,name")
ig_me_ok, ig_me, ig_me_err = call("https://graph.instagram.com", "me", "id,username")
fb_pages_ok, fb_pages, fb_pages_err = call(
    "https://graph.facebook.com", "me/accounts", "id,name,instagram_business_account"
)
configured_ok = False
configured_err = {}
if ACCOUNT_ID:
    configured_ok, _, configured_err = call(
        "https://graph.facebook.com", ACCOUNT_ID, "id,username"
    )

pages = fb_pages.get("data", []) if fb_pages_ok and isinstance(fb_pages.get("data"), list) else []
linked = []
for page in pages:
    if isinstance(page, dict):
        account = page.get("instagram_business_account")
        if isinstance(account, dict) and account.get("id"):
            linked.append(True)

if ig_me_ok:
    diagnosis = "INSTAGRAM_LOGIN_TOKEN_VALID"
    required_action = "Use this Instagram Login token; account target can be discovered from /me."
elif fb_me_ok and len(linked) == 1:
    diagnosis = "FACEBOOK_TOKEN_VALID_SINGLE_LINKED_INSTAGRAM_ACCOUNT"
    required_action = "Token can see one linked Instagram Professional account; use that linked account mapping."
elif fb_me_ok and fb_pages_ok and len(linked) == 0:
    diagnosis = "FACEBOOK_TOKEN_VALID_NO_LINKED_INSTAGRAM_ACCOUNT_VISIBLE"
    required_action = "Link the Instagram Professional account to a Facebook Page and grant the token the required Page/Instagram publishing permissions."
elif fb_me_ok and not fb_pages_ok:
    diagnosis = "FACEBOOK_TOKEN_VALID_PAGE_DISCOVERY_NOT_AUTHORIZED"
    required_action = "Regenerate the Meta user/page token with Page discovery and Instagram publishing permissions for the linked Professional account."
else:
    diagnosis = "TOKEN_NOT_VALID_FOR_SUPPORTED_INSTAGRAM_PUBLISH_PATH"
    required_action = "Replace the configured token with a valid Meta publishing token for the Instagram Professional account."

payload = {
    "schema_version": 1,
    "department_id": "aura3",
    "mode": "READ_ONLY_CREDENTIAL_DIAGNOSTIC",
    "secret_values_recorded": False,
    "public_action_performed": False,
    "token_present": bool(TOKEN),
    "configured_account_id_present": bool(ACCOUNT_ID),
    "facebook_me": {"success": fb_me_ok, "error": fb_me_err},
    "instagram_me": {"success": ig_me_ok, "error": ig_me_err},
    "facebook_pages": {
        "success": fb_pages_ok,
        "managed_page_count": len(pages),
        "linked_instagram_account_count": len(linked),
        "error": fb_pages_err,
    },
    "configured_account_access": {"success": configured_ok, "error": configured_err},
    "diagnosis": diagnosis,
    "required_action": required_action,
    "truth_note": "This diagnostic performs read-only GET requests only. It does not publish, mutate Meta state, or expose token/account identifiers."
}
OUT.parent.mkdir(parents=True, exist_ok=True)
OUT.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
print(json.dumps(payload, indent=2))
