"""No-cost researcher execution tests against fake Mission Control transports."""

import json
import tempfile
import unittest
from pathlib import Path

from mission_control_bridge import HandoffError, MissionControlBridge
from openai_research_adapter import OpenAIResearchProposalAdapter
from runtime_controls import BudgetedModelCalls, RunLedger
from supervised_researcher import run_supervised_research
from test_mission_control_bridge import FakeMissionControl

ROOT = Path(__file__).resolve().parent.parent

def bounded(call, *, calls=1):
    return BudgetedModelCalls(call, max_calls=calls, max_cost_usd=0.02,
                              per_call_worst_case_usd=0.02, max_prompt_chars=20000,
                              max_output_tokens_per_call=300)


class SupervisedResearcherTests(unittest.TestCase):
    def test_default_denies_both_model_and_task_creation(self):
        invoked = []
        api = FakeMissionControl()
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(HandoffError):
                run_supervised_research(question="Buyer problem?", customer="organizers",
                                        run_id="dry-1", repo_root=ROOT, ledger=RunLedger(Path(folder) / "ledger.sqlite"),
                                        model=bounded(lambda **kwargs: invoked.append(kwargs)),
                                        bridge=MissionControlBridge(api))
        self.assertEqual(invoked, [])
        self.assertEqual(api.tasks, {})

    def test_single_proposal_creates_two_review_tasks_without_approval(self):
        api = FakeMissionControl()
        captured = []
        def propose(**kwargs):
            captured.append(kwargs)
            return {"hypothesis": "Guests struggle coordinating dishes",
                    "gaps": ["Independent customer evidence is missing"]}
        model = bounded(propose)
        with tempfile.TemporaryDirectory() as folder:
            ledger = RunLedger(Path(folder) / "ledger.sqlite")
            kwargs = dict(question="Should we test a potluck planner?", customer="party organizers",
                          run_id="proposal-1", repo_root=ROOT, ledger=ledger, model=model,
                          bridge=MissionControlBridge(api), allow_model_call=True)
            result = run_supervised_research(**kwargs)
            self.assertEqual(result["packet"]["observations"], [])
            self.assertEqual(result["packet"]["evidence_status"], "UNVERIFIED")
            self.assertEqual(result["handoff"]["validation_report"]["verdict"], "RESEARCH_MORE")
            self.assertEqual(result["model_calls"], 1)
            self.assertIn("evidence-first-market-research", captured[0]["prompt"])
            self.assertIn("Researcher — SOUL", captured[0]["prompt"])
            self.assertEqual(result["estimated_cost_reserved_usd"], 0.02)
            self.assertEqual(len(api.tasks), 2)
            with self.assertRaises(HandoffError):
                run_supervised_research(**kwargs)
            self.assertEqual(len(api.tasks), 2)
            self.assertEqual(ledger.status("proposal-1"), "COMPLETE")

    def test_model_fabricated_approval_or_claims_are_discarded(self):
        model = bounded(lambda **kwargs: {"hypothesis": "Unverified possibility",
                                           "gaps": ["Need a buyer source"],
                                           "market_validated": True, "observations": [{"claim": "100 sales"}]})
        with tempfile.TemporaryDirectory() as folder:
            result = run_supervised_research(question="test", customer="customer", run_id="proposal-2",
                                             repo_root=ROOT,
                                             bridge=MissionControlBridge(FakeMissionControl()),
                                             ledger=RunLedger(Path(folder) / "ledger.sqlite"),
                                             model=model, allow_model_call=True)
        self.assertIs(result["packet"]["market_validated"], False)
        self.assertEqual(result["packet"]["observations"], [])

    def test_model_failure_consumes_one_run_and_stops(self):
        def broken(**kwargs):
            raise RuntimeError("provider timeout")
        api = FakeMissionControl()
        with tempfile.TemporaryDirectory() as folder:
            ledger = RunLedger(Path(folder) / "ledger.sqlite")
            with self.assertRaises(RuntimeError):
                run_supervised_research(question="test", customer="customer", run_id="failed-1",
                                         repo_root=ROOT,
                                         bridge=MissionControlBridge(api), ledger=ledger,
                                         model=bounded(broken), allow_model_call=True)
            self.assertEqual(ledger.status("failed-1"), "FAILED_NEEDS_REVIEW")
            self.assertEqual(len(api.tasks), 0)

    def test_budget_disabled_even_if_runner_opted_in(self):
        invoked = []
        with tempfile.TemporaryDirectory() as folder:
            ledger = RunLedger(Path(folder) / "ledger.sqlite")
            with self.assertRaises(HandoffError):
                run_supervised_research(question="test", customer="customer", run_id="no-budget",
                                         repo_root=ROOT,
                                         bridge=MissionControlBridge(FakeMissionControl()), ledger=ledger,
                                         model=BudgetedModelCalls(lambda **kwargs: invoked.append(kwargs)),
                                         allow_model_call=True)
            self.assertIsNone(ledger.status("no-budget"))  # rejected before reservation
        self.assertEqual(invoked, [])


class OpenAIAdapterTests(unittest.TestCase):
    def test_wire_payload_and_structured_response(self):
        received = []
        def send(payload, key):
            received.append((payload, key))
            return {"status": "completed", "output": [{"content": [
                {"type": "output_text", "text": json.dumps({"hypothesis": "Possible pain", "gaps": ["Need source"]})}]}]}
        adapter = OpenAIResearchProposalAdapter(api_key="fake-key", model="test-model", send=send)
        result = adapter(prompt="Propose JSON", max_output_tokens=120)
        self.assertEqual(result["gaps"], ["Need source"])
        payload = received[0][0]
        self.assertEqual(payload["store"], False)
        self.assertEqual(payload["max_output_tokens"], 120)
        self.assertEqual(payload["text"]["format"]["strict"], True)
        self.assertNotIn("tools", payload)

    def test_provider_refusal_fails_closed(self):
        adapter = OpenAIResearchProposalAdapter(api_key="fake-key", model="test-model", send=lambda *_: {
            "status": "completed", "output": [{"content": [{"type": "refusal", "refusal": "no"}]}]})
        with self.assertRaises(HandoffError):
            adapter(prompt="test", max_output_tokens=100)

    def test_incomplete_provider_response_fails_closed(self):
        adapter = OpenAIResearchProposalAdapter(api_key="fake-key", model="test-model", send=lambda *_: {
            "status": "incomplete", "output": []})
        with self.assertRaises(HandoffError):
            adapter(prompt="test", max_output_tokens=100)


if __name__ == "__main__":
    unittest.main()
