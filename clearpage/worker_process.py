"""Separate-process, fixture-only Mission Control worker entry point.

Requires an explicit opt-in and the appropriate scoped agent API key. The
Researcher and Validator are separate OS processes sharing a durable ledger.
No model calls or remote market research are performed.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

from handoff import validate_research_packet
from mission_control_bridge import HandoffError, MissionControlBridge, make_http_transport
from native_workers import (inspect_interrupted_run, research_with_lease,
                            recover_submitted_validation, schedule, validation_with_lease)
from runtime_controls import RunLedger


class ScopedWorkerBridge(MissionControlBridge):
    """A scoped worker must receive a server-issued fence, never an admin bypass."""

    def _claim(self, name: str, task_id: int) -> str:
        token = super()._claim(name, task_id)
        if not isinstance(token, str) or len(token) != 64:
            raise HandoffError('Scoped worker claim returned no server fencing token')
        return token


def execute(role: str, bridge: MissionControlBridge, ledger: RunLedger, *, run_id: str,
            packet: dict | None = None, question: str | None = None,
            owner: str = 'worker') -> dict:
    """One stage only. Never infer authorization from a role argument alone."""
    if role == 'schedule':
        if not question:
            raise HandoffError('Scheduling requires a question')
        return {'research_task_id': schedule(bridge, ledger, run_id=run_id, question=question)}
    if role == 'inspect':
        return inspect_interrupted_run(bridge, ledger, run_id=run_id)
    if role == 'recover-finalization':
        return recover_submitted_validation(bridge, ledger, run_id=run_id)
    if ledger.status(run_id) != 'RESERVED':
        raise HandoffError('Run must be reserved before a worker can start')
    research_id, validation_id = ledger.task_ids(run_id)
    if role == 'research':
        if research_id is None:
            raise HandoffError('Research task not yet checkpointed')
        if validate_research_packet(packet) or packet.get('research_id') != run_id:
            raise HandoffError('Invalid offline Research Packet')
        return {'validation_task_id': research_with_lease(bridge, ledger, run_id=run_id,
                research_task_id=research_id, packet=packet, owner=owner)}
    if role == 'validation':
        if research_id is None or validation_id is None:
            raise HandoffError('Validation handoff not yet checkpointed')
        return validation_with_lease(bridge, ledger, run_id=run_id,
                research_task_id=research_id, validation_task_id=validation_id, owner=owner)
    raise HandoffError('Unknown worker role')


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description='ClearPage zero-cost, fixture-only worker')
    parser.add_argument('--role', required=True,
                        choices=['schedule', 'research', 'validation', 'inspect', 'recover-finalization'])
    parser.add_argument('--run-id', required=True)
    parser.add_argument('--ledger', type=Path, required=True)
    parser.add_argument('--packet', type=Path, help='Researcher-only offline JSON packet')
    parser.add_argument('--question', help='Coordinator-only research question')
    parser.add_argument('--owner', default='local-worker')
    parser.add_argument('--loop', action='store_true', help='Wait for a checkpointed task, then execute once')
    parser.add_argument('--poll-seconds', type=float, default=2)
    parser.add_argument('--timeout-seconds', type=int, default=180)
    parser.add_argument('--allow-live', action='store_true', help='Authorize local Mission Control API writes')
    args = parser.parse_args(argv)
    if not args.allow_live:
        parser.error('Explicit --allow-live opt-in required')
    if not 0.2 <= args.poll_seconds <= 60 or not 1 <= args.timeout_seconds <= 3600:
        parser.error('Invalid polling limits')
    key, url = os.environ.get('MC_API_KEY'), os.environ.get('MC_BASE_URL', 'http://127.0.0.1:3000')
    if not key:
        parser.error('MC_API_KEY environment variable required')
    if not args.ledger.parent.is_dir():
        parser.error('Ledger parent directory must exist')
    if args.role == 'research' and not args.packet:
        parser.error('Researcher requires an offline --packet')
    if args.role == 'research':
        try:
            packet = json.loads(args.packet.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            parser.error('Unreadable or invalid fixture packet')
    else:
        packet = None
    transport = make_http_transport(url, key, allow_live_writes=True)
    bridge = ScopedWorkerBridge(transport) if args.role in {'research', 'validation'} else MissionControlBridge(transport)
    ledger = RunLedger(args.ledger)
    deadline = time.monotonic() + args.timeout_seconds
    while True:
        try:
            result = execute(args.role, bridge, ledger, run_id=args.run_id,
                             packet=packet, question=args.question, owner=args.owner)
            print(json.dumps({'role': args.role, 'run_id': args.run_id, 'result': result}, sort_keys=True))
            return 0
        except HandoffError as error:
            # Only missing future checkpoints are safe to poll. A remote claim,
            # failed submission or stale lease is never automatically retried.
            if (args.loop and args.role in {'research', 'validation'} and
                    str(error) in {'Run must be reserved before a worker can start',
                                   'Research task not yet checkpointed',
                                   'Validation handoff not yet checkpointed'} and
                    time.monotonic() < deadline):
                time.sleep(args.poll_seconds)
                continue
            print(json.dumps({'role': args.role, 'run_id': args.run_id,
                              'status': 'FAILED_NEEDS_REVIEW', 'error': str(error)}), file=sys.stderr)
            return 1


if __name__ == '__main__':
    raise SystemExit(main())
