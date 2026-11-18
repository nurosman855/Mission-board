"""Single-call, explicitly supervised hypothesis research with native task handoff.

No provider/model calls or Mission Control writes happen at import time.
Without independently supplied source-inspection tools, this runner can only
produce an UNVERIFIED hypothesis, never source-backed market evidence.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from handoff import validate_research_packet
from mission_control_bridge import HandoffError, MissionControlBridge
from runtime_controls import BudgetedModelCalls, RunLedger, agent_instructions


def run_supervised_research(
    *, question: str, customer: str, run_id: str,
    bridge: MissionControlBridge, ledger: RunLedger, repo_root: Path,
    model: BudgetedModelCalls, allow_model_call: bool = False,
    max_output_tokens: int = 300,
) -> dict[str, Any]:
    """Reserve run, spend at most one configured call, and submit unverified packet.

    Provider-side hard limits are mandatory before passing allow_model_call=True
    with a billable provider. Do not use with an unattended or shared budget.
    """
    if not allow_model_call:
        raise HandoffError("Supervised model call requires explicit opt-in")
    if (not isinstance(question, str) or not question.strip() or len(question) > 500 or
            not isinstance(customer, str) or not customer.strip() or len(customer) > 250 or
            not isinstance(run_id, str) or not run_id.strip() or len(run_id) > 128 or
            type(max_output_tokens) is not int or not 1 <= max_output_tokens <= 1000):
        raise HandoffError("Invalid supervised research task parameters")
    if model.max_calls != 1 or model.calls != 0:
        raise HandoffError("Researcher requires an unused one-call model budget")
    instructions = agent_instructions(repo_root, "researcher")

    ledger.reserve(run_id)
    result = None
    try:
        # Keep user-supplied question as untrusted task data, never as permissions.
        prompt = (
            instructions + "\n\n# Controlled model execution\n"
            "Propose a research hypothesis only. You cannot browse or verify sources. "
            "Return a JSON object with keys hypothesis (string), gaps (nonempty array of strings). "
            "Do not invent evidence, reviews, numbers, URLs, sales, or claim inspected sources.\n"
            + json.dumps({"research_question": question, "target_customer": customer}, ensure_ascii=True)
        )
        proposal = model.invoke(prompt=prompt, max_output_tokens=max_output_tokens)
        if (not isinstance(proposal, dict) or not isinstance(proposal.get("hypothesis"), str) or
                not proposal["hypothesis"].strip()):
            raise HandoffError("Model output lacks hypothesis")
        if (not isinstance(proposal.get("gaps"), list) or not proposal["gaps"] or
                any(not isinstance(g, str) or not g.strip() for g in proposal["gaps"])):
            raise HandoffError("Model output lacks actionable research gaps")
        if len(proposal["hypothesis"]) > 1200 or sum(map(len, proposal["gaps"])) > 4000:
            raise HandoffError("Model output exceeds field limits")
        packet = {
            "schema_version": "0.1", "research_id": run_id,
            "research_question": question, "target_customer": customer,
            "customer_problem_hypothesis": proposal["hypothesis"],
            "observed_at_utc": datetime.now(timezone.utc).isoformat(),
            "evidence_status": "UNVERIFIED", "observations": [], "alternatives": [],
            "gaps": proposal["gaps"], "contradictions": [],
            "limitations": ["No independent source inspection or marketplace metrics performed"],
            "recommended_next_step": "RESEARCH_MORE", "market_validated": False,
            "human_go_approved": False, "commercial_release_allowed": False,
        }
        issues = validate_research_packet(packet)
        if issues:
            raise HandoffError("Generated packet failed validation: " + "; ".join(issues))
        handoff = bridge.run_fixture(packet, run_id)
        if handoff["validation_report"].get("verdict") != "RESEARCH_MORE":
            raise HandoffError("Uninspected research must not be passed")
        result = {"packet": packet, "handoff": handoff, "model_calls": model.calls,
                  "estimated_cost_reserved_usd": model.reserved_cost_usd}
        return result
    finally:
        ledger.finish(run_id, result)
