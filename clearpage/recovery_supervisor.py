"""Conservative, fixture-only supervisor for one Mission Control run.

Inspects remote tasks and the durable local ledger. No task is reclaimed,
reset, retried or rescheduled automatically. Only verified local finalization
can be explicitly requested by an operator.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from pathlib import Path

from mission_control_bridge import HandoffError, MissionControlBridge, make_http_transport
from native_workers import (inspect_interrupted_run, recover_submitted_validation,
                            verify_submitted_validation, _task)
from runtime_controls import RunLedger


def plan(bridge: MissionControlBridge, ledger: RunLedger, *, run_id: str) -> dict:
    """A read-only decision for a single run; never reclaims an expired lease."""
    observation = inspect_interrupted_run(bridge, ledger, run_id=run_id)
    action = observation['action']
    if action == 'NO_REPLAY':
        decision = 'DONE_NO_REPLAY'
    elif action == 'WAIT_ACTIVE_WORKER':
        decision = 'WAIT_NO_RETRY'
    elif action == 'RESEARCH_READY':
        decision = 'OPERATOR_MAY_START_RESEARCH_WORKER'
    elif action == 'VALIDATION_READY':
        decision = 'OPERATOR_MAY_START_VALIDATOR_WORKER'
    elif action == 'MANUAL_RECONCILIATION':
        # Inspection can only establish a partially completed transition.
        # A submitted Validator report is special: it can be independently
        # verified without claiming, replaying, or creating a native task.
        try:
            verify_submitted_validation(bridge, ledger, run_id=run_id)
        except HandoffError:
            decision = 'MANUAL_RECONCILIATION_REQUIRED'
        else:
            decision = 'VERIFIED_FINALIZATION_AVAILABLE'
    else:
        raise HandoffError('Unknown restart inspection action')
    return {'run_id': run_id, 'decision': decision, 'observation': observation,
            'remote_writes': 0, 'ai_calls': 0}


def finalize_verified(bridge: MissionControlBridge, ledger: RunLedger, *, run_id: str,
                      operator_approved: bool = False) -> dict:
    """Only the explicit operator path may finalize an independently proved result."""
    if not operator_approved:
        raise HandoffError('Operator approval required for verified finalization')
    decision = plan(bridge, ledger, run_id=run_id)
    if decision['decision'] != 'VERIFIED_FINALIZATION_AVAILABLE':
        raise HandoffError('Current run is not eligible for verified finalization')
    result = recover_submitted_validation(bridge, ledger, run_id=run_id)
    return {'run_id': run_id, 'decision': 'FINALIZED_LOCALLY', 'result': result,
            'remote_writes': 0, 'ai_calls': 0}


def reconciliation_case(bridge: MissionControlBridge, ledger: RunLedger, *, run_id: str) -> dict:
    """Produce a stable, read-only operator dossier without copying task contents.

    Only bound native task IDs are inspected. Unbound remote creations cannot
    be discovered safely; those cases remain blocked for human investigation.
    """
    decision = plan(bridge, ledger, run_id=run_id)
    research_id, validation_id = ledger.task_ids(run_id)
    tasks: list[dict] = []
    for stage, task_id, agent in (
        ('research', research_id, bridge.researcher),
        ('validation', validation_id, bridge.validator),
    ):
        if task_id is None:
            continue
        task = _task(bridge, task_id, role=agent, run_id=run_id, stage=stage)
        tasks.append({'stage': stage, 'task_id': task_id, 'status': task['status'],
                      'local_lease': ledger.lease_state(run_id, stage)})
    document = {'run_id': run_id, 'ledger_status': ledger.status(run_id),
                'decision': decision['decision'], 'tasks': tasks,
                'operator_instruction': ('Do not reset or reassign a claimed task. Confirm the worker has '
                                         'stopped, inspect the native task activity and fence expiry, '
                                         'then reconcile through the administrator workflow. Never '
                                         'reuse the old run ID for a new attempt.'),
                'remote_writes': 0, 'ai_calls': 0}
    digest = hashlib.sha256(json.dumps(document, sort_keys=True).encode()).hexdigest()
    return {**document, 'case_sha256': digest}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description='ClearPage conservative recovery inspection')
    parser.add_argument('--run-id', required=True)
    parser.add_argument('--ledger', type=Path, required=True)
    parser.add_argument('--finalize-verified', action='store_true',
                        help='Explicitly approve local-only completion of a verified submitted report')
    parser.add_argument('--watch', action='store_true', help='Read-only periodic monitoring')
    parser.add_argument('--case', action='store_true', help='Print an operator reconciliation dossier')
    parser.add_argument('--poll-seconds', type=float, default=10)
    parser.add_argument('--max-checks', type=int, default=30)
    args = parser.parse_args(argv)
    if args.watch and args.finalize_verified:
        parser.error('Monitoring cannot finalize or modify tasks')
    if args.case and (args.watch or args.finalize_verified):
        parser.error('Reconciliation dossier must be read-only and single-shot')
    if not 1 <= args.poll_seconds <= 300 or not 1 <= args.max_checks <= 10000:
        parser.error('Invalid monitoring bounds')
    if not args.ledger.is_file():
        parser.error('Existing local SQLite ledger required')
    key = os.environ.get('MC_API_KEY')
    if not key:
        parser.error('MC_API_KEY environment variable required')
    try:
        transport = make_http_transport(os.environ.get('MC_BASE_URL', 'http://127.0.0.1:3000'),
                                        key, allow_live_writes=True)
        def read_only(method, path, body):
            if method != 'GET' or body is not None:
                raise HandoffError('Recovery supervisor cannot mutate native tasks')
            return transport(method, path, body)
        bridge = MissionControlBridge(read_only)
        ledger = RunLedger(args.ledger)
        previous = None
        for check in range(args.max_checks if args.watch else 1):
            output = (finalize_verified(bridge, ledger, run_id=args.run_id, operator_approved=True)
                      if args.finalize_verified else reconciliation_case(bridge, ledger, run_id=args.run_id)
                      if args.case else plan(bridge, ledger, run_id=args.run_id))
            if output['decision'] != previous:
                print(json.dumps(output, sort_keys=True), flush=True)
                previous = output['decision']
            if not args.watch or output['decision'] == 'DONE_NO_REPLAY':
                break
            if check + 1 < args.max_checks:
                time.sleep(args.poll_seconds)
        return 0
    except HandoffError as error:
        print(json.dumps({'status': 'FAILED_NEEDS_REVIEW', 'error': str(error)}), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
