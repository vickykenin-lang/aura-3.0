import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load(path):
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def test_identity_and_orchestrator():
    c = load("governance/department_contract.json")
    assert c["department_id"] == "aura3"
    assert c["organizational_orchestrator"] == "victor"
    assert c["business_execution_enabled"] is False


def test_heartbeat_ladder():
    h = load("governance/heartbeat_policy.json")
    assert h["approved_ladder_minutes"] == [60,30,15,10,5,3,2]
    assert h["minimum_minutes"] == 2


def test_publication_is_founder_only():
    a = load("governance/authority_policy.json")
    assert a["rules"]["instagram_publish"] == "FOUNDER_ONLY"


def test_fail_closed_control():
    c = load("state/control.json")
    assert c["kill_switch"] is True
    assert c["business_execution_enabled"] is False
    assert c["external_execution_enabled"] is False


def test_provider_and_capability_truth_reset():
    p = load("governance/providers.json")
    assert all(v["qualification"] == "NOT_VERIFIED_FOR_AURA3" for v in p["slots"].values())
    caps = load("governance/capabilities.json")["capabilities"]
    assert not any(x.get("qualification") == "LIVE" for x in caps)
