# ClearPage Mission Control — interrupted-task operator playbook

**Scope:** fixture-only Researcher → Validator jobs. No paid model calls, no
external evidence collection, and no autonomous task reset.

## Inspect before changing anything

1. Stop new schedules for the affected role and verify the worker process is no
   longer running. A task marked `in_progress` is **not** proof of a dead worker.
2. Set `MC_BASE_URL` to your trusted Mission Control instance and `MC_API_KEY`
   to an authorized **read-only capable** credential in your shell. Never paste
   keys into logs, chat, or GitHub.
3. From the repository root, run:

   ```bash
   python clearpage/recovery_supervisor.py --run-id RUN_ID --ledger /path/to/runs.sqlite --case
   ```

4. Save the printed `case_sha256`, inspect the native task's activity history
   in the administrator interface, and compare bound task IDs with the ledger.
   The case intentionally omits full task resolutions and evidence payloads.

## Decisions

| Decision | Permitted action |
| --- | --- |
| `WAIT_NO_RETRY` | Wait for the active worker; do not change the task. |
| `OPERATOR_MAY_START_RESEARCH_WORKER` | Start the existing Researcher worker on its existing run and assigned task, using its own scoped key and fixture packet. |
| `OPERATOR_MAY_START_VALIDATOR_WORKER` | Start the existing Validator worker on its existing run and assigned task, using its own scoped key. |
| `VERIFIED_FINALIZATION_AVAILABLE` | An operator may run `--finalize-verified` to write only the local SQLite completion record after deterministic re-verification. |
| `MANUAL_RECONCILIATION_REQUIRED` | Stop. Investigate all server and ledger states before any administrative task transition. |
| `DONE_NO_REPLAY` | No retry or new write is needed. |

## For a stuck `in_progress` task

1. Confirm the worker is stopped; do **not** infer this merely from an expired
   lease. Verify current status, task ownership, and task audit history.
2. Check whether the original worker submitted a review result. If already in
   `review`, use the supervisor's independent verification path when eligible.
3. If still `in_progress`, **do not** automatically change it back to
   `assigned`. A remote submission might have succeeded even if the local
   checkpoint did not. Preserve the original task and associated audit trail.
4. An administrator must explicitly decide whether to close the existing
   failed attempt, investigate an orphaned result, or create a new run. If a
   new attempt is authorized, give it a **new run ID** and retain the original
   case and history. No programmatic reset command is provided by this module.
5. Re-run `--case` after administrative intervention and verify that the
   original run cannot be executed again. Restore scheduling only once the
   assigned role has no unresolved stale task.

## Rules that must remain true

- Never steal or renew another worker's lease.
- Never replay a claimed or reviewed task.
- Never bypass scoped worker credentials or disable submission fencing.
- Never use a new run ID to hide an unresolved old task.
- Do not enable paid providers or unattended recovery until a separate
  production security and load audit has approved those changes.

## Verification scope

Unit tests cover stable, read-only dossiers, identity mismatches, active versus
expired local leases, tampered validator reports, explicit finalization,
duplicate-run protection, and the interrupted handoff. Live deployment,
administrator UI reconciliation, and network-partition chaos testing are
separate acceptance gates and are **not** implied by these tests.
