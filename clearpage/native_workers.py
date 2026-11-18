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
        return bridge._create("[SIM] Research: " + question, bridge.researcher,
                              "Independent Researcher worker must claim and submit fixture evidence.",
                              {"clearpage_run_id": run_id, "stage": "research", "simulation_only": True})
    except BaseException:
        ledger.finish(run_id, None)
        raise


def research_step(bridge: MissionControlBridge, *, research_task_id: int, run_id: str, packet: dict) -> int:
    """Researcher worker: claim its own task, submit packet, schedule Validator."""
    issues = validate_research_packet(packet)
    if issues or packet.get("research_id") != run_id:
        raise HandoffError("Invalid Research Packet or run identifier")
    task = _task(bridge, research_task_id, role=bridge.researcher, run_id=run_id, stage="research")
    if task.get("status") != "assigned":
        raise HandoffError("Research task not available for first claim")
    bridge._claim(bridge.researcher, research_task_id)
    bridge._submit_for_review(research_task_id, {"packet": packet, "simulation_only": True})
    return bridge._create("[SIM] Validate Research Packet", bridge.validator,
                          f"Inspect immutable Research Packet from task {research_task_id}.",
                          {"clearpage_run_id": run_id, "stage": "validation", "simulation_only": True,
                           "research_task_id": research_task_id})


def validation_step(bridge: MissionControlBridge, ledger: RunLedger, *,
                    validation_task_id: int, research_task_id: int, run_id: str) -> dict:
    """Validator worker: independently retrieve Researcher's submitted packet."""
    if ledger.status(run_id) != "RESERVED":
        raise HandoffError("Run not reserved or already finalized")
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
