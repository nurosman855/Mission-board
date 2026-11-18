"""Bounded, zero-model, separate-process native task reliability probe.

Requires a preconfigured isolated Mission Control server and three credentials:
MC_COORDINATOR_API_KEY, MC_RESEARCH_API_KEY and MC_VALIDATION_API_KEY.
Never targets production automatically; all runs use unverified fixture data.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path
from urllib.parse import urlsplit

from runtime_controls import RunLedger
from test_handoff import packet


def role_environment(parent: dict[str, str], *, key: str, base_url: str) -> dict[str, str]:
    """Build an isolated child environment without other role key material."""
    safe = {name: value for name, value in parent.items()
            if name not in {'MC_API_KEY', 'MC_COORDINATOR_API_KEY',
                            'MC_RESEARCH_API_KEY', 'MC_VALIDATION_API_KEY'}}
    return {**safe, 'MC_API_KEY': key, 'MC_BASE_URL': base_url,
            'PYTHONDONTWRITEBYTECODE': '1'}


def run_probe(*, runs: int, ledger_path: Path, base_url: str, keys: dict[str, str],
              timeout: int = 45) -> dict:
    """Exercise real CLI processes, restart the ledger, and reject every replay."""
    if not 1 <= runs <= 100 or not 5 <= timeout <= 180:
        raise ValueError('Invalid bounded probe limits')
    target = urlsplit(base_url)
    if (not ledger_path.parent.is_dir() or target.scheme != 'http' or
            target.hostname not in {'127.0.0.1', 'localhost'} or not target.port or
            target.username or target.password or target.path not in {'', '/'} or
            target.query or target.fragment):
        raise ValueError('Only an explicitly local isolated Mission Control endpoint is allowed')
    if set(keys) != {'schedule', 'research', 'validation'} or any(not v for v in keys.values()) or len(set(keys.values())) != 3:
        raise ValueError('Three different, nonempty role credentials required')
    worker = Path(__file__).resolve().with_name('worker_process.py')
    summary = {'runs_requested': runs, 'runs_completed': 0, 'replays_blocked': 0,
               'ai_calls': 0, 'elapsed_seconds': None, 'status': 'IN_PROGRESS'}
    began = time.monotonic()
    for index in range(runs):
        run_id = f'soak-{uuid.uuid4().hex}-{index:03d}'
        fixture = packet()
        fixture['research_id'] = run_id
        env = {role: role_environment(os.environ, key=key, base_url=base_url)
               for role, key in keys.items()}
        common = [sys.executable, str(worker), '--run-id', run_id,
                  '--ledger', str(ledger_path), '--allow-live']
        validator = None
        with tempfile.TemporaryDirectory() as directory:
            packet_path = Path(directory) / 'fixture.json'
            packet_path.write_text(json.dumps(fixture), encoding='utf-8')
            try:
                scheduled = subprocess.run(common + ['--role', 'schedule', '--question', fixture['research_question']],
                                           env=env['schedule'], capture_output=True, text=True, timeout=timeout)
                if scheduled.returncode:
                    raise RuntimeError(f'Coordinator failed at iteration {index}')
                validator = subprocess.Popen(common + ['--role', 'validation', '--loop',
                                                       '--poll-seconds', '0.2', '--timeout-seconds', str(timeout)],
                                             env=env['validation'], stdout=subprocess.PIPE,
                                             stderr=subprocess.PIPE, text=True)
                researcher = subprocess.run(common + ['--role', 'research', '--packet', str(packet_path)],
                                            env=env['research'], capture_output=True, text=True, timeout=timeout)
                if researcher.returncode:
                    raise RuntimeError(f'Researcher failed at iteration {index}')
                validator_output, _ = validator.communicate(timeout=timeout + 5)
                if validator.returncode:
                    raise RuntimeError(f'Validator failed at iteration {index}')
                result = json.loads(validator_output)['result']
                if result['validation_report']['verdict'] != 'RESEARCH_MORE' or result['validation_report']['ai_calls'] != 0:
                    raise RuntimeError(f'Unexpected fixture verdict at iteration {index}')
                # Reopen the persisted ledger as if the supervisor restarted.
                reopened = RunLedger(ledger_path)
                if reopened.status(run_id) != 'COMPLETE':
                    raise RuntimeError(f'Incomplete persistent ledger at iteration {index}')
                replay = subprocess.run(common + ['--role', 'validation'], env=env['validation'],
                                        capture_output=True, text=True, timeout=timeout)
                if replay.returncode == 0 or 'FAILED_NEEDS_REVIEW' not in replay.stderr:
                    raise RuntimeError(f'Unsafe replay at iteration {index}')
                summary['runs_completed'] += 1
                summary['replays_blocked'] += 1
            finally:
                if validator is not None and validator.poll() is None:
                    validator.terminate()
                    try:
                        validator.communicate(timeout=3)
                    except subprocess.TimeoutExpired:
                        validator.kill()
                        validator.communicate()
    summary['elapsed_seconds'] = round(time.monotonic() - began, 2)
    summary['status'] = 'PASS'
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description='Isolated, bounded Researcher/Validator fixture soak')
    parser.add_argument('--runs', type=int, default=10)
    parser.add_argument('--ledger', type=Path, required=True)
    parser.add_argument('--base-url', default='http://127.0.0.1:3000')
    parser.add_argument('--ack-isolated-fixture', action='store_true')
    args = parser.parse_args(argv)
    if not args.ack_isolated_fixture:
        parser.error('Explicit isolated fixture acknowledgement required')
    keys = {role: os.environ.get(name, '') for role, name in (
        ('schedule', 'MC_COORDINATOR_API_KEY'), ('research', 'MC_RESEARCH_API_KEY'),
        ('validation', 'MC_VALIDATION_API_KEY'))}
    try:
        report = run_probe(runs=args.runs, ledger_path=args.ledger, base_url=args.base_url, keys=keys)
        print(json.dumps(report, sort_keys=True))
        return 0
    except (ValueError, RuntimeError, subprocess.TimeoutExpired, OSError, KeyError, json.JSONDecodeError) as error:
        # Do not print exception details: injected transports and subprocess
        # failures must never leak key material into logs.
        print(json.dumps({'status': 'FAIL_NEEDS_REVIEW', 'error_type': type(error).__name__}), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
