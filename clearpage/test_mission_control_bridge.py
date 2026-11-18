"""Offline contract tests for Mission Control's native task endpoints."""

import unittest
from urllib.parse import parse_qs, urlsplit

from mission_control_bridge import HandoffError, MissionControlBridge, make_http_transport
from test_handoff import packet


class FakeMissionControl:
    """In-memory API shape fixture; does not implement real Mission Control."""

    def __init__(self):
        self.tasks = {}
        self.calls = []

    def __call__(self, method, path, body):
        self.calls.append((method, path, body))
        if method == "POST" and path == "/api/tasks":
            task = {"id": len(self.tasks) + 1, "status": "assigned", **body}
            self.tasks[task["id"]] = task
            return {"task": task.copy()}
        if method == "GET" and path.startswith("/api/tasks/queue?"):
            params = parse_qs(urlsplit(path).query)
            agent = params["agent"][0]
            requested_id = int(params["task_id"][0]) if "task_id" in params else None
            matches = [t for t in self.tasks.values() if t["assigned_to"] == agent and t["status"] == "assigned"
                       and (requested_id is None or t["id"] == requested_id)]
            if not matches:
                return {"task": None, "reason": "no_tasks_available"}
            task = matches[0]
            task["status"] = "in_progress"
            return {"task": task.copy(), "reason": "assigned"}
        if method == "PUT" and path.startswith("/api/tasks/"):
            task_id = int(path.split("/")[-1])
            task = self.tasks[task_id]
            task.update(body)
            return {"task": task.copy()}
        raise AssertionError("Unexpected API call")


class BridgeTests(unittest.TestCase):
    def test_explicit_claim_never_consumes_an_earlier_same_role_task(self):
        mc = FakeMissionControl()
        bridge = MissionControlBridge(mc)
        first = bridge._create("other task", bridge.researcher, "", {"simulation_only": True})
        second = bridge._create("intended task", bridge.researcher, "", {"simulation_only": True})
        bridge._claim(bridge.researcher, second)
        self.assertEqual(mc.tasks[first]["status"], "assigned")
        self.assertEqual(mc.tasks[second]["status"], "in_progress")

    def test_live_transport_requires_opt_in(self):
        with self.assertRaises(HandoffError):
            make_http_transport("http://localhost:3000", "test-key")
        with self.assertRaises(HandoffError):
            make_http_transport("http://example.com", "test-key", allow_live_writes=True)

    def test_two_native_task_cycles_and_fail_closed(self):
        mc = FakeMissionControl()
        bridge = MissionControlBridge(mc)
        result = bridge.run_fixture(packet(), "fixture-potluck-001")
        self.assertEqual(result["validation_report"]["verdict"], "RESEARCH_MORE")
        self.assertFalse(result["validation_report"]["product_creation_allowed"])
        self.assertEqual(result["validation_report"]["ai_calls"], 0)
        self.assertEqual(len(mc.tasks), 2)
        self.assertEqual([t["status"] for t in mc.tasks.values()], ["review", "review"])
        self.assertEqual([t["assigned_to"] for t in mc.tasks.values()],
                         ["clearpage-researcher", "clearpage-validator"])
        self.assertEqual([c[0] for c in mc.calls], ["POST", "GET", "PUT", "POST", "GET", "PUT"])
        self.assertTrue(all(t["metadata"]["simulation_only"] for t in mc.tasks.values()))
        self.assertFalse(any(t["assigned_to"] == "clearpage-strategist" for t in mc.tasks.values()))

    def test_invalid_packet_produces_no_tasks(self):
        value = packet()
        value["human_go_approved"] = True
        mc = FakeMissionControl()
        with self.assertRaises(HandoffError):
            MissionControlBridge(mc).run_fixture(value, "fixture-potluck-001")
        self.assertEqual(mc.calls, [])

    def test_reject_inconsistent_run_id_before_mutation(self):
        mc = FakeMissionControl()
        with self.assertRaises(HandoffError):
            MissionControlBridge(mc).run_fixture(packet(), "wrong-id")
        self.assertEqual(mc.calls, [])

    def test_queue_mismatch_stops_handoff(self):
        mc = FakeMissionControl()
        def broken_transport(method, path, body):
            response = mc(method, path, body)
            if method == "GET":
                return {"task": {"id": 999, "status": "in_progress", "assigned_to": "wrong-agent"}}
            return response
        with self.assertRaises(HandoffError):
            MissionControlBridge(broken_transport).run_fixture(packet(), "fixture-potluck-001")
        self.assertEqual(len(mc.tasks), 1)
        self.assertFalse(any(t["status"] == "review" for t in mc.tasks.values()))


if __name__ == "__main__":
    unittest.main()
