import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load(path):
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def test_identity_and_orchestrator():
    c = load("governance/department_contract.json")
    assert c["department_id"] == "aura3"
    assert c["authority"]["supreme"] == "Founder"
    assert c["future_integrations"]["victor"]["status"] == "INACTIVE"
    assert c["public_release"]["instagram_publish"] == "FOUNDER_ONLY"


def test_heartbeat_ladder():
    h = load("governance/heartbeat_policy.json")
    assert h["approved_ladder_minutes"] == [60,30,15,10,5,3,2]
    assert h["minimum_minutes"] == 2


def test_publication_is_founder_only():
    a = load("governance/authority_policy.json")
    assert a["rules"]["instagram_publish"] == "FOUNDER_ONLY"


def test_fail_closed_control():
    c = load("state/control.json")
    assert isinstance(c["kill_switch"], bool)
    assert isinstance(c["business_execution_enabled"], bool)
    if c["certification_status"] != "VERIFIED":
        assert c["external_execution_enabled"] is False


def test_provider_and_capability_truth_reset():
    p = load("governance/providers.json")
    for v in p["slots"].values():
        if v.get("execution_mode") == "SHADOW_ONLY":
            assert v["production_authority"] is False
            assert v["qualification"] == "NOT_VERIFIED_FOR_PRODUCTION_AUTHORITY"
        else:
            assert v["qualification"] == "NOT_VERIFIED_FOR_AURA3"
    caps = load("governance/capabilities.json")["capabilities"]
    assert not any(x.get("qualification") == "LIVE" for x in caps)
