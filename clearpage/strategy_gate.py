"""Deterministic, fail-closed gate before Product Strategist drafting.

The signing key must remain in a trusted server component, never in an agent
prompt, tool result, task record, browser, or git. No model/network calls.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from datetime import datetime, timezone
from typing import Any, Callable

from handoff import validate_research_packet


def _timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def _signed_bytes(approval: dict[str, Any]) -> bytes:
    return json.dumps(approval, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")


def review_strategy_gate(
    packet: Any,
    validation: Any,
    approval: Any,
    signature: Any,
    *,
    verification_key: bytes,
    now: datetime,
    is_revoked: Callable[[str], bool],
    load_trusted_validation: Callable[[str], dict[str, Any]],
) -> dict[str, Any]:
    """Inspect authenticated GO and linked PASS; grant drafting eligibility only.

    Approval signing belongs to a separate trusted human-auth service.
    In particular, this gate does NOT permit production or commercial release.
    """
    reasons: list[str] = []
    if validate_research_packet(packet):
        reasons.append("INVALID_RESEARCH_PACKET")
    if not isinstance(validation, dict):
        reasons.append("MISSING_VALIDATION")
        validation = {}
    if not callable(load_trusted_validation) or not validation.get("validation_id"):
        reasons.append("VALIDATION_PROVENANCE_UNAVAILABLE")
    else:
        try:
            verified_validation = load_trusted_validation(validation["validation_id"])
            if not isinstance(verified_validation, dict) or verified_validation != validation:
                reasons.append("VALIDATION_PROVENANCE_MISMATCH")
        except Exception:
            reasons.append("VALIDATION_PROVENANCE_UNAVAILABLE")
    if not isinstance(packet, dict):
        packet = {}
    if (validation.get("schema_version") != "0.1" or
            validation.get("validator_role") != "market_validator" or
            validation.get("input_schema_version") != "0.1" or
            validation.get("input_integrity") != "VALID" or
            validation.get("verdict") != "PASS" or
            validation.get("recommended_next_step") != "HUMAN_REVIEW" or
            any(validation.get(flag) is not False for flag in
                ("market_validated", "human_go_approved", "commercial_release_allowed")) or
            not isinstance(validation.get("validation_id"), str) or
            not validation.get("validation_id") or
            validation.get("research_id") != packet.get("research_id")):
        reasons.append("VALIDATOR_PASS_NOT_ESTABLISHED")
    if (not isinstance(approval, dict) or
            set(approval) != {"approval_id", "research_id", "validation_id", "approver_id", "decision", "issued_at_utc", "expires_at_utc"} or
            any(not isinstance(approval.get(key), str) or not approval[key] for key in approval)):
        reasons.append("INVALID_GO_RECORD")
        approval = {}
    if (approval.get("decision") != "GO" or
            approval.get("research_id") != packet.get("research_id") or
            approval.get("validation_id") != validation.get("validation_id")):
        reasons.append("GO_NOT_LINKED_TO_EVIDENCE")
    issued, expires = _timestamp(approval.get("issued_at_utc")), _timestamp(approval.get("expires_at_utc"))
    if (not isinstance(now, datetime) or now.tzinfo is None or
            issued is None or expires is None or
            not (issued <= now.astimezone(timezone.utc) < expires)):
        reasons.append("GO_NOT_CURRENT")
    if (not isinstance(verification_key, bytes) or len(verification_key) < 32 or
            not isinstance(signature, str) or len(signature) != 64 or
            not approval):
        reasons.append("GO_SIGNATURE_INVALID")
    else:
        expected = hmac.new(verification_key, _signed_bytes(approval), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature, expected):
            reasons.append("GO_SIGNATURE_INVALID")
    if not callable(is_revoked):
        reasons.append("REVOCATION_CHECK_UNAVAILABLE")
    elif approval.get("approval_id"):
        try:
            revocation_status = is_revoked(approval["approval_id"])
            if revocation_status is not False:
                reasons.append("GO_REVOKED")
        except Exception:
            reasons.append("REVOCATION_CHECK_UNAVAILABLE")
    if not reasons and (not isinstance(validation.get("checks"), list) or len(validation["checks"]) < 1):
        reasons.append("VALIDATION_CHECKS_MISSING")
    return {
        "decision": "ELIGIBLE_FOR_STRATEGY_DRAFT" if not reasons else "BLOCKED",
        "blocked_reasons": sorted(set(reasons)),
        "research_id": packet.get("research_id"),
        "validation_id": validation.get("validation_id"),
        "human_go_record_id": approval.get("approval_id") if not reasons else None,
        "production_authorized": False,
        "commercial_release_allowed": False,
    }
