# Maintained part workflow

This reference describes the shared domain service and its maintained part tools.
Use the live schemas for exact argument types, limits, and required fields.
Select the profile in [SKILL.md](../SKILL.md) first. Use only tools permitted by both the server and the client.
The installed server can differ from the skill version.
Use [verification-loop.md](verification-loop.md) for structured validation errors, rendered layout diagnostics, and correction retries.

## Discovery and validation

Call `drawing2cad_status`, `cad_capabilities`, and `cad_worker_probe`.
If the sandbox probe fails, stop the CAD workflow.
The service requires a passing probe before free-code execution; declarative builds also require the supported sandbox.
Do not replace it with a raw backend call.

Call `part_schema` to read the closed versioned schema.
Call `part_validate` with `description`.
The description contains units, coordinates, stable parameters and features, source evidence, review records, and independent measurements.
Schema 1.3 also stores manufacturing tolerances. Use [tolerances-and-changes.md](tolerances-and-changes.md) for capture and parameter-change reports.
Schema 1.4 also stores printed dimensions for cross-checks. See "Printed dimension cross-checks" below.
Use only operations and parameter references accepted by the schema.
Unknown fields, unsupported operations, invalid references, and nonfinite values require correction.

A parameter must have evidence.
An assumed value needs a reason and a source region.
Keep `explicit`, `derived`, `inferred`, `assumed`, and `unresolved` distinct.
If the drawing prints a number, keep that value `explicit` even when its feature association is uncertain.
Record the association separately as `inferred` or `assumed`, with its reason and source region.
Keep each plausible alternative open when it changes the construction type.
Build from a reasonable interpretation, then record how the alternative affects source-review coverage.
Use a supported closed review status.
A reasonable geometric assumption can support construction without a new user question.
An unresolved value that prevents a reasonable build remains a blocker.

## Construction and revisions

| Tool | Use |
|---|---|
| `part_create` | Supply `run_id`, `description`, and `sources`. Domain sources use uploaded `source_id`, `sha256`, and `role`. Local sources use authorized `path`, `sha256`, and `role` (`construction` or `verification`). |
| `part_read` | Supply `run_id`; read the description, revision, results, and budget. This call is recorded. Audit access remains available after the execution budget is reached. |
| `part_update` | Supply `run_id`, `expected_revision`, and the changed `description`. Prior builds and releases become stale. |
| `create_base_body` | Add a supported box, cylinder, polygon extrusion, or closed line-and-arc profile extrusion. |
| `add_hole` | Add a through or blind hole, with supported countersink, counterbore, or thread data. |
| `add_pocket`, `add_cut` | Add a supported material-removal feature. |
| `add_chamfer`, `add_fillet` | Apply edge treatment with a bounded selector and expected selection count. |
| `build_from_description` | Build the stored description, export a candidate, and re-import in a separate worker. It does not release the candidate. |
| `build_code` | Optional in-memory execution within the separately verified sandbox scope. |

Read the current revision before a mutation.
Model edits increment the revision and invalidate prior builds and releases.
Supply `run_id` and `expected_revision` for each mutation.
Granular calls also take a typed `feature`.
The minimum path does not use `build_code`. Use it only when explicitly requested, listed, and permitted by the client.
`build_code` takes an in-memory `code` string and must assign the resulting build123d shape to `result`.
The namespace supplies `build123d` and a separate copy of the current `description`.
Read named parameters from that description. Do not keep a second set of unlinked model values in code.
Changes to this copy cannot change the trusted validation description.
Free-code output has separate geometry validation; feature replay remains unverified.
Retain the exact inline payload in the event trace.
To test a parameter change, update the description and rerun that payload.
JSON alone cannot replay construction that exists only in the inline payload.
Do not substitute `build_from_description` and claim equivalent replay without a separate comparison.
After a lost response, read state before another call.
Do not repeat an old mutation with a guessed revision.
Keep mutations to the same part in sequence.
The server counts part-service calls against its run budget.
For a domain run with likely corrections, `step_budget=45` is a useful starting value within the live server limits.
Keep the client's total tool-call budget separate; it can also count discovery, PDF, upload, and download calls.
After the budget is reached, `part_read` and `part_export_review` remain available for audit.
These calls cannot enable more construction or release operations.
Reserve calls for one final diagnostic build, `export_step`, and `part_export_review`.
The agent separately tracks the overall budget, including PDF preparation, discovery, and retries.

Jobs are optional for domain clients that permit `job_submit` and `job_get`. Other clients use synchronous calls.
The bounded local-model runner does not permit job tools.
The operation arguments keep their normal revision requirements.
Supply a unique idempotency key for a new request. An exact retry uses the same key; changed arguments require a new key.
Inspect `job_get` for the terminal state and actual result. A submitted or running job is not a successful operation.
Queued cancellation prevents execution. A running operation can finish with effects after cancellation is requested.
After a service restart, queued jobs resume and unfinished active jobs become `interrupted`. Inspect the run before a replacement request.
The queue has a finite pending-job limit. Do not repeatedly submit when it reports `JOB_QUEUE_FULL`.
If the profile supplies notes tools, use `notes_read` and `notes_update` for run notes.
Their revision is separate from the part revision.

The description is the editable source for the declarative M1 path.
Changing a stored number alone does not prove editability.
Rebuild the changed description and measure the intended geometric effects.
Scalar references update their direct uses. The prototype does not have an algebraic constraint solver.
Derived profile points and edge selectors can require coordinated edits after a dimension change.

Closed profiles can contain straight lines and three-point circular arcs.
Before a profile extrusion or cut, inspect the coordinate basis in the live `part_schema`.
Profile points use local coordinates. The feature origin uses global coordinates.
Use the declared local X, Y, and Z basis to map each profile point into the part.
Do not infer the two profile axes from the extrusion axis name.
For example, a positive Y extrusion can map positive local y to negative global Z.
Check the transformed profile bounds before construction, especially for non-Z and negative-axis features.
Extrusions support a bounded draft angle. Blind holes can include an explicit drill-tip angle.
The blind depth is the cylindrical depth; the conical tip extends beyond it.
Schema 1.2 and later permit `thread.length` on a plain blind hole. Measure this length from the hole entry along the inward axis.
Keep `depth` as the full cylindrical tap-drill depth. For example, a 9 mm M6 thread in a 14 mm blind bore uses one hole feature with `thread.length` set to 9 mm and `depth` set to 14 mm.
The length must be positive and no greater than the bore depth. If length is absent, the thread length is unspecified.
The build and fresh STEP import check the entry, tap-drill diameter, and full cylindrical depth against this attribute. This check does not verify helical geometry or semantic PMI.
Schema 1.1 also supports tapered cuts and pockets. Use [draft-and-fillets.md](draft-and-fillets.md) for their direction and validation rules.

Use the 15 current measurement examples returned by `part_schema` to select a kind and its required anchors.
Do not reuse an example position without placing it on the source feature.
Use `arc_radius` for a circular profile edge. Use `outer_diameter` for a cylindrical outer face.
For `outer_diameter`, put the axis position at a station inside the intended cylindrical face.
Inspect the returned station and ambiguity details before accepting a stepped-shaft diameter.
Use `axis_distance` for two distinct axes, not for length along one axis.
For `plane_distance`, put both anchors on material faces, outside bores and axes.
`section_distance` measures two trimmed planar faces along one line. It can measure a drafted rib at a selected height.
Both anchors must lie on that line. `surface_radius` measures a cylindrical face near its surface anchor, including a trimmed fillet.
Do not use an axis-center anchor for `surface_radius`.

For a hole opening check, supply source-derived `entry_position` and an axis that points into the part.
The entry must lie on the measured hole axis.
The entry check supports connected full concave cylinders, cones, and planar shoulders at a planar circular opening.
A stepped bore (counterbore, countersink, or a smaller bore below a larger bore) is one connected cavity.
Use the outer opening as `entry_position` for each of its bores. An internal shoulder is not an entry.
If a check reports `entry_side: fail`, compare `actual_entry_positions` with this rule before you change the geometry.
Toroidal lips and partial or noncircular transitions are outside this check.
If `entry_position` is omitted, `entry_side` remains `not_tested`.
A cylindrical diameter/depth pass alone does not prove the correct entry side.

Thread data in M1 describe a tap-drill representation and thread attributes.
They do not prove modeled helical flanks or semantic thread PMI in STEP.

## Drawing and review

This section applies to the domain profile. The local-path metric skips drawing tools.

Read `drawing_schema` and prepare DrawingSpec 1.0 with the current `part_revision` and `description_sha256` from `part_read`.
After a passed build, `drawing_derive_views` derives orthographic, isometric, and section views. A 2.0 view refers to one with `derivation`.
DrawingSpec 2.0 adds declarations that `drawing_validate` checks. `drawing_render` renders projections and isometric views with line, circle, and arc geometry.
It rejects ellipses, cutting planes, hatching, theoretically exact dimensions, sheet data, and GPS data (see drawing-delivery.md).
Supply 2D views, line/circle/arc geometry, feature and evidence references, dimensions, notes, and uncertainty markers.
Drawing scalar references can use a parameter, factor, and offset. Rebind and regenerate after model changes.
Use `drawing_validate`, then `drawing_render` with `run_id`, `expected_revision`, and `drawing_spec`.
The worker produces DXF with native dimensions and a PDF rendered from those same entities.
This is supplied view geometry; automatic solid projection and section extraction are unsupported.

Inspect the PDF and layout report. Compare geometry, dimensions, sections, and manufacturing data with the permitted source and measured model.
Either drawing or model may be created first. The final accepted review must follow the current model build.
Use `drawing_review` with the current drawing hash, part revision, construction-source hashes, reviewer, decision, and reason.
A model rebuild invalidates a previous drawing review even if the part revision did not change.
The review is an identified attestation. It does not convert untested automatic drawing-to-solid equivalence into a pass.
Use [drawing-delivery.md](drawing-delivery.md) for the visual review and delivery requirements.

## Validation, export, and reports

Inspect the returned build status and each measurement.
Feature creation is not proof that the intended source feature was interpreted correctly.
Compare actual geometry with independent drawing expectations.
Use [validation.md](validation.md) for separate claims.

The build creates a candidate and runs fresh-worker re-import before release.
`export_step` requires `run_id`, `expected_revision`, and `coverage`.
Coverage identifies the reviewer, source hashes, view/feature/printed-dimension totals and reviewed counts, and critical measurement IDs.
Include the reason for the review conclusion.
The service verifies the evidence structure; the attestation does not prove that the reviewer interpreted every source correctly.
Keep a separate inventory that links each printed callout to its geometry check.
Include every printed fillet radius and chamfer in that inventory, even when its edge is visually small.
Compare each entry with the final feature list and model measurement.
The reviewer must also check features that do not have dimensions, such as a visible web or a drill tip.
Do not replace a failed local check with a bounding-box check that does not measure the same feature.

Release requires trusted re-import, passing source-dimension checks, and complete source-review coverage.
Domain release does not require a drawing review. The release records the current drawing status and its files, or the reason why no drawing exists.
An identified acting-agent attestation is sufficient for the metric; a separate reviewer is optional when available.
Record the actual AP214 schema, units, product identity, and geometry.
A passed re-import does not prove STEP-only feature reconstruction.

Call `part_export_review` with `run_id` and `expected_revision` for review records, coverage, manifest, and event evidence.
A permitted domain host uses `artifact_get` and `artifact_read` to download outputs and verify each complete file hash.
The bounded local-model runner returns artifact IDs and hashes to that host; it cannot call these download tools.
Local-path tools return server output paths.
Artifacts are immutable snapshots. A later run revision does not replace an earlier artifact ID.
Keep unexecuted target-CAD opening, independent conformance, model comparison, and PMI tests as `not_tested`.
A successful server operation is not a complete metric pass when required external checks are missing.

## Legacy evidence and STEP tools

This section is optional and outside the minimum path. Use these tools only when the server and client permit them.

The `workflow_*` tools retain a separate legacy evidence profile.
They are hidden by default; `server.expose_legacy_workflow=true` explicitly enables that development profile.
They register structural evidence, revisions, and review attestations.
They do not execute CAD or replace the part service's build/export validation.
Do not use a caller-supplied attestation as measured geometry.

The bounded STEP readers remain useful for inspection:

- `step_inspect`: syntax, references, and entity inventory.
- `step_read_procedural`: the declared construction subset.
- `step_read_pmi`: supported nominal dimensions and associations.
- `step_read_review_properties`: application metadata envelopes.
- `step_append_review_properties`: metadata in a separate candidate.

In the domain profile, the read-only tools use an authorized `artifact_id` and its exact-byte `expected_sha256`.
`step_append_review_properties` is not part of that profile. The local-path development profile retains its older path-based inspection tools.
Their parsing success does not prove geometry, full EXPRESS conformity, or general PMI support.
A metadata append is not CAD export or semantic-PMI authoring.

Historical FreeCAD inline adapters are unavailable through the current MCP.
Do not load them for the current tool sequence.

## Printed dimension cross-checks

Schema 1.4 has an optional `dimensions` list. Each item records one printed dimension: `id`, the unchanged `printed_text`, the `nominal` value, the `unit` (`mm` or `deg`), and `evidence_ids` for its view and region.
The list does not change the construction. Parameters and features keep their own values and evidence.
Add these optional fields to make the cross-checks possible:

| Field | Use | Check in `part_validate` |
|---|---|---|
| `chain` | `{"id": ..., "role": "part"}` for each element of a dimension chain, `{"id": ..., "role": "total"}` for the overall dimension of the chain. | The parts must add up to the total. |
| `dim_id` | The same value for each occurrence of one physical dimension in different views. | All occurrences must have the same nominal value. |
| `measured` | `{"value": ..., "method": ...}` with the size measured at the calibrated scale of the view. | The difference from the nominal value must not exceed the larger of 0.2 mm (0.5 deg) and 1 % of the nominal value. |
| `not_to_scale` | `true` for a dimension marked as not to scale. | The measured value is not compared. |

A failed check is a defect (`dimension_chain`, `dimension_views`, `dimension_measured`, or `dimension_unit`) with a pointer, the identifiers, and the numbers.
Correct the reading, the calibration, or the chain assignment. If the drawing itself is inconsistent, record the conflict as a review flag and remove the incorrect link.
`dimension_checks` in the result lists each check as `pass`, `fail`, or `not_tested`. A check without the necessary data is `not_tested`. Do not report it as passed.
