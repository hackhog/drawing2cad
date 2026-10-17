# Verification and correction loop

Use this loop for reconstruction and model changes through `drawing2cad-mcp`.
Read the live schemas before the first request and after a server version change.
Keep model changes in sequence. Use a separate reviewer when available; this is optional for the hackathon metric.
Otherwise, the acting agent records its identified review attestation.

## Prepare and validate JSON

Read `part_schema` and the applicable tool input schemas.
For domain drawing delivery, also read `drawing_schema`. The local-path metric skips drawing operations.
Use only tools that both the server and the client permit.
Read `pmi_schema` only when the requested profile uses supported PMI.
Prepare ordinary JSON data with stable identifiers, explicit units, parameter references, and source evidence.
Use a JSON parser and serializer. Do not use `eval` to decode data.
Keep executable expressions out of declarative fields. Do not create ad hoc model files.
Keep numeric values finite. Use the closed fields, types, limits, and coordinate rules from the live schema.
Use the live server contract as the authority, including when a client caches its JSON Schema.

Call `part_validate` for the description.
For domain drawing delivery, call `drawing_validate` for the revision-bound drawing specification.
These MCP tools apply maintained Pydantic models and additional contract checks.
Correct the returned defect code and its JSON pointer or identifier, where supplied.
Retain structured errors and the exact failed request. Do not interpret a union-branch name as an input field.
Revalidate the corrected payload before the next dependent operation.

Pydantic validates declared data. It does not prove a valid solid, source agreement, readable drawing, or sandbox isolation.
Use actual worker results and artifact review for those separate claims.

## Measure the model

Build the validated description through the MCP.
Compare measurements from the resulting geometry with independent source expectations.
Inspect feature coverage and local details. A bounding-box pass cannot prove a hole, rib, or pocket.
If geometry is incorrect, revise the responsible parameters or features and rebuild.
Keep source expectations unchanged unless an authorized design change replaces them.
Read the resulting revision and description hash before updating the drawing binding.

## Inspect drawing diagnostics

This section applies to domain drawing delivery. It does not add drawing requirements to the local-path metric.

Run `drawing_validate`, then `drawing_render` for the current part revision.
If drawing validation returns `diagnostic_eligible: true`, rendering can supply a preview of the failed layout.
Other validation failures require correction before rendering.
Inspect the returned operation status and the drawing status. A completed request can contain a failed drawing.
For a rendered layout failure, inspect the layout report and any diagnostic artifacts returned by the live service.
Read labels and collision pairs from `drawing.report.diagnostics`.
Select the PDF with role `drawing_diagnostic_preview` and the JSON report with role `drawing_diagnostic_report`.
The diagnostic PDF is an inspection aid marked **NOT FOR RELEASE**. It is not the accepted technical drawing.
Use `artifact_preview` for the diagnostic PDF, when available.
If the client permits downloads, use `artifact_read` for diagnostic files. Otherwise, supply their IDs to the permitted host.
Inspect the actual image as well as the collision records.

Diagnostic label bounds use sheet millimeters from the bottom-left origin, with positive Y upward.
Use label identifiers and collision pairs to locate the affected drawing elements.
Observe reported truncation or scan limits. A bounded report need not list every collision.
Compare a reported overlap with the visible text before choosing a correction.
Record a suspected detector defect instead of removing a required dimension to obtain a pass.

Correct the affected label position, view frame, spacing, scale, or sheet layout.
Preserve dimension values, geometry associations, source evidence, and required view coverage.
Then repeat validation and rendering, and inspect the new PDF.
A model error requires a model correction and new binding; moving drawing text cannot repair it.

Diagnostic previews apply to supported rendered layout failures only.
Schema, evidence, geometry, or binding failures can stop before a preview exists.
Correct the reported contract defect first. Do not bypass it with a separate renderer.
Keep failed artifacts as evidence. A failed drawing cannot receive an accepted review. The STEP release states the failed drawing and links its diagnostic files.

## Review and release

For domain drawing delivery, do the drawing review below. The STEP release does not wait for it; the release records the drawing status. The local-path metric skips this drawing review.
After a render pass, independently compare the final source, drawing, and measured model.
Inspect the complete sheet and necessary detail views for legibility, missing features, and unclear assumptions.
Compare inner and outer boundaries in each view. Duplicate lines do not prove that both boundaries are present.
Inspect section hatching against material regions. Keep hatch strokes outside bores, pockets, and drill-point voids.
Explain uncertainty abbreviations in a visible legend. Keep each marker connected to its affected feature.
Record `drawing_review` for the exact drawing hash and current model build.
Repeat affected checks and obtain a new review after a change that invalidates the previous result.

In both profiles, inspect the candidate STEP and its fresh-worker import results before `export_step`.
AP242 and semantic PMI are optional M3 capabilities for the hackathon metric.
For AP242, also apply [ap242-adapter.md](ap242-adapter.md) within the verified capability scope.
Keep external analysis, target-CAD opening, editability, and PMI acceptance as separate results.
Use the permitted host for domain downloads; verify complete file hashes. Local-path outputs use returned server paths.
Deliver only artifacts supported by the selected profile, with their actual validation and review statuses.

## Preserve evidence and control retries

Keep each request, correction reason, tool version, input hash, part revision, and returned artifact hash in the run evidence.
Use server-returned hashes for bindings. If a local hash is necessary, use the documented serialization for that contract.
A reformatted JSON file can have a different byte hash without a model change.
Keep the exact transmitted payload distinct from the server's normalized description.

Continue targeted corrections while useful progress is possible within the agreed run budget.
Do not repeat the same failed payload without a reason to expect a different result.
After a lost response, inspect stored state before another mutation.
Reuse a job idempotency key only for an identical request.
If the next correction needs unavailable information or tooling, record the precise blocker and last proven checkpoint.
Do not replace a failed or unperformed check with a success claim.
