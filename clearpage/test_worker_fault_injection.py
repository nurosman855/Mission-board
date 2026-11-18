"""Crash and network interruption matrix for fixture-only native workers."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from mission_control_bridge import HandoffError, MissionControlBridge
from native_workers import (research_with_lease, schedule, task_heartbeat,
                            validation_with_lease)
from recovery_supervisor import plan
from runtime_controls import RunLedger
from test_handoff import packet
from test_native_workers import NativeTaskFixture


class FaultInjectionTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.path = Path(temp.name) / 'ledger.sqlite'
        self.ledger = RunLedger(self.path)
        self.api = NativeTaskFixture()
        self.bridge = MissionControlBridge(self.api)
        self.run_id = 'fixture-potluck-001'

    def start(self):
        return schedule(self.bridge, self.ledger, run_id=self.run_id, question='Demand?')

    def test_server_claim_succeeds_then_connection_drops(self):
        task_id = self.start()
        with patch.object(self.bridge, '_submit_for_review', side_effect=ConnectionError('offline')):
            with self.assertRaises(ConnectionError):
                research_with_lease(self.bridge, self.ledger, run_id=self.run_id,
                                    research_task_id=task_id, packet=packet(), owner='research-os')
        self.assertEqual(self.api.tasks[task_id]['status'], 'in_progress')
        self.assertEqual(plan(self.bridge, RunLedger(self.path), run_id=self.run_id)['decision'],
                         'MANUAL_RECONCILIATION_REQUIRED')
        with self.assertRaises(HandoffError):
            research_with_lease(self.bridge, RunLedger(self.path), run_id=self.run_id,
                                research_task_id=task_id, packet=packet(), owner='other-os')
        self.assertEqual(len(self.api.tasks), 1)

    def test_crash_after_research_review_before_validator_creation(self):
        task_id = self.start()
        original = self.bridge._create
        def interrupted(title, assigned_to, description, metadata):
            if metadata.get('stage') == 'validation':
                raise ConnectionError('network down before response')
            return original(title, assigned_to, description, metadata)
        with patch.object(self.bridge, '_create', side_effect=interrupted):
            with self.assertRaises(ConnectionError):
                research_with_lease(self.bridge, self.ledger, run_id=self.run_id,
                                    research_task_id=task_id, packet=packet(), owner='research-os')
        self.assertEqual(self.api.tasks[task_id]['status'], 'review')
        self.assertEqual(self.ledger.task_ids(self.run_id), (task_id, None))
        self.assertEqual(plan(self.bridge, self.ledger, run_id=self.run_id)['decision'],
                         'MANUAL_RECONCILIATION_REQUIRED')

    def test_validator_created_before_local_checkpoint_is_ambiguous(self):
        task_id = self.start()
        with patch.object(self.ledger, 'checkpoint', side_effect=OSError('disk offline')):
            with self.assertRaises(OSError):
                research_with_lease(self.bridge, self.ledger, run_id=self.run_id,
                                    research_task_id=task_id, packet=packet(), owner='research-os')
        self.assertEqual(len(self.api.tasks), 2)
        self.assertEqual(self.ledger.task_ids(self.run_id), (task_id, None))
        self.assertEqual(plan(self.bridge, self.ledger, run_id=self.run_id)['decision'],
                         'MANUAL_RECONCILIATION_REQUIRED')

    def test_heartbeat_failure_prevents_submission(self):
        task_id = self.start()
        self.api.tasks[task_id]['status'] = 'in_progress'
        with patch.object(self.bridge, 'renew_task_lease', side_effect=HandoffError('expired')):
            with self.assertRaises(HandoffError):
                with task_heartbeat(self.bridge, task_id, 'f' * 64) as assert_current:
                    assert_current()
        self.assertEqual(self.api.tasks[task_id]['status'], 'in_progress')

    def test_validator_network_failure_after_claim_is_not_replayed(self):
        research_id = self.start()
        validator_id = research_with_lease(self.bridge, self.ledger, run_id=self.run_id,
                                           research_task_id=research_id, packet=packet(), owner='research-os')
        with patch.object(self.bridge, '_submit_for_review', side_effect=TimeoutError('unconfirmed reply')):
            with self.assertRaises(TimeoutError):
                validation_with_lease(self.bridge, self.ledger, run_id=self.run_id,
                                      research_task_id=research_id, validation_task_id=validator_id,
                                      owner='validator-os')
        self.assertEqual(plan(self.bridge, RunLedger(self.path), run_id=self.run_id)['decision'],
                         'MANUAL_RECONCILIATION_REQUIRED')
        with self.assertRaises(HandoffError):
            validation_with_lease(self.bridge, RunLedger(self.path), run_id=self.run_id,
                                  research_task_id=research_id, validation_task_id=validator_id,
                                  owner='different-worker')


if __name__ == '__main__':
    unittest.main()
