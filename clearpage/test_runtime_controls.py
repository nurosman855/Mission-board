"""Fail-closed, standard-library-only tests; no model or network calls."""

import math
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from mission_control_bridge import HandoffError, MissionControlBridge
from runtime_controls import (AGENT_ROLES, NATIVE_AGENT_ROLES, BudgetedModelCalls, RunLedger, agent_instructions,
                              make_agent_http_transport, register_native_agents, run_once)
from test_handoff import packet
from test_mission_control_bridge import FakeMissionControl


ROOT = Path(__file__).resolve().parent.parent


class FakeAgentAPI:
    def __init__(self, corrupt=False, wrong_role=False):
        self.agents = {}
        self.souls = {}
        self.corrupt = corrupt
        self.wrong_role = wrong_role

    def __call__(self, method, path, body):
        if method == "POST" and path == "/api/agents/register":
            if body["role"] not in NATIVE_AGENT_ROLES:
                raise HandoffError("Native agent API rejects role")
            name = body["name"]
            if name not in self.agents:
                self.agents[name] = {"name": name, "id": len(self.agents) + 1, "role": body["role"]}
            agent = dict(self.agents[name])
            if self.wrong_role:
                agent["role"] = "coder"
            return {"agent": agent}
        if method == "PUT" and path.endswith("/soul"):
            agent_id = int(path.split("/")[3])
            self.souls[agent_id] = body["soul_content"]
            return {"soul_content": self.souls[agent_id]}
        if method == "GET" and path.endswith("/soul"):
            agent_id = int(path.split("/")[3])
            return {"soul_content": "bad data" if self.corrupt else self.souls[agent_id]}
        raise AssertionError(f"unexpected request {method} {path}")


class InstructionTests(unittest.TestCase):
    def test_loads_each_soul_contract_and_skill(self):
        for role in ("researcher", "validator", "strategist", "pdf_creator"):
            text = agent_instructions(ROOT, role)
            self.assertIn("SOUL.md", text)
            self.assertIn("OUTPUT_CONTRACT.md", text)
            self.assertIn("SKILL.md", text)
            self.assertIn("approv", text.lower())

    def test_rejects_unknown_role(self):
        with self.assertRaises(HandoffError):
            agent_instructions(ROOT, "publisher")

    def test_registers_and_verifies_four_native_souls(self):
        api = FakeAgentAPI()
        result = register_native_agents(api, ROOT)
        self.assertEqual(set(result), {"researcher", "validator", "strategist", "pdf_creator"})
        self.assertEqual(api.agents["clearpage-validator"]["role"], "reviewer")
        self.assertIn("audit-market-evidence", api.souls[result["validator"]])
        self.assertEqual(api.agents["clearpage-strategist"]["role"], "assistant")
        self.assertIn("convert-evidence-to-product-brief", api.souls[result["strategist"]])
        self.assertEqual(api.agents["clearpage-pdf-creator"]["role"], "agent")
        self.assertIn("build-verified-printables", api.souls[result["pdf_creator"]])

    def test_rejects_soul_readback_mismatch(self):
        with self.assertRaises(HandoffError):
            register_native_agents(FakeAgentAPI(corrupt=True), ROOT)

    def test_native_role_configuration_matches_backend_allowed_roles(self):
        import re
        source = (ROOT / "src/app/api/agents/register/route.ts").read_text(encoding="utf-8")
        role_array = re.search(r"const VALID_ROLES\s*=\s*\[([^]]+)\]", source)
        self.assertIsNotNone(role_array, "Mission Control role API changed")
        backend_roles = set(re.findall(r"'([^']+)'", role_array.group(1)))
        self.assertEqual(NATIVE_AGENT_ROLES, backend_roles)
        self.assertTrue(all(native_role in backend_roles for _, native_role in AGENT_ROLES.values()))

    def test_rejects_wrong_role_readback(self):
        with self.assertRaises(HandoffError):
            register_native_agents(FakeAgentAPI(wrong_role=True), ROOT)

    def test_preflight_rejects_unknown_role_without_remote_writes(self):
        from unittest.mock import patch
        api = FakeAgentAPI()
        with patch.dict(AGENT_ROLES, {"strategist": ("clearpage-strategist", "general")}):
            with self.assertRaises(HandoffError):
                register_native_agents(api, ROOT)
        self.assertEqual(api.agents, {})

    def test_live_agent_transport_default_denied(self):
        with self.assertRaises(HandoffError):
            make_agent_http_transport("http://localhost:3000", "test-key")
        transport = make_agent_http_transport("http://localhost:3000", "test-key", allow_live_writes=True)
        with self.assertRaises(HandoffError):
            transport("POST", "/api/tasks", {})


class LedgerTests(unittest.TestCase):
    def test_worker_lease_exclusive_across_connections_and_fails_closed_after_expiry(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'leases.sqlite'
            first, second = RunLedger(path), RunLedger(path)
            first.reserve('lease-test')
            token = first.acquire_lease('lease-test', 'research', 'worker-a', ttl_seconds=5, now_ms=1000)
            self.assertEqual(second.lease_state('lease-test', 'research', now_ms=5999), 'ACTIVE')
            with self.assertRaises(HandoffError):
                second.acquire_lease('lease-test', 'research', 'worker-b', ttl_seconds=5, now_ms=2000)
            first.heartbeat_lease('lease-test', 'research', 'worker-a', token, ttl_seconds=5, now_ms=4000)
            self.assertEqual(second.lease_state('lease-test', 'research', now_ms=8999), 'ACTIVE')
            with self.assertRaises(HandoffError):
                first.heartbeat_lease('lease-test', 'research', 'worker-a', token, now_ms=9000)
            self.assertEqual(second.lease_state('lease-test', 'research', now_ms=9000), 'EXPIRED_NEEDS_REVIEW')
            with self.assertRaises(HandoffError):
                second.acquire_lease('lease-test', 'research', 'worker-b', now_ms=10000)
            with self.assertRaises(HandoffError):
                first.release_lease('lease-test', 'research', 'worker-a', token, now_ms=10000)

    def test_worker_lease_wrong_owner_or_token_cannot_renew_or_release(self):
        with tempfile.TemporaryDirectory() as directory:
            ledger = RunLedger(Path(directory) / 'leases.sqlite')
            ledger.reserve('lease-test')
            token = ledger.acquire_lease('lease-test', 'validation', 'worker-a', now_ms=1000)
            with self.assertRaises(HandoffError):
                ledger.heartbeat_lease('lease-test', 'validation', 'worker-b', token, now_ms=2000)
            with self.assertRaises(HandoffError):
                ledger.release_lease('lease-test', 'validation', 'worker-a', 'wrong', now_ms=2000)
            self.assertEqual(ledger.lease_state('lease-test', 'validation', now_ms=2000), 'ACTIVE')
            ledger.release_lease('lease-test', 'validation', 'worker-a', token, now_ms=2000)
            self.assertEqual(ledger.lease_state('lease-test', 'validation', now_ms=2000), 'UNCLAIMED')

    def test_repeat_and_restart_does_not_create_more_tasks(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "runs.sqlite"
            api = FakeMissionControl()
            run_id = "fixture-potluck-001"
            first = run_once(MissionControlBridge(api), RunLedger(path), packet(), run_id)
            self.assertEqual(first["validation_report"]["verdict"], "RESEARCH_MORE")
            self.assertEqual(len(api.tasks), 2)
            with self.assertRaises(HandoffError):
                run_once(MissionControlBridge(api), RunLedger(path), packet(), run_id)
            self.assertEqual(len(api.tasks), 2)
            self.assertEqual(RunLedger(path).status(run_id), "COMPLETE")

    def test_failed_run_not_retried_automatically(self):
        with tempfile.TemporaryDirectory() as directory:
            ledger = RunLedger(Path(directory) / "runs.sqlite")
            api = FakeMissionControl()
            def fail_transport(method, path, body):
                if method == "GET":
                    raise HandoffError("queue unavailable")
                return api(method, path, body)
            with self.assertRaises(HandoffError):
                run_once(MissionControlBridge(fail_transport), ledger, packet(), "fixture-potluck-001")
            self.assertEqual(ledger.status("fixture-potluck-001"), "FAILED_NEEDS_REVIEW")
            with self.assertRaises(HandoffError):
                run_once(MissionControlBridge(api), ledger, packet(), "fixture-potluck-001")
            self.assertEqual(len(api.tasks), 1)

    def test_concurrent_reservations_allow_one_winner(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "runs.sqlite"
            def attempt(_):
                try:
                    RunLedger(path).reserve("unique")
                    return True
                except HandoffError:
                    return False
            with ThreadPoolExecutor(max_workers=6) as pool:
                results = list(pool.map(attempt, range(6)))
            self.assertEqual(results.count(True), 1)
            self.assertEqual(results.count(False), 5)

    def test_invalid_packet_cannot_claim_run(self):
        with tempfile.TemporaryDirectory() as directory:
            ledger = RunLedger(Path(directory) / "runs.sqlite")
            value = packet()
            value["research_id"] = "wrong"
            with self.assertRaises(HandoffError):
                run_once(MissionControlBridge(FakeMissionControl()), ledger, value, "fixture-potluck-001")
            self.assertIsNone(ledger.status("fixture-potluck-001"))


class BudgetTests(unittest.TestCase):
    def test_no_model_calls_by_default(self):
        invoked = []
        runner = BudgetedModelCalls(lambda **kwargs: invoked.append(kwargs))
        with self.assertRaises(HandoffError):
            runner.invoke(prompt="Research", max_output_tokens=100)
        self.assertEqual(invoked, [])

    def test_reserved_max_cost_and_call_limits(self):
        invoked = []
        runner = BudgetedModelCalls(lambda **kwargs: invoked.append(kwargs),
                                    max_calls=2, max_cost_usd=0.02, per_call_worst_case_usd=0.01,
                                    max_prompt_chars=40, max_output_tokens_per_call=100)
        runner.invoke(prompt="First", max_output_tokens=100)
        runner.invoke(prompt="Second", max_output_tokens=100)
        with self.assertRaises(HandoffError):
            runner.invoke(prompt="Third", max_output_tokens=100)
        self.assertEqual(len(invoked), 2)
        self.assertAlmostEqual(runner.reserved_cost_usd, 0.02)

    def test_failed_call_still_consumes_reservation(self):
        def fail(**kwargs):
            raise RuntimeError("provider failed")
        runner = BudgetedModelCalls(fail, max_calls=1, max_cost_usd=1, per_call_worst_case_usd=1,
                                    max_prompt_chars=40, max_output_tokens_per_call=20)
        with self.assertRaises(RuntimeError):
            runner.invoke(prompt="test", max_output_tokens=5)
        self.assertEqual(runner.calls, 1)
        with self.assertRaises(HandoffError):
            runner.invoke(prompt="again", max_output_tokens=5)

    def test_nan_and_infinite_budgets_rejected(self):
        for bad in (math.nan, math.inf, -1):
            with self.assertRaises(ValueError):
                BudgetedModelCalls(lambda **kwargs: None, max_calls=1,
                                   max_cost_usd=bad, per_call_worst_case_usd=0.01)

    def test_prompt_and_token_limits_prevent_calls(self):
        invoked = []
        runner = BudgetedModelCalls(lambda **kwargs: invoked.append(kwargs),
                                    max_calls=1, max_cost_usd=0.05, per_call_worst_case_usd=0.02,
                                    max_prompt_chars=10, max_output_tokens_per_call=8)
        for prompt, tokens in (("prompt-too-long", 3), ("ok", 100)):
            with self.assertRaises(HandoffError):
                runner.invoke(prompt=prompt, max_output_tokens=tokens)
        self.assertEqual(invoked, [])
        self.assertEqual(runner.calls, 0)


if __name__ == "__main__":
    unittest.main()
