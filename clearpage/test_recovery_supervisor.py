"""Crash-state matrix for the conservative recovery supervisor."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from mission_control_bridge import HandoffError, MissionControlBridge
from native_workers import research_step, schedule
from recovery_supervisor import finalize_verified, plan, reconciliation_case
from runtime_controls import RunLedger
from test_handoff import packet
from test_native_workers import NativeTaskFixture


class RecoverySupervisorTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.ledger = RunLedger(Path(directory.name) / 'runs.sqlite')
        self.api = NativeTaskFixture()
        self.bridge = MissionControlBridge(self.api)
        self.run_id = 'fixture-potluck-001'

    def start(self):
        return schedule(self.bridge, self.ledger, run_id=self.run_id, question='Check demand')

    def test_missing_run_fails_closed(self):
        with self.assertRaises(HandoffError):
            plan(self.bridge, self.ledger, run_id=self.run_id)

    def test_assigned_research_is_operator_only_and_read_only(self):
        self.start()
        before = len(self.api.calls)
        result = plan(self.bridge, self.ledger, run_id=self.run_id)
        self.assertEqual(result['decision'], 'OPERATOR_MAY_START_RESEARCH_WORKER')
        self.assertEqual(result['remote_writes'], 0)
        self.assertTrue(all(method == 'GET' for method, _, _ in self.api.calls[before:]))
        with self.assertRaises(HandoffError):
            finalize_verified(self.bridge, self.ledger, run_id=self.run_id, operator_approved=True)

    def test_assigned_validator_is_operator_only(self):
        research_id = self.start()
        research_step(self.bridge, research_task_id=research_id, run_id=self.run_id,
                      packet=packet(), ledger=self.ledger)
        self.assertEqual(plan(self.bridge, self.ledger, run_id=self.run_id)['decision'],
                         'OPERATOR_MAY_START_VALIDATOR_WORKER')

    def test_claimed_task_requires_manual_reconciliation(self):
        research_id = self.start()
        self.api.tasks[research_id]['status'] = 'in_progress'
        self.assertEqual(plan(self.bridge, self.ledger, run_id=self.run_id)['decision'],
                         'MANUAL_RECONCILIATION_REQUIRED')

    def test_active_and_expired_local_lease_cannot_be_retried(self):
        self.start()
        self.ledger.acquire_lease(self.run_id, 'research', 'worker', ttl_seconds=3600)
        self.assertEqual(plan(self.bridge, self.ledger, run_id=self.run_id)['decision'],
                         'WAIT_NO_RETRY')
        # Deterministically advance the local clock without sleeping.
        self.assertEqual(self.ledger.lease_state(self.run_id, 'research', now_ms=10**16),
                         'EXPIRED_NEEDS_REVIEW')
        with patch('runtime_controls.time.time', return_value=10**13):
            self.assertEqual(plan(self.bridge, self.ledger, run_id=self.run_id)['decision'],
                             'MANUAL_RECONCILIATION_REQUIRED')

    def test_verified_finalization_requires_explicit_approval_and_is_idempotent(self):
        research_id = self.start()
        validator_id = research_step(self.bridge, research_task_id=research_id,
                                     run_id=self.run_id, packet=packet(), ledger=self.ledger)
        from native_workers import validation_step
        with patch.object(self.ledger, 'finish', side_effect=RuntimeError('crash')):
            with self.assertRaises(RuntimeError):
                validation_step(self.bridge, self.ledger, validation_task_id=validator_id,
                                research_task_id=research_id, run_id=self.run_id)
        before = len(self.api.tasks)
        self.assertEqual(plan(self.bridge, self.ledger, run_id=self.run_id)['decision'],
                         'VERIFIED_FINALIZATION_AVAILABLE')
        with self.assertRaises(HandoffError):
            finalize_verified(self.bridge, self.ledger, run_id=self.run_id)
        result = finalize_verified(self.bridge, self.ledger, run_id=self.run_id, operator_approved=True)
        self.assertEqual(result['decision'], 'FINALIZED_LOCALLY')
        self.assertEqual(result['ai_calls'], 0)
        self.assertEqual(self.ledger.status(self.run_id), 'COMPLETE')
        self.assertEqual(len(self.api.tasks), before)
        self.assertEqual(plan(self.bridge, self.ledger, run_id=self.run_id)['decision'], 'DONE_NO_REPLAY')
        with self.assertRaises(HandoffError):
            finalize_verified(self.bridge, self.ledger, run_id=self.run_id, operator_approved=True)

    def test_tampered_submitted_validator_cannot_finalize(self):
        research_id = self.start()
        validator_id = research_step(self.bridge, research_task_id=research_id,
                                     run_id=self.run_id, packet=packet(), ledger=self.ledger)
        self.api.tasks[validator_id]['status'] = 'review'
        self.api.tasks[validator_id]['resolution'] = json.dumps({'verdict': 'APPROVE'})
        self.assertEqual(plan(self.bridge, self.ledger, run_id=self.run_id)['decision'],
                         'MANUAL_RECONCILIATION_REQUIRED')
        with self.assertRaises(HandoffError):
            finalize_verified(self.bridge, self.ledger, run_id=self.run_id, operator_approved=True)

    def test_reconciliation_case_is_stable_read_only_and_minimal(self):
        research_id = self.start()
        self.api.tasks[research_id]['status'] = 'in_progress'
        before = len(self.api.calls)
        first = reconciliation_case(self.bridge, self.ledger, run_id=self.run_id)
        second = reconciliation_case(self.bridge, self.ledger, run_id=self.run_id)
        self.assertEqual(first, second)
        self.assertEqual(first['decision'], 'MANUAL_RECONCILIATION_REQUIRED')
        self.assertEqual(first['tasks'][0]['status'], 'in_progress')
        self.assertEqual(first['tasks'][0]['task_id'], research_id)
        self.assertEqual(len(first['case_sha256']), 64)
        self.assertNotIn('resolution', json.dumps(first))
        self.assertTrue(all(method == 'GET' for method, _, _ in self.api.calls[before:]))

    def test_reconciliation_case_refuses_wrong_remote_identity(self):
        research_id = self.start()
        self.api.tasks[research_id]['metadata']['clearpage_run_id'] = 'other-run'
        with self.assertRaises(HandoffError):
            reconciliation_case(self.bridge, self.ledger, run_id=self.run_id)


if __name__ == '__main__':
    unittest.main()
