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
2. **Crash recovery:** A crash after a native task transition but before scheduling its successor or recording the ledger result leaves an incomplete run. There is no reconciliation/retry supervisor; recover manually and do not silently replay.
3. **Queue contention:** The worker now requests its exact task ID with an atomic workspace-and-assignee-scoped claim. The legacy generic queue remains available for other clients; concurrency still requires load testing and care with role credentials.
4. **Durability:** Native task IDs are returned to the caller but not checkpointed in the SQLite ledger. An unattended restart needs durable stage/task linkage.
5. **Real evidence:** The Research Packet is a deliberately unverified fixture. `RESEARCH_MORE` is the correct outcome. No product strategy or publication is authorized.
6. **Operator interface:** These are importable Python steps rather than a durable background worker service or mobile control interface.

## Decision

**PASS for supervised, single-task-at-a-time offline simulation. NOT READY for unattended or paid execution.** Next development should address claim isolation, durable checkpoints and crash recovery before enabling model providers or external research APIs.

### Task-claim hardening checkpoint

- Explicit `task_id` claim is atomic and does not claim an unrelated role task.
- Invalid task IDs, unavailable IDs, and role/workspace boundaries are tested.
- Complete checks: **58 Python tests**, **1,609 JavaScript/TypeScript tests**, and `tsc --noEmit` passed.
- A local Next.js development-server smoke-test attempt encountered a build-manifest startup error; actual HTTP integration for this new endpoint is **not yet confirmed**. The draft PR must remain under review.
