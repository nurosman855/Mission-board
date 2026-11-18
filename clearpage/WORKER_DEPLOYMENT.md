# ClearPage native workers — isolated deployment checklist

**Status:** fixture-only verification. No AI provider or marketplace API is
enabled here. Do not expose the test credentials below outside an isolated
test environment.

## Two distinct runtime components

1. **Mission Control board:** the Next.js application; its prepared standalone
   artifact runs `node .next/standalone/server.js`. The board's release
   packaging deliberately excludes the `clearpage/` Python sources.
2. **ClearPage worker host:** Python 3.12+ with the checked-out `clearpage/`
   directory, persistent SQLite storage, and separate scoped API keys for
   Researcher and Validator. It can run on the same host or an isolated host
   with HTTPS access to the board. Do not copy the workers into `.next/standalone`.

All worker Python code currently uses the standard library only. Run commands
from the repository root and set each process's `MC_API_KEY` in its **own**
environment. Never place credentials in a command argument, committed file,
or shared shell history.

## Supervised fixture deployment sequence

1. Start Mission Control with its documented production configuration and a
   backed-up, writable database. Confirm the board's `/api/health` endpoint.
2. Create an existing directory for a persistent ledger, for example
   `/var/lib/clearpage`, accessible only to the worker service account.
3. Register the native roles and install their checked-in instructions through
   the existing agent registration procedure. Provision **different scoped**
   keys for Researcher and Validator; use a separately controlled coordinator
   credential for task scheduling.
4. Set `MC_BASE_URL` and the appropriate `MC_API_KEY` **separately in each
   process**. On remote hosts the URL must be HTTPS. Then schedule one fixture:

   ```bash
   python clearpage/worker_process.py --role schedule --run-id UNIQUE_RUN_ID --ledger /var/lib/clearpage/runs.sqlite --question 'Fixture-only demand check' --allow-live
   ```

5. Start Validator with its key and `--role validation --loop`, then Researcher
   with its distinct key and `--role research --packet /path/to/fixture.json`.
   Both use the **same durable ledger** and run ID. Do not use live market data.
6. Use `python clearpage/recovery_supervisor.py --run-id UNIQUE_RUN_ID
   --ledger /var/lib/clearpage/runs.sqlite --case` to inspect an interrupted run.
   Follow `RECOVERY_PLAYBOOK.md` before considering a restart.

## Acceptance checks

- Each stage uses its assigned API key; a cross-role request must be denied.
- A successful Researcher → Validator handoff produces `RESEARCH_MORE` for the
  unverified fixture and **zero paid model calls**.
- A duplicate run ID or replayed Validator step is rejected.
- Abrupt disconnects during claim, submission, and local checkpoint fail
  closed and become manual reconciliation cases; no automatic task steal.
- Board and worker processes can be restarted with the same persistent data.
- Backup/restore, alerting, service startup after reboot, TLS, least-privilege
  secret injection, and external network outage recovery need acceptance tests
  on the actual target host. Local smoke testing does **not** certify them.

## Checks executed locally

- The prepared Next.js standalone server started and returned a successful
  `/api/health` response in an isolated temporary database.
- The separate-process local development-server integration executed the
  coordinator, Researcher, and Validator through the real native API using
  distinct scoped keys. No model calls were made.
- Fault injection tests cover confirmed claim then lost network response,
  lost response after Researcher submission, validator creation before local
  checkpoint, failed heartbeat, and Validator submission timeout.

**Not yet tested:** deployment onto Nur's actual workstation or server,
container images, system-managed processes, network partitions at scale,
or long-duration worker reliability. The PR must remain a draft.
