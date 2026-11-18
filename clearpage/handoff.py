"""Zero-cost deterministic Researcher -> Validator simulation.

This module does not invoke AI models, external APIs, or Mission Control.
It simulates handoff decisions and makes no claim to verify remote sources.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


EVIDENCE_STATUS = {"UNVERIFIED", "PARTIALLY_VERIFIED", "SOURCE_BACKED_NEEDS_VALIDATION"}
EVIDENCE_CLASS = {"DIRECT_OBSERVATION", "DIRECT_CUSTOMER_FEEDBACK", "ESTIMATE", "INFERENCE", "HYPOTHESIS"}
VERIFICATION = {"INSPECTED_SOURCE", "UNVERIFIED_LEAD", "NOT_APPLICABLE"}
APPROVAL_FLAGS = ("market_validated", "human_go_approved", "commercial_release_allowed")
REQUIRED_PACKET = {
    "schema_version": str, "research_id": str, "research_question": str,
    "target_customer": str, "customer_problem_hypothesis": str,
    "observed_at_utc": str, "evidence_status": str,
    "observations": list, "alternatives": list, "gaps": list,
    "contradictions": list, "limitations": list,
    "recommended_next_step": str,
    "market_validated": bool, "human_go_approved": bool,
    "commercial_release_allowed": bool,
}
REQUIRED_EVIDENCE = {
    "claim": str, "class": str, "source_type": str,
    "source_observed_at_utc": str, "supporting_detail": str,
    "verification": str, "caveat": str,
}


@dataclass(frozen=True)
class Handoff:
    verdict: str
    next_step: str
    issues: tuple[str, ...]
    product_creation_allowed: bool = False
    ai_calls: int = 0


def validate_research_packet(packet: Any) -> tuple[str, ...]:
    """Check the v0.1 contract; fail closed for malformed payloads."""
    if not isinstance(packet, dict):
        return ("packet must be an object",)
    issues: list[str] = []
    for field, expected in REQUIRED_PACKET.items():
        if field not in packet:
            issues.append(f"missing {field}")
        elif type(packet[field]) is not expected:
            issues.append(f"{field} must be {expected.__name__}")
    if issues:
        return tuple(issues)
    if packet["schema_version"] != "0.1":
        issues.append("unsupported schema_version")
    if packet["evidence_status"] not in EVIDENCE_STATUS:
        issues.append("invalid evidence_status")
    if packet["recommended_next_step"] not in {"RESEARCH_MORE", "SEND_TO_VALIDATOR"}:
        issues.append("invalid recommended_next_step")
    for field in APPROVAL_FLAGS:
        if packet[field] is not False:
            issues.append(f"{field} must be false")
    for field in ("gaps", "contradictions", "limitations"):
        if any(not isinstance(item, str) for item in packet[field]):
            issues.append(f"{field} must contain strings")
    if not packet["observations"] and (packet["recommended_next_step"] != "RESEARCH_MORE" or not packet["gaps"]):
        issues.append("empty observations require RESEARCH_MORE and gaps")
    for collection in ("observations", "alternatives"):
        for index, record in enumerate(packet[collection]):
            location = f"{collection}[{index}]"
            if not isinstance(record, dict):
                issues.append(f"{location} must be object")
                continue
            for key, kind in REQUIRED_EVIDENCE.items():
                if key not in record or type(record[key]) is not kind:
                    issues.append(f"{location}.{key} missing or wrong type")
            if "source_url" not in record or record["source_url"] is not None and not (isinstance(record["source_url"], str) and record["source_url"].startswith("https://")):
                issues.append(f"{location}.source_url invalid")
            if record.get("class") not in EVIDENCE_CLASS:
                issues.append(f"{location}.class invalid")
            if record.get("verification") not in VERIFICATION:
                issues.append(f"{location}.verification invalid")
            if record.get("verification") == "INSPECTED_SOURCE" and not record.get("source_url"):
                issues.append(f"{location} inspected claim lacks URL")
            if record.get("class") in {"DIRECT_OBSERVATION", "DIRECT_CUSTOMER_FEEDBACK"} and record.get("verification") != "INSPECTED_SOURCE":
                issues.append(f"{location} direct claim has no inspected source")
    return tuple(issues)


def simulate_handoff(packet: Any) -> Handoff:
    """Conservative, offline simulation—not an autonomous market verdict."""
    structural = validate_research_packet(packet)
    if structural:
        return Handoff("REJECT", "STOP", structural)
    if packet["gaps"] or packet["contradictions"] or not packet["observations"]:
        return Handoff("RESEARCH_MORE", "RETURN_TO_RESEARCHER", ("unresolved gaps, contradictions, or no observations",))
    for record in packet["observations"]:
        if record["verification"] != "INSPECTED_SOURCE":
            return Handoff("RESEARCH_MORE", "RETURN_TO_RESEARCHER", ("material source not independently inspectable",))
        if any(term in record["claim"].lower() for term in ("verified sales", "confirmed purchases")):
            return Handoff("RESEARCH_MORE", "RETURN_TO_RESEARCHER", ("sales claim needs independent transactional verification",))
    # A simulation cannot inspect remote sources; it must not issue PASS.
    return Handoff("RESEARCH_MORE", "RETURN_TO_RESEARCHER", ("independent source inspection not performed",))


def run_fixture(path: Path) -> dict[str, Any]:
    packet = json.loads(path.read_text(encoding="utf-8"))
    decision = simulate_handoff(packet)
    return {
        "research_id": packet.get("research_id") if isinstance(packet, dict) else None,
        "verdict": decision.verdict,
        "next_step": decision.next_step,
        "issues": list(decision.issues),
        "product_creation_allowed": decision.product_creation_allowed,
        "ai_calls": decision.ai_calls,
        "simulation_only": True,
    }
