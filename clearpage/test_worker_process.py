"""Worker stages can run through separate entry points without paid models."""

import tempfile
import unittest
from pathlib import Path

from mission_control_bridge import HandoffError, MissionControlBridge
from runtime_controls import RunLedger
from test_handoff import packet
from test_native_workers import NativeTaskFixture
from worker_process import ScopedWorkerBridge, execute, resolve_packet_path


class WorkerProcessTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / 'runs.sqlite'
        self.transport = NativeTaskFixture()
        self.run_id = 'fixture-potluck-001'

    def test_independent_entry_points_share_durable_checkpoints(self):
        coordinator = MissionControlBridge(self.transport)
        result = execute('schedule', coordinator, RunLedger(self.path), run_id=self.run_id,
                         question='Does anyone need this?')
        self.assertIsInstance(result['research_task_id'], int)
        result = execute('research', coordinator, RunLedger(self.path), run_id=self.run_id,
                         packet=packet(), owner='research-process')
        self.assertIsInstance(result['validation_task_id'], int)
        result = execute('validation', coordinator, RunLedger(self.path), run_id=self.run_id,
                         owner='validator-process')
        self.assertEqual(result['validation_report']['verdict'], 'RESEARCH_MORE')
        self.assertEqual(RunLedger(self.path).status(self.run_id), 'COMPLETE')
        self.assertEqual(len(self.transport.tasks), 2)
        with self.assertRaises(HandoffError):
            execute('validation', coordinator, RunLedger(self.path), run_id=self.run_id,
                    owner='validator-process')

    def test_scoped_bridge_rejects_missing_server_token(self):
        bridge = ScopedWorkerBridge(self.transport)
        task_id = MissionControlBridge(self.transport)._create('Test', bridge.researcher, '', {})
        with self.assertRaises(HandoffError):
            bridge._claim(bridge.researcher, task_id)

    def test_worker_refuses_unreserved_run(self):
        with self.assertRaises(HandoffError):
            execute('research', MissionControlBridge(self.transport), RunLedger(self.path),
                    run_id=self.run_id, packet=packet())

    def test_service_fixture_path_is_researcher_only(self):
        env = {'MC_RESEARCH_PACKET_PATH': '/var/lib/clearpage/fixture.json'}
        self.assertEqual(resolve_packet_path('research', None, env), Path(env['MC_RESEARCH_PACKET_PATH']))
        self.assertEqual(resolve_packet_path('research', Path('/explicit.json'), env), Path('/explicit.json'))
        self.assertIsNone(resolve_packet_path('validation', None, env))
        self.assertIsNone(resolve_packet_path('schedule', None, env))


if __name__ == '__main__':
    unittest.main()
