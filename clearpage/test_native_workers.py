"""Separate native worker stages with strict IDs, status and no-model proof."""

import copy
import json
import tempfile
import unittest
from pathlib import Path

from mission_control_bridge import HandoffError, MissionControlBridge
from native_workers import research_step, schedule, validation_step
from runtime_controls import RunLedger
from test_handoff import packet
from test_mission_control_bridge import FakeMissionControl


class NativeTaskFixture(FakeMissionControl):
    def __call__(self, method, path, body):
        if method == "GET" and path.startswith("/api/tasks/") and not path.startswith("/api/tasks/queue"):
            self.calls.append((method, path, body))
            return {"task": copy.deepcopy(self.tasks[int(path.rsplit("/", 1)[1])])}
        return super().__call__(method, path, body)


class NativeWorkersTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.ledger = RunLedger(Path(self.directory.name) / "worker_runs.sqlite")
        self.api = NativeTaskFixture()
        self.bridge = MissionControlBridge(self.api)
        self.run_id = "fixture-potluck-001"

    def start(self):
        return schedule(self.bridge, self.ledger, run_id=self.run_id, question="Party-planner market?")

    def research(self, task_id):
        return research_step(self.bridge, research_task_id=task_id, run_id=self.run_id, packet=packet())

    def test_three_independent_stages_in_order_and_duplicate_denied(self):
        task_id = self.start()
        self.assertEqual(len(self.api.tasks), 1)
        self.assertEqual(self.api.tasks[task_id]["status"], "assigned")
        validator_id = self.research(task_id)
        self.assertEqual([t["status"] for t in self.api.tasks.values()], ["review", "assigned"])
        self.assertEqual(len(self.api.tasks), 2)
        result = validation_step(self.bridge, self.ledger, validation_task_id=validator_id,
                                 research_task_id=task_id, run_id=self.run_id)
        self.assertEqual(result["validation_report"]["verdict"], "RESEARCH_MORE")
        self.assertEqual(result["validation_report"]["ai_calls"], 0)
        self.assertEqual(self.ledger.status(self.run_id), "COMPLETE")
        self.assertEqual([t["status"] for t in self.api.tasks.values()], ["review", "review"])
        with self.assertRaises(HandoffError):
            self.research(task_id)
        with self.assertRaises(HandoffError):
            validation_step(self.bridge, self.ledger, validation_task_id=validator_id,
                            research_task_id=task_id, run_id=self.run_id)
        self.assertEqual(len(self.api.tasks), 2)

    def test_invalid_research_packet_creates_no_validator_task(self):
        task_id = self.start()
        bad = packet()
        bad["market_validated"] = True
        with self.assertRaises(HandoffError):
            research_step(self.bridge, research_task_id=task_id, run_id=self.run_id, packet=bad)
        self.assertEqual(self.api.tasks[task_id]["status"], "assigned")
        self.assertEqual(len(self.api.tasks), 1)

    def test_wrong_task_id_fails_before_claim(self):
        task_id = self.start()
        with self.assertRaises(HandoffError):
            research_step(self.bridge, research_task_id=task_id, run_id="another-run", packet=packet())
        self.assertEqual(self.api.tasks[task_id]["status"], "assigned")

    def test_validation_fails_if_research_not_reviewed(self):
        task_id = self.start()
        validator_id = self.bridge._create("[SIM] Fake validation", self.bridge.validator, "test",
                                           {"clearpage_run_id": self.run_id, "stage": "validation",
                                            "simulation_only": True, "research_task_id": task_id})
        with self.assertRaises(HandoffError):
            validation_step(self.bridge, self.ledger, validation_task_id=validator_id,
                            research_task_id=task_id, run_id=self.run_id)
        self.assertEqual(self.api.tasks[validator_id]["status"], "assigned")

    def test_validator_reads_original_record_not_model_claim(self):
        task_id = self.start()
        validator_id = self.research(task_id)
        self.api.tasks[task_id]["resolution"] = json.dumps({"simulation_only": True,
                                                            "packet": {"research_id": self.run_id,
                                                                       "human_go_approved": True}})
        with self.assertRaises(HandoffError):
            validation_step(self.bridge, self.ledger, validation_task_id=validator_id,
                            research_task_id=task_id, run_id=self.run_id)
        self.assertEqual(self.api.tasks[validator_id]["status"], "assigned")

    def test_duplicate_schedule_rejected_and_no_extra_task(self):
        self.start()
        with self.assertRaises(HandoffError):
            self.start()
        self.assertEqual(len(self.api.tasks), 1)


if __name__ == "__main__":
    unittest.main()
