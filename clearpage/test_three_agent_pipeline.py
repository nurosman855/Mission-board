"""Three-agent offline handoff: insufficient evidence must block strategy."""

import unittest
from datetime import datetime, timezone

from mission_control_bridge import MissionControlBridge
from strategy_gate import review_strategy_gate
from test_handoff import packet
from test_mission_control_bridge import FakeMissionControl


class ThreeAgentPipelineTests(unittest.TestCase):
    def test_no_strategist_task_when_validation_requests_more_research(self):
        api = FakeMissionControl()
        research = packet()
        handoff = MissionControlBridge(api).run_fixture(research, research["research_id"])
        self.assertEqual(handoff["validation_report"]["verdict"], "RESEARCH_MORE")

        decision = review_strategy_gate(
            research, handoff["validation_report"], None, None,
            verification_key=b"isolated-test-key-with-32-plus-bytes-long",
            now=datetime(2026, 11, 18, 12, tzinfo=timezone.utc),
            is_revoked=lambda _: False,
            load_trusted_validation=lambda _: handoff["validation_report"],
        )
        self.assertEqual(decision["decision"], "BLOCKED")
        self.assertEqual(len(api.tasks), 2)
        self.assertFalse(decision["production_authorized"])
        self.assertFalse(decision["commercial_release_allowed"])
        self.assertEqual(handoff["validation_report"]["ai_calls"], 0)


if __name__ == "__main__":
    unittest.main()
