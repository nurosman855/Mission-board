---
name: build-verified-printables
description: Use when ClearPageDigital's PDF Creator receives an approved printable or workbook brief and must produce original PDF pages, render every page, record technical and visual self-checks, and submit artifacts for independent QA.
---

# Build verified printables

Read `../../SOUL.md`, `../../OUTPUT_CONTRACT.md`, and the Product Strategist output contract before beginning.

1. Request controller-verified production authorization and match it to the exact approved brief ID/version. If unavailable, return BLOCKED before generating files or making model/tool calls.
2. Convert the brief into a page-by-page content map with requirement IDs and explicit exclusions. Clarify missing choices instead of inventing product scope.
3. Design a cohesive page system: typography, grids, whitespace, consistent page numbering, and legible instructions. Use original content and licensed/owned assets only.
4. Generate the PDF with reproducible tools already approved for the job. Keep the output path scoped to the assigned run; avoid network and paid services unless separately authorized.
5. Extract text, verify page count and dimensions, inspect fonts and links when relevant, and render **every page** to image previews.
6. Review every rendered page for clipping, overlaps, cramped text, awkward page breaks, poor contrast, and unusable form fields. Repair and re-render any defective page.
7. Cross-check all promised deliverables against the brief. Record a SHA-256 manifest, requirement-coverage table, QA notes, and honest unresolved issues.
8. Submit the candidate and report to the independent Quality Auditor. Do not self-approve, package, publish, or claim a product is ready for sale.

## Escalate
Pause if a production authorization, required asset license, exact product scope, tool approval, or critical functional requirement is missing. A nice-looking preview is not evidence of functional completeness.
