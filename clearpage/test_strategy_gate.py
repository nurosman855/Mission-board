"""Offline tests of independent Validation PASS + signed human GO gating."""

import copy
import hashlib
import hmac
import unittest
from datetime import datetime, timezone

from strategy_gate import _signed_bytes, review_strategy_gate
from test_handoff import packet


KEY = b"isolated-test-key-with-32-plus-bytes-long"
NOW = datetime(2026, 11, 18, 12, tzinfo=timezone.utc)


def inputs():
    research = packet()
    validation = {
        "schema_version": "0.1", "validator_role": "market_validator",
        "input_schema_version": "0.1", "input_integrity": "VALID",
        "validation_id": "val-1", "research_id": research["research_id"],
        "verdict": "PASS", "recommended_next_step": "HUMAN_REVIEW",
        "market_validated": False, "human_go_approved": False,
        "commercial_release_allowed": False, "checks": [{"category": "PROVENANCE", "status": "PASS"}],
    }
    approval = {
        "approval_id": "go-1", "research_id": research["research_id"],
        "validation_id": "val-1", "approver_id": "trusted-human-1",
        "decision": "GO", "issued_at_utc": "2026-11-18T11:00:00Z",
        "expires_at_utc": "2026-11-19T11:00:00Z",
    }
    return research, validation, approval


def assess(research, validation, approval, *, key=KEY, signature=None, trusted=None, revoked=None):
    if signature is None:
        signature = hmac.new(KEY, _signed_bytes(approval), hashlib.sha256).hexdigest()
    if trusted is None:
        trusted = lambda _: copy.deepcopy(validation)
    if revoked is None:
        revoked = lambda _: False
    return review_strategy_gate(research, validation, approval, signature,
                                verification_key=key, now=NOW, is_revoked=revoked,
                                load_trusted_validation=trusted)


class StrategyGateTests(unittest.TestCase):
    def test_signed_linked_go_allows_draft_only(self):
        r = assess(*inputs())
        self.assertEqual(r["decision"], "ELIGIBLE_FOR_STRATEGY_DRAFT")
        self.assertFalse(r["production_authorized"])
        self.assertFalse(r["commercial_release_allowed"])

    def test_missing_verdict_blocks(self):
        research, validation, approval = inputs()
        validation["verdict"] = "RESEARCH_MORE"
        self.assertEqual(assess(research, validation, approval)["decision"], "BLOCKED")

    def test_unsigned_or_tampered_go_blocks(self):
        research, validation, approval = inputs()
        approval["approver_id"] = "attacker"
        result = assess(research, validation, approval, signature="0" * 64)
        self.assertIn("GO_SIGNATURE_INVALID", result["blocked_reasons"])

    def test_wrong_ids_block_even_with_valid_signature(self):
        research, validation, approval = inputs()
        approval["validation_id"] = "other-validation"
        self.assertEqual(assess(research, validation, approval)["decision"], "BLOCKED")

    def test_expired_or_revoked_go_blocks(self):
        research, validation, approval = inputs()
        approval["expires_at_utc"] = "2026-11-18T11:00:00Z"
        self.assertIn("GO_NOT_CURRENT", assess(research, validation, approval)["blocked_reasons"])
        research, validation, approval = inputs()
        self.assertIn("GO_REVOKED", assess(research, validation, approval,
                                            revoked=lambda _: True)["blocked_reasons"])

    def test_trusted_validator_record_required(self):
        research, validation, approval = inputs()
        self.assertIn("VALIDATION_PROVENANCE_MISMATCH",
                      assess(research, validation, approval, trusted=lambda _: {"verdict": "REJECT"})["blocked_reasons"])
        self.assertIn("VALIDATION_PROVENANCE_UNAVAILABLE",
                      assess(research, validation, approval, trusted=lambda _: 1 / 0)["blocked_reasons"])

    def test_invalid_research_packet_blocks(self):
        research, validation, approval = inputs()
        research["human_go_approved"] = True
        self.assertIn("INVALID_RESEARCH_PACKET", assess(research, validation, approval)["blocked_reasons"])

    def test_missing_revocation_check_blocks(self):
        research, validation, approval = inputs()
        r = assess(research, validation, approval, revoked=lambda _: 1 / 0)
        self.assertIn("REVOCATION_CHECK_UNAVAILABLE", r["blocked_reasons"])
        self.assertIn("GO_REVOKED", assess(research, validation, approval,
                                            revoked=lambda _: None)["blocked_reasons"])


if __name__ == "__main__":
    unittest.main()
