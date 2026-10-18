# Tolerances and parameter changes

## Read manufacturing tolerances

Use `pdf_read_text` for native text.
Compare tolerance callouts with `pdf_render_page` and `pdf_crop_region` images.
Record the literal text, page, normalized displayed-page region, view, units, and observation confidence.
The current PDF tools do not return structured tolerance candidates.
For outlined text, transcribe the visible callout after image inspection. Do not claim OCR.
Do not use confidence as proof that a value or association is correct.

The part schema stores explicit deviations, limits, fit designations, and general tolerance statements.
A fit designation such as `H7` does not supply numerical limits by itself.
Keep the printed designation. Do not invent a tolerance class or use an unverified table.

## Store the source requirement

Use part schema 1.3 for nonempty `tolerances`.
Associate each tolerance with source evidence and, when known, its parameter.
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
