# Tolerances and parameter changes

## Read manufacturing tolerances

Use `pdf_read_text` for native text and `tolerance_candidates`.
Compare each candidate with `pdf_render_page` and `pdf_crop_region` images.
Native candidates use a whole-page source region and `location_precision="page"`.
Their confidence is a fixed heuristic, not a measured recognition probability.
Native extraction supports separate callout lines. It does not associate arbitrary page text with model features.

For outlined text, inspect the source image first.
Supply the visible callout through `tolerance_observations` in `pdf_read_text`.
Each observation requires `raw_text`, `page`, `view`, `region`, `source_sha256`, and `confidence`.
The page must be selected. The hash must match the current PDF bytes.
Use normalized displayed-page bounds `[left, top, right, bottom]` for `region`.
Supply `unit` when the permitted source establishes it. Use the live schema for optional `notation_hint` values.
These records have `provenance="client_observation"`; they are transcriptions, not OCR results.
Do not use confidence as proof that a value or association is correct.

The tool accepts at most 100 observations and returns at most 200 candidates.
If the candidate limit is exceeded, select fewer pages.
Inspect truncation and skipped-line information. Do not treat omitted text as an absent requirement.

The parser supports explicit deviations, limits, fit designations, and general tolerance statements.
A fit designation such as `H7` does not supply numerical limits by itself.
Keep the printed designation. Do not invent a tolerance class or use an unverified table.
Unclear notation, contradictory bounds, and conflicting units need review.

## Missing and incomplete manufacturing requirements

Record each missing functional requirement as a decision, not as a value from picture geometry.
Do not infer a tolerance class, a datum system, a material, or a surface requirement from the drawing image or from the model.
An empty general-tolerance field is a missing requirement. Record it, and do not fill it.

For each missing requirement, record one of these decisions with its reason:

- `user_decision`: a value that the user supplied. Keep it separate from source requirements.
- `open`: an open review item. The construction can proceed with a reasonable nominal geometry.
- `not_applicable`: the requirement does not apply to the part, with the reason.

An incomplete specification can support a reconstruction. It cannot support an unqualified manufacturing-release claim.
Report the open requirements in the final report.

## Geometrical tolerances and datums

Record each source geometrical tolerance frame, datum feature symbol, and theoretically exact dimension with its literal text,
source view, region, and the affected feature (ISO 1101, ISO 5459, ISO 8015).
The current part and drawing contracts have no structured tolerance frames, datums, or datum systems.
Keep these requirements as tolerance records or notes with an open review item. Their coverage row has status `needs_review`.
Do not invent a datum system or a datum order. Do not convert a frame into free text and report it as a supported tolerance.

## Store the source requirement

Use part schema 1.3 for nonempty `tolerances`.
Associate each tolerance with source evidence and, when known, its parameter.
Put the candidate `source` in an evidence record. Reference its ID from the tolerance.
Do not copy transport fields such as `provenance` into the closed tolerance record.
Use `part_schema` for its permitted fields and supply stable IDs.
Both `association_required` and `source_review_required` require agent review; they are not proof of an accepted association.
Keep the source hash, page, region, literal text, and confidence.
Use construction evidence with normalized displayed-page coordinates.

Keep `printed_nominal` separate from the current design parameter.
Keep manufacturing tolerances separate from `Measurement.tolerance`, which controls a numerical geometry test.
Do not widen a numerical test to make a changed design pass.

Retain unclear text and uncertain associations in open review items.
Do not discard a visible requirement because its interpretation is incomplete.
A reasonable nominal construction can proceed while the manufacturing requirement remains open.
A schema pass does not prove manufacturing compliance.

Tolerance data in the JSON description do not prove semantic tolerance PMI in STEP.
Report semantic PMI and target-CAD behavior separately.

## Change an existing part

1. Call `part_read` and retain the current revision and description hash.
2. Change the required parameters in the complete description.
3. Update dependent profile points or selectors only when the design change requires them.
4. Preserve printed source requirements and record the reason for each design change.
5. Call `part_validate`, then `part_update` with the current `expected_revision`.
6. Inspect the change report for direct references and potentially affected later features.
7. Call `build_from_description` with the new revision.
8. Inspect geometry measurements, fresh-worker STEP import, and agreement results.
9. Compare the measured effects with the intended change.
10. Regenerate the drawing and repeat its review when the delivery includes a drawing.
11. Release the validated STEP and retain `part_export_review` evidence.

The update invalidates the previous build and release.
An accepted update is not a validated geometric change.
Keep failed build results and their reasons. Correct the description before another build.

The report distinguishes changed inputs, potential dependencies, and measured effects.
Later ordered features can depend on earlier geometry without a direct parameter reference.
Equal volumes do not prove equal geometry.
The prototype does not solve algebraic constraints or update independent source measurements automatically.

For an authorized change to an assumed dimension, supply the revised independent check explicitly.
If a changed parameter conflicts with an unchanged printed requirement, retain and report that failure.
