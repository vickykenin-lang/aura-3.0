from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_json(path: str):
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


class HFPhase5ReadinessTests(unittest.TestCase):
    def test_primary_model_is_pinned_safetensors_only_and_non_authoritative(self):
        registry = load_json("hf/model_registry.json")
        model = registry["models"]["siglip_primary"]
        self.assertRegex(model["revision"], r"^[0-9a-f]{40}$")
        self.assertTrue(model["safetensors_required"])
        self.assertFalse(model["trust_remote_code"])
        self.assertFalse(model["production_authority"])
        self.assertEqual(model["qualified_scope"], "ROOM_TAXONOMY_AND_INTERIOR_RELEVANCE_ONLY")
        self.assertEqual(model["production_readiness"], "READY_FOR_CONTROLLED_SHADOW_DEPLOYMENT_ONLY")

    def test_licence_security_gate_for_primary(self):
        registry = load_json("hf/licence_registry.json")
        entry = registry["entries"]["google/siglip-base-patch16-224@7fd15f0689c79d79e38b1c2e2e2370a7bf2761ed"]
        self.assertEqual(entry["licence"], "apache-2.0")
        self.assertTrue(entry["safetensors_present"])
        self.assertTrue(entry["safetensors_required_by_runtime"])
        self.assertFalse(entry["legacy_pickle_weight_allowed_by_runtime"])
        self.assertFalse(entry["remote_code_required"])
        self.assertEqual(entry["security_status"], "RUNTIME_QUALIFIED_FOR_SHADOW_SCOPE")

    def test_runtime_forces_safetensors_and_disables_remote_code(self):
        source = (ROOT / "runtime/hf_shadow.py").read_text(encoding="utf-8")
        self.assertIn('"trust_remote_code": False', source)
        self.assertIn('model_kwargs["use_safetensors"] = True', source)

    def test_direct_and_transitive_dependencies_are_exact_pins(self):
        for path in ("hf/requirements-shadow.txt", "hf/constraints-shadow.txt"):
            lines = [
                line.strip()
                for line in (ROOT / path).read_text(encoding="utf-8").splitlines()
                if line.strip() and not line.lstrip().startswith("#")
            ]
            self.assertGreater(len(lines), 0)
            for line in lines:
                self.assertRegex(line, r"^[A-Za-z0-9_.-]+==[^<>=!~\s]+$")

    def test_config_resource_cost_data_and_rollback_controls(self):
        config = load_json("hf/config.json")
        self.assertFalse(config["enabled"])
        self.assertFalse(config["production_authority"])
        self.assertFalse(config["required_for_business_execution"])
        self.assertEqual(config["execution"]["python_version"], "3.12.14")
        self.assertEqual(config["execution"]["torch_version"], "2.14.0+cpu")
        self.assertEqual(config["execution"]["production_shadow_boundary"], "SEPARATE_GITHUB_ACTIONS_JOB")
        self.assertLessEqual(config["execution"]["max_job_minutes"], 30)
        self.assertLessEqual(config["execution"]["max_cases_per_run"], 10)
        self.assertFalse(config["execution"]["gpu_allowed"])
        self.assertFalse(config["cost_policy"]["hf_hosted_paid_inference_allowed"])
        self.assertFalse(config["cost_policy"]["hf_dedicated_endpoint_allowed"])
        self.assertLessEqual(config["cost_policy"]["phase1_5_external_spend_ceiling_usd"], 2.0)
        self.assertFalse(config["data_policy"]["confidential_client_data_allowed"])
        self.assertFalse(config["data_policy"]["lead_or_contact_data_allowed"])
        self.assertFalse(config["security"]["inject_hf_token_for_public_primary"])
        self.assertFalse(config["rollback"]["requires_database_rollback"])

    def test_readiness_policy_blocks_authority_and_requires_job_isolation(self):
        policy = load_json("hf/production_readiness_policy.json")
        self.assertEqual(policy["target"], "CONTROLLED_PRODUCTION_SHADOW_DEPLOYMENT_ONLY")
        self.assertFalse(policy["authority"]["production_decision_authority"])
        self.assertFalse(policy["authority"]["publish_authority"])
        self.assertFalse(policy["authority"]["routing_authority"])
        self.assertEqual(policy["execution_boundary"]["required_boundary"], "SEPARATE_GITHUB_ACTIONS_JOB")
        self.assertFalse(policy["execution_boundary"]["in_process_production_hook_allowed"])
        self.assertEqual(policy["promotion_gate"]["production_authority_promotion"], "BLOCKED")
        self.assertEqual(policy["promotion_gate"]["live_claim_before_main_deploy"], "BLOCKED")

    def test_workflow_supply_chain_and_secret_hardening(self):
        workflow = (ROOT / ".github/workflows/aura3-hf-shadow-evaluation.yml").read_text(encoding="utf-8")
        self.assertNotRegex(workflow, r"uses:\s+[^\s]+@v\d")
        self.assertIn("actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1", workflow)
        self.assertIn("actions/setup-python@5fda3b95a4ea91299a34e894583c3862153e4b97", workflow)
        self.assertIn("actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a", workflow)
        self.assertGreaterEqual(workflow.count("persist-credentials: false"), 5)
        self.assertNotIn("secrets.HF_AURA3_EVAL_TOKEN", workflow)
        self.assertIn("python-version: '3.12.14'", workflow)
        self.assertIn("torch==2.14.0+cpu", workflow)
        self.assertIn("-c hf/constraints-shadow.txt", workflow)

    def test_blip_remains_disabled_and_not_ready(self):
        registry = load_json("hf/model_registry.json")
        model = registry["models"]["blip_caption_candidate"]
        self.assertFalse(model["enabled_for_shadow"])
        self.assertEqual(model["qualification"], "CANDIDATE_NOT_TESTED")
        self.assertEqual(model["production_readiness"], "NOT_READY")


if __name__ == "__main__":
    unittest.main(verbosity=2)
