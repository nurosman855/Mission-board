"""Two independently invocable, zero-cost Mission Control worker steps.

The coordinator schedules; Researcher and Validator explicitly claim their own
native tasks. This is an offline evidence simulation, NOT live AI validation.
Every role must run under separately scoped credentials in production.
"""

from __future__ import annotations

import json

from handoff import simulate_handoff, validate_research_packet
from mission_control_bridge import HandoffError, MissionControlBridge
from runtime_controls import RunLedger


def _task(bridge: MissionControlBridge, task_id: int, *, role: str, run_id: str, stage: str) -> dict:
    if type(task_id) is not int or task_id <= 0:
        raise HandoffError("Invalid native task ID")
    response = bridge.transport("GET", f"/api/tasks/{task_id}", None)
    task = response.get("task")
    if (not isinstance(task, dict) or task.get("id") != task_id or
            task.get("assigned_to") != role or not isinstance(task.get("metadata"), dict) or
            task["metadata"].get("clearpage_run_id") != run_id or
            task["metadata"].get("stage") != stage or
            task["metadata"].get("simulation_only") is not True):
        raise HandoffError("Task identity or metadata mismatch")
    return task


def schedule(bridge: MissionControlBridge, ledger: RunLedger, *, run_id: str, question: str) -> int:
    if (not isinstance(run_id, str) or not run_id or len(run_id) > 128 or
            not isinstance(question, str) or not question.strip() or len(question) > 500):
        raise HandoffError("Invalid scheduling parameters")
    ledger.reserve(run_id)
    try:
        task_id = bridge._create("[SIM] Research: " + question, bridge.researcher,
                              "Independent Researcher worker must claim and submit fixture evidence.",
                              {"clearpage_run_id": run_id, "stage": "research", "simulation_only": True})
        ledger.checkpoint(run_id, research_task_id=task_id)
        return task_id
    except BaseException:
        ledger.finish(run_id, None)
        raise


def research_step(bridge: MissionControlBridge, *, research_task_id: int, run_id: str, packet: dict,
                  ledger: RunLedger | None = None) -> int:
    """Researcher worker: claim its own task, submit packet, schedule Validator."""
    issues = validate_research_packet(packet)
    if issues or packet.get("research_id") != run_id:
        raise HandoffError("Invalid Research Packet or run identifier")
    task = _task(bridge, research_task_id, role=bridge.researcher, run_id=run_id, stage="research")
    if task.get("status") != "assigned":
        raise HandoffError("Research task not available for first claim")
    bridge._claim(bridge.researcher, research_task_id)
    bridge._submit_for_review(research_task_id, {"packet": packet, "simulation_only": True})
    validator_id = bridge._create("[SIM] Validate Research Packet", bridge.validator,
                          f"Inspect immutable Research Packet from task {research_task_id}.",
                          {"clearpage_run_id": run_id, "stage": "validation", "simulation_only": True,
                           "research_task_id": research_task_id})
    if ledger is not None:
        ledger.checkpoint(run_id, research_task_id=research_task_id, validation_task_id=validator_id)
    return validator_id


def validation_step(bridge: MissionControlBridge, ledger: RunLedger, *,
                    validation_task_id: int, research_task_id: int, run_id: str) -> dict:
    """Validator worker: independently retrieve Researcher's submitted packet."""
    if ledger.status(run_id) != "RESERVED":
        raise HandoffError("Run not reserved or already finalized")
    recorded_research, recorded_validation = ledger.task_ids(run_id)
    if ((recorded_research is not None and recorded_research != research_task_id) or
            (recorded_validation is not None and recorded_validation != validation_task_id)):
        raise HandoffError("Native task IDs disagree with durable checkpoint")
    validation = _task(bridge, validation_task_id, role=bridge.validator, run_id=run_id,
                       stage="validation")
    if (validation.get("status") != "assigned" or
            validation["metadata"].get("research_task_id") != research_task_id):
        raise HandoffError("Validation task not assigned to source task")
    research = _task(bridge, research_task_id, role=bridge.researcher, run_id=run_id,
                     stage="research")
    if research.get("status") != "review":
        raise HandoffError("Source Researcher task is not in review")
    try:
        resolution = json.loads(research["resolution"])
        packet = resolution["packet"]
    except (KeyError, ValueError, TypeError):
        raise HandoffError("Source Researcher resolution missing or malformed") from None
    if (resolution.get("simulation_only") is not True or
            validate_research_packet(packet) or packet.get("research_id") != run_id):
        raise HandoffError("Invalid or unauthorized Researcher resolution")
    bridge._claim(bridge.validator, validation_task_id)
    verdict = simulate_handoff(packet)
    report = {"verdict": verdict.verdict, "next_step": verdict.next_step,
              "issues": list(verdict.issues), "simulation_only": True,
              "product_creation_allowed": False, "ai_calls": 0}
    bridge._submit_for_review(validation_task_id, report)
    result = {"research_task_id": research_task_id, "validation_task_id": validation_task_id,
              "validation_report": report, "mission_control_status": "review"}
    ledger.finish(run_id, result)
    return result


def inspect_interrupted_run(bridge: MissionControlBridge, ledger: RunLedger, *, run_id: str) -> dict:
    """Read-only recovery diagnosis. Never release claims or replay remote writes."""
    state = ledger.status(run_id)
    if state is None:
        raise HandoffError("Unknown run ID")
    research_id, validator_id = ledger.task_ids(run_id)
    if state != "RESERVED":
        return {"run_id": run_id, "state": state, "action": "NO_REPLAY"}
    if research_id is None:
        return {"run_id": run_id, "state": state, "action": "MANUAL_RECONCILIATION",
                "reason": "Remote research creation may have succeeded before checkpoint"}
    research = _task(bridge, research_id, role=bridge.researcher, run_id=run_id, stage="research")
    if research["status"] == "assigned" and validator_id is None:
        action = "RESEARCH_READY"
    elif research["status"] == "review" and validator_id is not None:
        validation = _task(bridge, validator_id, role=bridge.validator, run_id=run_id, stage="validation")
        if validation["metadata"].get("research_task_id") != research_id:
            raise HandoffError("Recovered validation task has different source")
        action = "VALIDATION_READY" if validation["status"] == "assigned" else "MANUAL_RECONCILIATION"
    else:
        action = "MANUAL_RECONCILIATION"
    return {"run_id": run_id, "state": state, "research_task_id": research_id,
            "validation_task_id": validator_id, "action": action}


def recover_submitted_validation(bridge: MissionControlBridge, ledger: RunLedger, *, run_id: str) -> dict:
    """Finalize a fully submitted Validator task after a local ledger crash.

    Never claims tasks, retries work, or trusts a report without recomputing it
    from the Researcher's stored source packet.
    """
    if ledger.status(run_id) != "RESERVED":
        raise HandoffError("Recovery requires an unfinished reserved run")
    research_id, validator_id = ledger.task_ids(run_id)
    if research_id is None or validator_id is None:
        raise HandoffError("Both task IDs must have durable checkpoints")
    research = _task(bridge, research_id, role=bridge.researcher, run_id=run_id, stage="research")
    validation = _task(bridge, validator_id, role=bridge.validator, run_id=run_id, stage="validation")
    if research.get("status") != "review" or validation.get("status") != "review" or validation["metadata"].get("research_task_id") != research_id:
        raise HandoffError("Both linked tasks must already be submitted for review")
    try:
        source = json.loads(research["resolution"])
        actual = json.loads(validation["resolution"])
        packet = source["packet"]
    except (KeyError, TypeError, ValueError):
        raise HandoffError("Submitted task result unavailable") from None
    if (not isinstance(source, dict) or source.get("simulation_only") is not True or
            validate_research_packet(packet) or packet.get("research_id") != run_id):
        raise HandoffError("Research source cannot be independently verified")
    verdict = simulate_handoff(packet)
    expected = {"verdict": verdict.verdict, "next_step": verdict.next_step,
                "issues": list(verdict.issues), "simulation_only": True,
                "product_creation_allowed": False, "ai_calls": 0}
    if actual != expected:
        raise HandoffError("Validator result does not match deterministic source verification")
    result = {"research_task_id": research_id, "validation_task_id": validator_id,
              "validation_report": expected, "mission_control_status": "review"}
    ledger.finish(run_id, result)
    return result
