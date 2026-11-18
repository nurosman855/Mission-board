# Supervised Researcher adapter audit — 2026-11-18

## Scope
One optional OpenAI Responses proposal call; one Researcher packet; existing offline Validator simulator; native Mission Control task handoff through an injected bridge. The model does **not** browse or independently inspect marketplace evidence. No request can yield a validated market signal or production approval.

## Controls verified locally
- `python -m unittest discover -s clearpage -p 'test_*.py' -q` — 51 tests pass.
- An explicit `allow_model_call=True` and a fresh one-call `BudgetedModelCalls` instance are required.
- Budgeted invocation reserves worst-case cost before calling the adapter; a provider failure marks the run `FAILED_NEEDS_REVIEW`.
- Researcher SOUL, output contract, and project skill are included in the actual model prompt.
- Model-supplied observations/approval flags are discarded; only an unverified hypothesis and missing-evidence list are accepted.
- The Research Packet passes contract validation and native task handoff remains simulation-labelled with zero independent source inspections.
- Duplicate run IDs are rejected by the durable `RunLedger` across fresh connections.
- Adapter uses `POST /v1/responses` with `store:false`, no tools, a small strict JSON schema, explicit output-token ceiling; incomplete responses and refusals fail closed.

## Blocking release issues
1. No `OPENAI_API_KEY` exists in the current execution environment; **no paid provider call was made**.
2. No provider-side hard spend cap, explicit real-money budget, model selection, or scoped API key has been approved. Do **not** enable unattended paid calls.
3. Application-level budget is per process, not an aggregate durable spending guarantee. Estimated reserve is not authoritative provider billing.
4. A model response is not web research: real source acquisition, ToS-respecting access, independent inspection and a true Validator PASS are not implemented.
5. The existing handoff still uses its explicitly simulation-only `run_fixture()` API and fabricated research task completion; rename/replace that bridge before considering the full pipeline operational.
6. Human review and restart reconciliation remain mandatory, especially if a provider succeeds but the task API fails after an attempted submission.

## Release decision
**Ready for code review and isolated zero-cost testing; NOT ready for a paid or unattended production run.**
