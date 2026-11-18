"""Mission Control REST task bridge for the Researcher -> Validator handoff.

No API calls are made by importing this module. Use an injected transport in
tests; live transport requires deliberate configuration and a separate launch.
This bridge coordinates existing agents; it does not execute LLMs or approve work.
"""

from __future__ import annotations

import json
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from typing import Any, Callable

from handoff import simulate_handoff, validate_research_packet


Transport = Callable[[str, str, dict[str, Any] | None], dict[str, Any]]


class HandoffError(RuntimeError):
    pass


def make_http_transport(base_url: str, api_key: str, *, allow_live_writes: bool = False) -> Transport:
    """Explicit opt-in to authenticated Mission Control REST; never called by tests.

    Live use can create tasks and consume queue assignments. Require an operator
    to affirm the environment; never persist the token or send to other hosts.
    """
    if not allow_live_writes:
        raise HandoffError("Live Mission Control writes are disabled by default")
    if not api_key or not base_url.startswith(("http://127.0.0.1:", "http://localhost:", "https://")):
        raise HandoffError("Explicit URL and API key required")
    root = base_url.rstrip("/")

    def transport(method: str, path: str, body: dict[str, Any] | None) -> dict[str, Any]:
        if method not in {"GET", "POST", "PUT"} or not path.startswith("/api/tasks") or "//" in path:
            raise HandoffError("Disallowed Mission Control endpoint")
        payload = json.dumps(body).encode("utf-8") if body is not None else None
        request = Request(root + path, method=method, data=payload,
                          headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"})
        try:
            with urlopen(request, timeout=15) as response:
                data = json.load(response)
        except (HTTPError, URLError, TimeoutError, ValueError) as error:
            raise HandoffError(f"Mission Control transport failure: {type(error).__name__}") from None
        if not isinstance(data, dict):
            raise HandoffError("Invalid Mission Control response")
        return data

    return transport


class MissionControlBridge:
    def __init__(self, transport: Transport, researcher: str = "clearpage-researcher", validator: str = "clearpage-validator"):
        self.transport = transport
        self.researcher = researcher
        self.validator = validator

    def _create(self, title: str, assigned_to: str, description: str, metadata: dict[str, Any]) -> int:
        response = self.transport("POST", "/api/tasks", {
            "title": title, "description": description, "assigned_to": assigned_to,
            "priority": "medium", "metadata": metadata,
        })
        task = response.get("task")
        if not isinstance(task, dict) or type(task.get("id")) is not int or task.get("assigned_to") != assigned_to:
            raise HandoffError("Mission Control did not confirm task creation and assignment")
        return task["id"]

    def _claim(self, name: str, task_id: int) -> None:
        from urllib.parse import quote

        response = self.transport("GET", f"/api/tasks/queue?agent={quote(name, safe='')}&task_id={task_id}", None)
        task = response.get("task")
        if not isinstance(task, dict) or task.get("id") != task_id or task.get("assigned_to") != name or task.get("status") != "in_progress":
            raise HandoffError("Queue returned a different task or an unclaimed task")

    def _submit_for_review(self, task_id: int, resolution: dict[str, Any]) -> None:
        response = self.transport("PUT", f"/api/tasks/{task_id}", {
            "status": "review", "resolution": json.dumps(resolution, sort_keys=True),
        })
        if response.get("task", {}).get("status") != "review":
            raise HandoffError("Mission Control did not confirm review status")

    def run_fixture(self, packet: dict[str, Any], run_id: str) -> dict[str, Any]:
        """Exercise actual API shapes with existing agents and fixture data.

        Call only from a controlled test harness with fake transport. The method
        is not idempotent on a live service; production needs a run ledger.
        """
        if not run_id or not isinstance(packet, dict):
            raise HandoffError("run_id and Research Packet are required")
        if packet.get("research_id") != run_id:
            raise HandoffError("run_id must match packet research_id")
        # Validate before any task is created, to prevent unsafe mutations.
        issues = validate_research_packet(packet)
        if issues:
            raise HandoffError("Invalid packet: " + "; ".join(issues))

        metadata = {"clearpage_run_id": run_id, "simulation_only": True, "stage": "research"}
        research_id = self._create("[SIM] Research: " + packet["research_question"], self.researcher,
                                   "Preconstructed offline research fixture; do not perform web/API calls.", metadata)
        self._claim(self.researcher, research_id)
        self._submit_for_review(research_id, {"packet": packet, "simulation_only": True})

        validation_id = self._create("[SIM] Validate Research Packet", self.validator,
                                     f"Audit fixture from research task {research_id}; do not use external tools.",
                                     {"clearpage_run_id": run_id, "simulation_only": True,
                                      "stage": "validation", "research_task_id": research_id})
        self._claim(self.validator, validation_id)
        verdict = simulate_handoff(packet)
        report = {"verdict": verdict.verdict, "next_step": verdict.next_step,
                  "issues": list(verdict.issues), "product_creation_allowed": False,
                  "ai_calls": 0, "simulation_only": True}
        self._submit_for_review(validation_id, report)
        return {"research_task_id": research_id, "validation_task_id": validation_id,
                "validation_report": report, "mission_control_status": "review"}
