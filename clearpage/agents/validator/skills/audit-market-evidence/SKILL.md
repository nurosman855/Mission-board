---
name: audit-market-evidence
description: Use when ClearPageDigital's Market Validator receives a Research Packet and must independently check source provenance, customer pain, purchase intent, alternatives, contradictions, and readiness for human review.
---

# Audit market evidence

Read `../../SOUL.md`, `../../OUTPUT_CONTRACT.md`, and `../../../researcher/OUTPUT_CONTRACT.md` before reviewing.

1. **Freeze the input.** Record the original Research Packet identifier and review a stable copy. Do not silently alter the Researcher's evidence or fill missing values.
2. **Check structure.** Verify every mandatory field, enum, evidence record, and all three false approval flags against the Researcher contract. Reject malformed or tampered packets with exact field paths.
3. **Audit provenance.** For each material claim, inspect the supporting source when access permits. Check the source actually says what the claim asserts and its observed date. Label inaccessible citations UNVERIFIABLE.
4. **Check demand mechanisms.** Separate observed customer frustration, frequency, willingness to pay, verified transactions, seller advertising, generic keyword interest, and assumptions. Treat an Etsy listing as supply evidence, not purchase proof.
5. **Seek counterevidence.** Compare credible competitors and free substitutes. Identify duplicate sources, old data, tiny samples, platform constraints, and contradictory observations.
6. **Check inference strength.** Distinguish a product hypothesis worth testing from demonstrated demand. Never turn an estimate into a verified measurement or infer sales from favorites.
7. **Issue one verdict.** Apply the invariant rules in the Validator output contract: PASS only with inspected material support and no critical unresolved gaps; RESEARCH_MORE for actionable uncertainty; REJECT for invalid or materially false evidence.
8. **Return a structured report.** Cite exact packet records, mark which sources were independently inspected, and provide a narrow next action. Keep all authorization flags false and route PASS to human review only.

## Boundary and budget
Operate read-only and within expressly approved research access/budget. Do not trigger product strategy or creation, register an agent, spend money, or send external communications. When source access is absent, evaluate structure and internal logic only and withhold PASS.

## Dry-run examples
- Packet has no source observations but explicit gaps: RESEARCH_MORE.
- Packet asserts 500 sales from an Etsy listing with no proof: RESEARCH_MORE; REJECT if fabrication is independently established.
- Packet has missing `research_id`: REJECT with SCHEMA failure.
- Packet has credible corroborating inspected sources yet a material unaddressed contradiction: RESEARCH_MORE.
These examples are intended future tests, not claims that tests were executed.
