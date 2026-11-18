# ClearPage runtime-gate audit — 2026-11-18

## Scope and observed results

This change adds a project-local agent instruction loader, native Mission Control
agent registration/SOUL readback, SQLite at-most-once run reservation, and a
disabled-by-default model-call preflight. It does **not** turn on unattended AI.

Evidence:

1. `PYTHONDONTWRITEBYTECODE=1 python -m unittest discover -s clearpage -p 'test_*.py' -q`: **28 passed** (including 14 new runtime-control tests).
2. Isolated Mission Control 16.4.6 production instance bound to `127.0.0.1`, temporary database and generated credentials: both agents registered with native roles; SOUL content including skill and output contract uploaded and read back exactly.
3. Same isolated instance: two real task API cycles completed to `review`; Validator returned `RESEARCH_MORE`; durable duplicate attempt using a fresh ledger connection rejected without creating more tasks; **zero model calls**.
4. Prior integration verification: unauthenticated task create denied; `done` without Aegis approval denied. These are native control-plane protections, separate from business validation.

## Findings and controls

| Severity | Finding | Current control / status |
|---|---|---|
| Critical | A model provider's charges cannot be capped reliably by local estimates alone. | Calls default to disabled. A provider-side spending limit, approved rate card and explicitly scoped API key are required before live paid use. **Open.** |
| High | Model-call counter is in-memory and not shared across processes or restarts. | Per-process preflight only. Do not run multiple paid workers or unattended calls until a durable shared spend ledger exists. **Open.** |
| High | Existing `MissionControlBridge.run_fixture()` can be invoked without the new `run_once()` ledger wrapper. | Only the audited `run_once()` entry point offers at-most-once reservation. Enforce this boundary in the eventual production command and avoid legacy direct calls. **Open.** |
| High | A crash after task creation leaves a `RESERVED`/`FAILED_NEEDS_REVIEW` record. | Fail closed; no automatic retry. Human must reconcile native task records before new run ID. **Accepted for manual-only tests.** |
| High | No real research model or independent online source inspection executed. | All results are explicitly simulation-only. A separate acceptance test with scoped credentials is needed. **Open.** |
| Medium | Project-local skills are included in SOUL content, not installed into Mission Control's global Skills Hub. | Native SOUL readback verified. Full runner prompt injection/skill selection not yet verified. **Open.** |
| Medium | Role-specific tool permissions and runtime scopes are not yet enforced by a provider adapter. | Two native roles were registered, but operator API key powered the isolated test. Separate least-privilege keys are required for production. **Open.** |

## Release gate

This PR is suitable for **manual, isolated, zero-cost testing only**. It must not
be presented as a safe unattended revenue-producing factory. Before enabling
paid research, require: provider choice, explicit budget, provider-side spend
limit, durable global spend reservations, permission review, real research-
evidence acceptance, and a recovery drill for interrupted runs.
