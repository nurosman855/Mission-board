# Research Packet — contract v0.1

The Researcher delivers one UTF-8 JSON packet per research task. It never authorizes demand validation, product creation or commercial release.

## Required top-level fields

- schema_version: exactly 0.1
- research_id: stable task/run identifier
- research_question: specific research question
- target_customer: concrete customer description
- customer_problem_hypothesis: explicitly unverified hypothesis
- observed_at_utc: ISO-8601 timestamp
- evidence_status: UNVERIFIED, PARTIALLY_VERIFIED, or SOURCE_BACKED_NEEDS_VALIDATION
- observations: array of evidence records, possibly empty
- alternatives: array of competing or substitute solutions, possibly empty
- gaps: array of missing decision-critical evidence
- contradictions: array of conflicting findings
- limitations: array of source, sampling and measurement limitations
- recommended_next_step: RESEARCH_MORE or SEND_TO_VALIDATOR
- market_validated: false
- human_go_approved: false
- commercial_release_allowed: false

## Evidence record fields

Each observation or alternative must include: claim; class (DIRECT_OBSERVATION, DIRECT_CUSTOMER_FEEDBACK, ESTIMATE, INFERENCE, HYPOTHESIS); source_url (HTTPS or null for a pure hypothesis); source_type; source_observed_at_utc; supporting_detail (short excerpt or precise paraphrase); verification (INSPECTED_SOURCE, UNVERIFIED_LEAD, NOT_APPLICABLE); and caveat. Never include customer identifiers.

## Acceptance checks

- All required fields must be present with the documented types and enumerations.
- A market claim classified as observed must have inspected source provenance; a URL alone is not proof.
- Unverified or unavailable metrics must not be presented as verified data.
- Contradictions and limitations must remain visible.
- Empty observations are acceptable only with RESEARCH_MORE and explicit gaps.
- All approval flags remain false, including in source-backed packets.
- The independent Validator may reject this packet, request additional research, or recommend human review.

The first runtime increment must implement a machine-readable JSON Schema and invalid-packet tests. This document is a specification, not an executed validation gate.
