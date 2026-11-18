# Native Researcher → Validator worker audit

## Scope

This is a **zero-cost fixture simulation** of separate Mission Control task ownership. The coordinator schedules one Researcher task, the Researcher claims and submits its packet, and the Validator claims its own task and retrieves the submitted packet from Mission Control. It does **not** collect real market evidence, authorize product creation, or invoke a language-model API.

## Verified

- Six targeted tests exercise the happy path, wrong run/task linkage, invalid evidence, premature validation, altered stored evidence, and duplicate scheduling.
- The complete ClearPage Python test suite passes (57 tests).
- An isolated Next.js Mission Control API test registers native roles and runs schedule → research → validation with both tasks in `review`, verdict `RESEARCH_MORE`, and zero model calls.
- Each transition verifies the native task's role, run ID, stage, and simulation flag. The Validator reads the Researcher's stored task resolution, not an in-memory handoff.
- The local SQLite ledger rejects repeat run IDs.

## Open production blockers

1. **Credential isolation:** Role identity is checked in task metadata, not guaranteed by independently scoped API credentials. Provision restricted role-specific credentials before real autonomous operation.
2. **Crash recovery:** The SQLite ledger now persists native Researcher/Validator task IDs and a read-only restart inspector identifies safe pending stages. Ambiguous transitions (remote creation before checkpoint, claimed-but-unsubmitted task, reviewed Researcher without linked Validator, or reviewed Validator without finalized ledger) are deliberately **manual reconciliation**. No automatic replay supervisor or lease-expiration policy exists.
3. **Queue contention:** The worker now requests its exact task ID with an atomic workspace-and-assignee-scoped claim. The legacy generic queue remains available for other clients; concurrency still requires load testing and care with role credentials.
4. **Durability:** Native task IDs are checkpointed monotonically in the SQLite ledger when the caller supplies the ledger to `research_step`. A crash between remote mutation and local checkpoint is necessarily ambiguous without server-side idempotency keys.
5. **Real evidence:** The Research Packet is a deliberately unverified fixture. `RESEARCH_MORE` is the correct outcome. No product strategy or publication is authorized.
6. **Operator interface:** These are importable Python steps rather than a durable background worker service or mobile control interface.

## Decision

**PASS for supervised, single-task-at-a-time offline simulation. NOT READY for unattended or paid execution.** Next development should address claim isolation, durable checkpoints and crash recovery before enabling model providers or external research APIs.

### Task-claim hardening checkpoint

- Explicit `task_id` claim is atomic and does not claim an unrelated role task.
- Invalid task IDs, unavailable IDs, and role/workspace boundaries are tested.
- Complete checks: **58 Python tests**, **1,609 JavaScript/TypeScript tests**, and `tsc --noEmit` passed.
- A local Next.js development-server smoke-test attempt encountered a build-manifest startup error; actual HTTP integration for this new endpoint is **not yet confirmed**. The draft PR must remain under review.

### Restart and crash-injection checkpoint

- Restarting `RunLedger` from the same SQLite path preserves the Researcher and Validator IDs.
- `inspect_interrupted_run` reads native task states and returns `RESEARCH_READY`, `VALIDATION_READY`, `NO_REPLAY`, or `MANUAL_RECONCILIATION` without writing to the server.
- Invalid or conflicting checkpoint assignments fail closed; the earlier mapping remains unchanged.
- Four additional Python tests cover process restart, claimed/reviewed orphan tasks, conflicting bindings and a remote-create/local-checkpoint gap. **62 Python tests pass.**
- This is **safe restart diagnosis and supervised continuation**, not automated recovery from every crash. An atomic server-side create idempotency key and a recovery supervisor are still needed for unattended operation.

### Server-side task creation idempotency checkpoint

- Migration `056_task_create_idempotency` establishes a unique `(workspace_id, actor_key, idempotency_key)` mapping to the created native task.
- The task creation transaction returns the existing task for the same canonical request and rejects key reuse with changed payload (HTTP 409), without repeating ticket allocation, notification creation, or sync side effects.
- ClearPage's bridge supplies deterministic run-and-stage keys for Researcher and Validator task creation.
- TypeScript checking, existing Vitest suite, and Python unit tests pass. A Playwright HTTP test was added for concurrent same-key retries, conflicts and distinct keys.
- **Verified against a live isolated Mission Control API:** Five concurrent identical POST requests returned `[201, 200, 200, 200, 200]`, all mapped to exactly one task, and same-key/different-payload returned HTTP 409. The same isolated run verified the Researcher → Validator native task handoff, `RESEARCH_MORE`, both tasks in `review`, and zero AI calls. The test used local throwaway credentials and a temporary SQLite database.
- The Playwright configuration's full build/startup still exceeded its 120-second timeout. An independent local webpack development-server smoke test succeeded; CI and deployment-specific build verification remain separate checks. Keep the PR draft until release gates and permission controls are reviewed.
- **Still open:** No automatic reconciliation supervisor; actor-scoped API permissions require independent enforcement tests; concurrent exact-task claim capacity has not been load-tested.

### Agent permission and safe-finalization checkpoint

- Non-admin agent-scoped task creation is now constrained to self-assignment, except for a narrow `clearpage-researcher` → `clearpage-validator` simulation handoff linked to a reviewed source in the same workspace and run.
- The Validator cannot self-schedule a task (prevents forging a source link). It can read a reviewed Researcher source only when a matching linked Validator task exists; the existing task-update endpoint remains limited to its own assignment.
- New unit tests cover unauthorized cross-agent creation and reviewed-source linkage. **A real isolated HTTP permission test using separately issued short-lived Researcher and Validator API keys passed**: own Researcher read 200, Validator linked-source read 200, Validator own read 200, Researcher cross-read 403, forged Validator self-assignment 403, unauthorized Researcher-to-Strategist creation 403, authorized reviewed Researcher-to-Validator handoff 201. Both keys were scoped to `operator` + `agent:self` and created only in a throwaway local database.
- These tests verify the specific ClearPage task routes above, not a whole-platform least-privilege or adversarial security audit. Do not enable broader permissions or assume other API endpoints are isolated without separate verification.
- `recover_submitted_validation` can safely finalize the ledger when both tasks are already in review and a deterministic recomputation matches the Validator's stored report. It cannot recover ambiguous partial remote transitions or perform unattended retries.
- Crash-injection tests cover failure after remote Validator submission and before local completion, and rejection of tampered Validator output. **65 Python tests pass; targeted access-control tests and TypeScript checking pass.**

### Supervised worker leases checkpoint

- SQLite now persists a per-run/per-stage lease with an unpredictable token, owner identity, expiry, and heartbeat timestamp. Acquisition, heartbeat and release use `BEGIN IMMEDIATE` and compare exact owner/token.
- Two worker processes sharing the ledger cannot acquire the same stage lease simultaneously. An expired lease **cannot** be stolen or silently renewed: it reports `EXPIRED_NEEDS_REVIEW` until an operator reconciles the native task.
- `research_with_lease` and `validation_with_lease` wrap the existing zero-cost worker steps. An exception deliberately retains the lease instead of pretending the remote operation was safely undone.
- Tests cover concurrent ownership, wrong token/owner, heartbeat, expiry, no automatic takeover, and a successfully completed leased handoff. **69 Python tests pass.**
- **Not production-ready:** These SQLite worker-stage leases remain local coordination fences. The subsequent server-side submission fence protects the actual review write, but the two lease systems have not been unified and do not yet automatically heartbeat or support unattended safe reassignment. A recovery supervisor is not deployed.

### Server-side result-submission fencing checkpoint

- Migration `057_clearpage_submission_fences` stores a SHA-256 hash of each scoped worker's random claim token with a task ID, assignee and expiry. The clearpage-specific exact-ID queue claim issues the token and stores its hash inside the same database transaction as the task claim.
- Non-admin ClearPage workers can update **only** an in-progress task assigned to them, and only to submit a review status with a resolution and matching token. The server checks the live token, assigned agent, current status and expiration in the same conditional SQL `UPDATE` that writes the result. Replaying after review is rejected.
- Live isolated HTTP proof with distinct, short-lived Researcher and Validator agent keys: missing token **403**, wrong token **409**, unauthorized field mutation **403**, correct current token **200**, replayed submission **409**, and artificially expired token **409**. Earlier handoff and concurrent task-creation tests still passed in this run. Zero model calls.
- This protection applies to **scoped ClearPage worker keys** on the existing native queue and task-update endpoints. The administrator retains its existing override; it is not intended as an immutable audit seal against an administrator.
- **Remaining:** An explicit lease renewal endpoint now exists (see next checkpoint), but no automatic heartbeat scheduler, safe automatic reassignment, deployed always-on workers or full platform security audit exists. An existing in-progress task cannot recover its lost token through a generic queue poll; manual reconciliation is required.

### Scoped lease renewal and expiry checkpoint

- `POST /api/tasks/{id}/lease` extends a current ClearPage worker fence to 120 seconds from the renewal time. The agent must authenticate with its own scoped key and supply the existing token; the SQL update checks token hash, assigned agent, workspace, unexpired fence and `in_progress` task status atomically.
- A wrong or expired token cannot renew; an administrator or unrelated agent cannot use this worker-only endpoint. A submitted task also cannot renew.
- A real isolated HTTP run with separate Researcher and Validator keys verified renewal **200**, wrong token **409**, expired token **409**; the existing submit-fencing, duplicate creation and handoff checks also passed. Zero paid AI calls.
- Three focused Vitest renewal tests passed, the complete JS/TS suite passed **1,616 tests**, TypeScript checking passed, and **69 Python tests** passed.
- **Deliberate safety boundary:** No server-side automatic reassignment, no background renewal scheduler, and no unattended recovery. Expired tasks require operator review and a controlled administrative reset before any new claim. That process has not yet been load-tested with separate live worker processes.

### Independent processes and repository-wide verification (2026-11-18)

- `clearpage/worker_process.py` is a bounded, opt-in command-line entry point for independent `schedule`, `research`, `validation`, `inspect`, and `recover-finalization` operations. Researcher and Validator use separate process environments and scoped API keys; the local run ledger persists across restarts. This is a **per-run worker**, not an always-on fleet supervisor.
- The worker refuses an actual stage claim without a server-issued fencing token. Neither fixture mode nor any stage invokes a paid model API.
- `task_heartbeat` renews the server submission fence and the associated SQLite stage lease while work is active. The final synchronous renewal fails closed before review submission if either renewal fails. This reduces lease-clock drift but does **not** make two databases one atomic transaction.
- The isolated live HTTP integration launched three separate OS processes (coordinator, Researcher, Validator) against a running Next.js API with distinct scoped agent credentials. Both worker processes exited successfully, the validator returned `RESEARCH_MORE`, a replay was blocked, and no model calls were made. The same run verified duplicate creation, cross-role authorization, task submission fencing, and correct/wrong/expired lease renewal.
- The complete Python suite passed **72 tests**; the complete Vitest suite passed **1,616 tests across 189 files**; repository-wide ESLint and `tsc --noEmit` passed; `scripts/security-audit.test.sh` passed. The OpenAPI parity check identified one omitted lease endpoint; `openapi.json` was corrected and parity passed (263 route operations, 254 documented operations, 12 explicitly ignored exceptions).
- The complete `npm run build -- --webpack` production build and standalone artifact preparation passed. Its tracing warning about 27 files outside `outputFileTracingRoot` is tied to this local workspace's external symlinked `node_modules`; **standalone deployment must be independently smoke-tested** in its target environment. The complete `npm run test:security-shell` suite passed, including `load-env` checks.
- The integration deliberately created an expired `in_progress` task. The native queue correctly refused to claim another task for that role until an administrator reconciled the stale task. Reconciliation was performed **only in the isolated test database**. Production requires a reviewed operator procedure for this state.

**Outstanding:** Real marketplace research, evidence-provider integrations, production credentials, durable always-on worker deployment, recovery from partial remote/local writes, load testing, and an automated browser E2E pass are not verified. Keep this work in draft review and keep paid APIs disabled until the separate security and recovery gates pass.

### Conservative recovery supervisor checkpoint (2026-11-18)

- Added `clearpage/recovery_supervisor.py` with a **read-only** one-run inspection and bounded `--watch` polling. Its HTTP transport rejects non-GET operations. It does not reclaim expired server fences, reset native task status, issue new work, or automatically retry a previously claimed task.
- Decisions are explicit: `OPERATOR_MAY_START_RESEARCH_WORKER`, `OPERATOR_MAY_START_VALIDATOR_WORKER`, `WAIT_NO_RETRY`, `MANUAL_RECONCILIATION_REQUIRED`, `VERIFIED_FINALIZATION_AVAILABLE`, and `DONE_NO_REPLAY`.
- The only mutation it can authorize is **local SQLite finalization** of an already submitted Validator report, and only with explicit `--finalize-verified`. Before that operation, the report is independently rederived from the Researcher's stored source packet and exact task/run linkage. No remote task writes or model calls occur.
- Seven additional Python tests cover missing runs, both safe ready stages, claimed tasks, active and expired leases, crash-before-ledger-finalize recovery with explicit approval, and tampered results. **79 Python tests pass**.
- This is deliberately **not** an unattended recovery supervisor capable of safely unblocking a stale `in_progress` server task. That needs an administrator-approved reconciliation protocol, stronger cross-store transactional coordination, and real deployment testing. A manually authorized worker restart is still required for a safe unclaimed stage.

### Administrative reconciliation evidence checkpoint (2026-11-18)

- Added `--case` to the recovery supervisor. It retrieves only checkpoint-bound, identity-validated native tasks and emits a deterministic `case_sha256` with run status, task IDs, task statuses, local stage-lease statuses, and the required operator action. Full research/validation payloads and API secrets are excluded from the dossier.
- Added `clearpage/RECOVERY_PLAYBOOK.md` with an operator-first procedure for pausing a role, verifying that the process is actually dead, collecting the case and native audit history, handling uncertain `in_progress` claims without replay, and preserving the original run ID and task record.
- The playbook explicitly forbids using a new run to conceal an unresolved old task. The supervisor still performs **zero remote mutations** and does not provide an automatic administrative reset or close endpoint.
- Two extra crash/identity tests verify deterministic dossiers, read-only calls, redaction, and refusal when a remote task belongs to a different run. **81 Python tests pass.**
- **Still blocked:** A human administrator must inspect and resolve ambiguous native states. Real administrative UI recovery, deployed process-stop proof, lost-update races between inspection and administrator action, network partitions, and load testing remain unverified.

### Deployment smoke and injected crash matrix (2026-11-18)

- Inspected the whole release packaging path: `scripts/prepare-standalone-artifact.mjs` intentionally removes raw Python sources from the Next.js standalone artifact. The board and ClearPage worker processes are **separate deployment units**; no production worker service has yet been deployed.
- The prepared standalone Next.js server started successfully in a clean, temporary Mission Control database and returned a healthy HTTP response from `/api/health`. `npm run artifact:check` passed the standalone release boundaries. This proves local startup only, not a container or remote-host deployment.
- Added `clearpage/WORKER_DEPLOYMENT.md` with separate-service deployment steps, scoped credential handling, persistent SQLite ledger requirements, supervised worker launch, recovery inspection and explicit acceptance gates.
- Added five fault-injection tests covering a dropped connection after task claim, failure after Researcher review before Validator task creation, crash after remote Validator creation before local checkpoint, failing lease heartbeat, and a dropped Validator submission response. In each case, a second worker is denied or the supervisor reports manual reconciliation; it never blindly retries a claimed task.
- Whole Python suite: **86 passed**. API parity, shell-security tests and standalone artifact check passed. The prior separate-process live HTTP smoke still passed with no model calls; the newly added faults were tested through controlled deterministic fake transports, **not** by injecting real packet loss into a remote network.
- **Unverified:** long-running deployment, actual target workstation/server, reboot/service management, container build, backup/restore, network-partition chaos, production-scale load, and browser E2E. Do not call the complete factory production-ready.

### Bounded multi-run fixture reliability checkpoint (2026-11-18)

- Added `clearpage/soak_fixture.py`: an explicitly opted-in, **localhost-only**, zero-model probe invoking coordinator, Researcher, and Validator as separate subprocesses for each unique run. Each cycle checks its persistent SQLite completion after reopening the ledger and proves replay rejection. The tool runs at most 100 cycles and stops at the first uncertain outcome; it is not a background service.
- An isolated real Mission Control API run completed **40/40** fixture handoffs in **61.11 seconds**, blocked **40/40** duplicate Validator replays, and made **0 paid model calls**. The earlier one-run lease, cross-role authorization, and idempotency probes also passed in the same test database.
- Full-code review exposed two potential credential-isolation vulnerabilities in the test harness: a crafted URL using `user@host` could bypass a naive localhost prefix check, and agent child environments could inherit other roles' keys. Both were repaired: URL parsing validates the actual hostname and rejects userinfo; each child process receives only its own key with parent role-key variables removed. A dedicated isolation test verifies the latter.
- **After** these two harness repairs, an additional real HTTP run passed **8/8** independent handoffs and blocked **8/8** replays with zero model calls. The 40-run test occurred immediately before the hardening changes.
- The complete Python suite has **90 passing tests**. Existing full JS/TS checks and security/API scans remain applicable. The 40-run proof measures repeated local execution; it does **not** establish continuous uptime, production deployment, or remote network fault recovery.

### Persistent supervised-service blueprint and backup checkpoint (2026-11-18)

- Added `ops/templates/clearpage-worker@.service` and `ops/templates/clearpage-recovery@.service`, and an explicit operator guide in `clearpage/PERSISTENT_DEPLOYMENT.md`. The workers are one-run services using separate per-role credential files and a shared persistent SQLite ledger. **Automatic worker restart is disabled** because the server may have accepted a task claim before a crash. The recovery monitor performs only read-only operations.
- `worker_process.py` can load an explicitly reviewed Researcher-only fixture path from `MC_RESEARCH_PACKET_PATH` when invoked by the service without a `--packet` argument. Validator never consumes that environment fallback. Its unit test passes.
- Added `clearpage/ledger_backup.py` using SQLite's online backup API and exclusive, non-overwriting publish. Four tests verify transaction-consistent checkpoint restoration, rejection of an existing destination, invalid paths, and corruption. Source database files are never deleted or overwritten.
- Both systemd templates passed `systemd-analyze verify` on the Linux test host. The **complete Python suite has 95 passing tests**.
- **Explicit limitation:** The systemd services were **not** installed or run on Nur's actual computer, and a 24-hour persistent service run has not happened. This checkpoint supplies tested templates and local backup mechanics, not production deployment acceptance. No paid model calls were made.
