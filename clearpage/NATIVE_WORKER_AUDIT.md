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
- New unit tests cover unauthorized cross-agent creation and reviewed-source linkage. A dedicated end-to-end permission matrix using separate issued agent keys is **not yet completed**. Until then, do not declare runtime credential isolation production-ready.
- `recover_submitted_validation` can safely finalize the ledger when both tasks are already in review and a deterministic recomputation matches the Validator's stored report. It cannot recover ambiguous partial remote transitions or perform unattended retries.
- Crash-injection tests cover failure after remote Validator submission and before local completion, and rejection of tampered Validator output. **65 Python tests pass; targeted access-control tests and TypeScript checking pass.**
