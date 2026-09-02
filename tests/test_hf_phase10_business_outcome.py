import unittest

from scripts.evaluate_hf_phase10_business_outcome import evaluate


POLICY = {
    "eligible_outcome_classes": [
        "CONTENT_REWRITE_ATTRIBUTED_TO_HF_WARNING",
        "MEASURED_REVIEW_TIME_REDUCTION",
        "PUBLISHED_CONTENT_DIVERSITY_IMPROVEMENT",
        "ENGAGEMENT_IMPROVEMENT",
        "ENQUIRY_IMPROVEMENT",
        "QUALIFIED_LEAD_IMPROVEMENT",
        "REVENUE_ATTRIBUTED",
    ],
    "verification_thresholds": {
        "content_rewrites_attributed_to_warning_min": 1,
        "review_minutes_saved_min": 1,
        "published_content_diversity_change_min_percentage_points": 5,
        "engagement_change_min_percent": 5,
        "enquiries_change_min_count": 1,
        "qualified_leads_change_min_count": 1,
        "revenue_attributed_min_inr": 1,
    },
}

PHASE9 = {
    "lifecycle": {"production_deployed": True, "live_verified": True},
    "privacy_and_authority": {"business_outcome_verified": False},
}


class Phase10BusinessOutcomeGateTests(unittest.TestCase):
    def test_empty_real_world_evidence_is_insufficient_not_verified(self):
        ledger = {
            "measurement_window": {"status": "NOT_ESTABLISHED", "hf_warning_interventions_observed": 0},
            "verified_outcomes": [],
            "pending_metrics": {"review_minutes_saved": "NOT_MEASURED"},
        }
        result = evaluate(POLICY, ledger, PHASE9, {}, {"business_outcome": {"qualified_leads": 0}})
        self.assertEqual(result["verdict"], "INSUFFICIENT_REAL_WORLD_EVIDENCE")
        self.assertFalse(result["business_outcome_verified"])
        self.assertIn("NO_CANONICAL_PUBLISHED_ITEMS", result["reason_codes"])

    def test_technical_success_alone_never_verifies_business_outcome(self):
        ledger = {
            "measurement_window": {"status": "ESTABLISHED", "hf_warning_interventions_observed": 0},
            "verified_outcomes": [],
            "pending_metrics": {},
        }
        result = evaluate(POLICY, ledger, PHASE9, {"post-1": {}}, {"business_outcome": {"qualified_leads": 0}})
        self.assertFalse(result["business_outcome_verified"])
        self.assertEqual(result["verdict"], "INSUFFICIENT_REAL_WORLD_EVIDENCE")

    def test_real_attributed_outcome_can_pass_gate(self):
        ledger = {
            "measurement_window": {"status": "ESTABLISHED", "hf_warning_interventions_observed": 2},
            "verified_outcomes": [{
                "outcome_class": "MEASURED_REVIEW_TIME_REDUCTION",
                "value": 12,
                "verified": True,
                "hf_attribution": "Reviewer timing log comparing warning-assisted review with baseline",
                "source_record": "review-log-001",
                "measurement_method": "before_after_timed_review",
                "measurement_window": "2026-09-02/2026-09-09"
            }],
            "pending_metrics": {},
        }
        result = evaluate(POLICY, ledger, PHASE9, {"post-1": {}, "post-2": {}}, {"business_outcome": {"qualified_leads": 0}})
        self.assertEqual(result["verdict"], "BUSINESS_OUTCOME_VERIFIED")
        self.assertTrue(result["business_outcome_verified"])
        self.assertEqual(result["evidence_snapshot"]["verified_outcomes_meeting_gate"], 1)

    def test_unattributed_metric_cannot_pass(self):
        ledger = {
            "measurement_window": {"status": "ESTABLISHED", "hf_warning_interventions_observed": 2},
            "verified_outcomes": [{
                "outcome_class": "ENGAGEMENT_IMPROVEMENT",
                "value": 25,
                "verified": True,
                "hf_attribution": "",
                "source_record": "analytics-001",
                "measurement_method": "before_after",
                "measurement_window": "2026-09-02/2026-09-09"
            }],
            "pending_metrics": {},
        }
        result = evaluate(POLICY, ledger, PHASE9, {"post-1": {}}, {"business_outcome": {"qualified_leads": 0}})
        self.assertEqual(result["verdict"], "BUSINESS_OUTCOME_NOT_VERIFIED")
        self.assertFalse(result["business_outcome_verified"])


if __name__ == "__main__":
    unittest.main()
