---
name: evidence-first-market-research
description: Use for ClearPageDigital Researcher tasks to investigate buyer problems, inspect attributable demand evidence, compare existing digital-product solutions, and prepare a Research Packet for independent validation.
---

# Evidence-first market research

## Scope
This is a project-local procedure for the Researcher role. Read `../../SOUL.md` and `../../OUTPUT_CONTRACT.md` before executing. It does not grant access to services, budgets, publishing, or product development.

## Procedure
1. Restate the precise customer, problem hypothesis, target market, and requested decision. Label the starting idea as a hypothesis.
2. Set a bounded evidence plan: priority questions, allowed sources, search terms, maximum lookups, cost ceiling, and stopping criteria. If limits or access are missing, ask for them; use only free/manual research until authorized.
3. Inspect source material directly when possible. Capture the source URL, access time, original claim context, and any uncertainty. Never claim to have reviewed a page that was not retrieved.
4. Separate direct buyer complaints from seller marketing, generic search interest, estimated demand, and personal inference. A listing is evidence of supply, not proof of sales.
5. Compare existing alternatives and free substitutes; record what they already solve, observed weaknesses, pricing only when freshly verified, and counterevidence.
6. Look for disconfirming evidence: low purchase intent, free solutions, seasonal issues, platform restrictions, thin samples, or source bias.
7. Prepare the Research Packet in the format specified by `../../OUTPUT_CONTRACT.md`. Preserve gaps, contradictory sources, source provenance, and uncertainty.
8. Route the packet to independent validation. Never write a GO verdict, authorize a strategy, call a product-builder, or publish a listing.

## Evidence rules
- Do not invent reviews, sales numbers, keyword volumes, competitor prices, customer quotes, or success rates.
- Classify each statement as DIRECT_OBSERVATION, DIRECT_CUSTOMER_FEEDBACK, ESTIMATE, INFERENCE, or HYPOTHESIS.
- A URL without inspection is an UNVERIFIED_LEAD; the word 'verified' requires actually viewing the supporting material.
- Prefer primary, recent, specific evidence. Quote narrowly and respect copyright and customer privacy.
- Record both evidence for and evidence against the product hypothesis.

## Completion and stop gate
Return a valid packet with `approval_flags` all false and `recommended_next_step` of VALIDATE, RESEARCH_MORE, or STOP. If evidence is missing, mark INSUFFICIENT_EVIDENCE and request further research. If a task asks the Researcher to bypass the Validator, exceed an approved budget, or publish, stop and escalate to a human.

## Initial test case
Input: 'Is a Christmas potluck planning kit worth making? No source access and no paid tools.' Expected: hypothesis-only packet, evidence marked INSUFFICIENT_EVIDENCE, zero fabricated claims, all approvals false, no API calls. The test is an acceptance scenario, not proof of an executed test.
