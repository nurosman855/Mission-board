"""Run with: python -m unittest discover -s clearpage -p 'test_*.py'."""

import copy
import unittest

from handoff import simulate_handoff, validate_research_packet


def packet():
    return {
        "schema_version": "0.1",
        "research_id": "fixture-potluck-001",
        "research_question": "Is a Christmas potluck kit worth testing?",
        "target_customer": "holiday party organizers",
        "customer_problem_hypothesis": "Coordination is difficult",
        "observed_at_utc": "2026-11-18T00:00:00Z",
        "evidence_status": "UNVERIFIED",
        "observations": [], "alternatives": [],
        "gaps": ["No independent buyer evidence"],
        "contradictions": [], "limitations": ["No source access"],
        "recommended_next_step": "RESEARCH_MORE",
        "market_validated": False, "human_go_approved": False,
        "commercial_release_allowed": False,
    }


def observation(claim="Buyer says party coordination is difficult", verification="INSPECTED_SOURCE"):
    return {
        "claim": claim, "class": "DIRECT_CUSTOMER_FEEDBACK",
        "source_url": "https://example.org/review", "source_type": "customer_review",
        "source_observed_at_utc": "2026-11-18T00:00:00Z",
        "supporting_detail": "Illustrative fixture, not real research",
        "verification": verification, "caveat": "Fictional test data",
    }


class ContractTests(unittest.TestCase):
    def test_missing_evidence_returns_research_more(self):
        result = simulate_handoff(packet())
        self.assertEqual(result.verdict, "RESEARCH_MORE")
        self.assertEqual(result.next_step, "RETURN_TO_RESEARCHER")
        self.assertFalse(result.product_creation_allowed)
        self.assertEqual(result.ai_calls, 0)

    def test_missing_required_field_rejects(self):
        value = packet()
        del value["research_id"]
        self.assertEqual(simulate_handoff(value).verdict, "REJECT")

    def test_invalid_json_shape_rejects(self):
        self.assertEqual(simulate_handoff([]).verdict, "REJECT")

    def test_approval_flag_cannot_be_set(self):
        for flag in ("market_validated", "human_go_approved", "commercial_release_allowed"):
            value = packet()
            value[flag] = True
            self.assertEqual(simulate_handoff(value).verdict, "REJECT")

    def test_unsupported_sales_claim_not_passed(self):
        value = packet()
        value["observations"] = [observation("500 verified sales")]
        value["gaps"] = []
        value["recommended_next_step"] = "SEND_TO_VALIDATOR"
        self.assertEqual(simulate_handoff(value).verdict, "RESEARCH_MORE")

    def test_unverified_direct_claim_rejected_by_contract(self):
        value = packet()
        value["observations"] = [observation(verification="UNVERIFIED_LEAD")]
        self.assertTrue(any("direct claim" in issue for issue in validate_research_packet(value)))

    def test_missing_all_source_inspection_never_passes(self):
        value = packet()
        value["observations"] = [observation()]
        value["gaps"] = []
        value["recommended_next_step"] = "SEND_TO_VALIDATOR"
        self.assertEqual(simulate_handoff(value).verdict, "RESEARCH_MORE")

    def test_contradiction_blocks(self):
        value = packet()
        value["observations"] = [observation()]
        value["gaps"] = []
        value["contradictions"] = ["Comparable free kit solves same problem"]
        self.assertEqual(simulate_handoff(value).verdict, "RESEARCH_MORE")

    def test_input_not_mutated(self):
        value = packet()
        original = copy.deepcopy(value)
        simulate_handoff(value)
        self.assertEqual(value, original)


if __name__ == "__main__":
    unittest.main()
