# PDF Creation Report — contract v0.1

Return one structured JSON report. Runtime must independently verify trusted production authorization; an agent-authored approval claim cannot unlock generation.

## Required fields
- `schema_version`: exactly `"0.1"`
- `report_type`: exactly `"PDF_CREATION_REPORT"`
- `creation_id`: unique run identifier
- `brief_id`: exact approved brief identifier
- `brief_version`: exact approved brief version
- `creator_role`: exactly `"pdf_creator"`
- `status`: `BLOCKED` or `READY_FOR_INDEPENDENT_QA`
- `blockers`: array of actionable blockers; nonempty when BLOCKED
- `authorization_reference`: trusted handoff reference, or null when BLOCKED
- `artifact_manifest`: array; empty when BLOCKED
- `requirement_coverage`: array; empty when BLOCKED
- `qa_evidence`: object or null; null when BLOCKED
- `unresolved_issues`: array of limitations and defects
- `quality_approved`: always false
- `commercial_release_allowed`: always false

## Artifact manifest fields
Every output file record includes `relative_path`, `file_type` (`PDF` or `PNG_PREVIEW`), `sha256`, `file_bytes`, and `purpose`. Paths must remain within a designated output directory and must not reference private keys or customer data.

## Requirement coverage fields
Every entry includes `requirement_id`, `status` (`MET`, `NOT_MET`, `NEEDS_REVIEW`), `artifact_reference`, and `verification_note`. Every required element of the source brief must be covered.

## QA evidence fields
When READY_FOR_INDEPENDENT_QA include `page_count`, `page_sizes`, `rendered_page_count`, `font_check`, `text_extraction_check`, `layout_review_summary`, `functional_check_summary`, and `asset_rights_review`. A preliminary self-check is not an independent quality approval.

## Invariants
1. No verified production handoff matching brief ID/version -> BLOCKED, no artifacts.
2. Strategist `READY_FOR_PRODUCTION_REVIEW` is not production authorization.
3. Missing pages, unrendered pages, unsupported claims, broken links, or unresolved critical defects prevent READY_FOR_INDEPENDENT_QA.
4. No output can change quality or commercial approval flags from false.
5. Human or independent QA review remains necessary before packaging and storefront publication.

## Negative acceptance cases
- Unapproved or mismatched brief -> BLOCKED.
- Strategy Decision marked `READY_FOR_PRODUCTION_REVIEW` with no separate production handoff -> BLOCKED.
- Missing required page or an obvious clipped page -> BLOCKED until repaired.
- All pages generated but not independently inspected -> may be READY_FOR_INDEPENDENT_QA, never quality-approved.
