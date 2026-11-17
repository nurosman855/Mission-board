# Validation Report — contract v0.1

Input is one Research Packet conforming to `../researcher/OUTPUT_CONTRACT.md` version 0.1. Output is one UTF-8 JSON report. This is a design contract; no runtime JSON Schema enforcement exists yet.

## Required top-level fields
- `schema_version`: exactly `"0.1"`
- `validation_id`: stable unique validation run identifier
- `research_id`: same identifier as input packet
- `reviewed_at_utc`: ISO-8601 UTC timestamp
- `validator_role`: exactly `"market_validator"`
- `input_schema_version`: exactly `"0.1"`
- `input_integrity`: `VALID` or `INVALID`
- `verdict`: `PASS`, `RESEARCH_MORE`, or `REJECT`
- `checks`: array of check records; at least one
- `critical_findings`: array of actionable critical defects; may be empty on PASS
- `unresolved_gaps`: array of missing, contradictory or unverified decision-critical evidence
- `evidence_summary`: concise account of what independent inspection did and did not establish
- `recommended_next_step`: `HUMAN_REVIEW`, `RETURN_TO_RESEARCHER`, or `STOP`
- `market_validated`: false
- `human_go_approved`: false
- `commercial_release_allowed`: false

## Check record fields
Each `checks[]` record has:
- `check_id`: stable ID for this check
- `category`: `SCHEMA`, `PROVENANCE`, `CLAIM_ACCURACY`, `CUSTOMER_PAIN`, `PURCHASE_INTENT`, `ALTERNATIVES`, `CONTRADICTIONS`, or `COVERAGE`
- `status`: `PASS`, `FAIL`, or `UNVERIFIABLE`
- `severity`: `CRITICAL`, `MAJOR`, `MINOR`, or `INFO`
- `research_reference`: input record reference or `"packet"`
- `finding`: precise fact or issue
- `source_url`: HTTPS source actually inspected, or null
- `inspection_status`: `INSPECTED_SOURCE`, `NOT_INSPECTED`, or `NOT_APPLICABLE`
- `required_action`: correction or follow-up, or null

## Cross-field invariants
- `PASS` requires `input_integrity=VALID`, zero unresolved CRITICAL findings, no decision-critical unresolved gaps, and inspected support for consequential market claims.
- `PASS` must map to `recommended_next_step=HUMAN_REVIEW`. PASS does not assert verified sales volume or authorize production.
- `RESEARCH_MORE` maps to `RETURN_TO_RESEARCHER` and must identify at least one actionable missing piece.
- `REJECT` maps to `STOP` and requires a concrete material reason (invalid structure, fabricated/false material evidence, or strong contradictory evidence).
- When sources are inaccessible, mark related checks `UNVERIFIABLE`, never `PASS`.
- No outcome changes any of the three approval booleans; they remain false.
- The Validator cannot modify its input packet. Revised research must receive a separately traceable packet/run.

## Minimum validation categories
Always check SCHEMA, PROVENANCE, CLAIM_ACCURACY, CUSTOMER_PAIN, PURCHASE_INTENT, ALTERNATIVES, CONTRADICTIONS, and COVERAGE. An empty input observation list cannot yield PASS.

## Negative acceptance cases (specifications, not executed tests)
1. Empty observations with declared gaps => RESEARCH_MORE; no product approval.
2. Claimed verified sales without inspected proof => RESEARCH_MORE, or REJECT if demonstrated fabrication.
3. Missing required packet fields => REJECT, input_integrity INVALID.
4. Source pages inaccessible => RESEARCH_MORE unless independent grounds compel REJECT.
5. Source-backed but narrow findings => PASS only if no decision-critical gaps remain; still no autonomous product creation.

Next runtime increment: implement JSON Schemas and deterministic invalid-case tests before treating reports as a machine-enforced gate.
