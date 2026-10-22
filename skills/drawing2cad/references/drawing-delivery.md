# Technical drawing delivery

Create both the technical drawing and the 3D model for the complete service.
Either artifact can be created first. Compare their final revisions before delivery.

The STEP-only profile delivers a validated STEP file and an editable JSON part description.
It does not satisfy the complete drawing deliverable.
The domain profile supplies dimensioned DXF and PDF rendering from an explicit drawing specification.

## Drawing requirements

Use a supported drawing adapter through `drawing2cad-mcp`.
Do not create a sheet with hand-written SVG or ad hoc model scripts.
Sketcher profiles, raw projected edges, and a copy of the input PDF are insufficient.

The drawing must include:

- A stable drawing ID, revision, units, projection method, and scale.
- Views and sections that fully describe the required shape.
- Dimensions tied to the correct geometry, including thicknesses, depths, and hole positions.
- Required source manufacturing data, including threads, finish, material, and tolerances.
- Readable identifiers for assumptions and unclear details.
- An editable sheet and a rendered inspection artifact from the same revision.

## Required content of a complete-service drawing

A complete-service drawing has all of these items. Each item is a row of the coverage table.

1. **Isometric view.** Add an isometric view of the part in addition to the necessary orthographic views and sections (ISO 5456-3).
   An isometric view has equal axis scales and 120-degree axes in parallel projection. An axonometric label alone is not an isometric view.
   An isometric view does not replace dimensioned orthographic views or sections.
2. **Orthographic views.** Use the views that the shape needs (ISO 5456-2). Use the projection method of the source.
3. **Sections.** Add each section that the source shows, and each section that an internal feature needs (ISO 128-3).
   A section shows the cutting line with arrows and letters in its source view, the complete section boundary, and hatching.
   A set of isolated lines is not a section.
4. **Dimensions.** Show each printed source dimension at the geometry that it controls (ISO 129-1).
   The drawing contract supports millimeters only. For a source in other units, convert the value to mm, and keep the source value and unit in the coverage table.
   Record the presentation in the source unit as `not_tested`.
   Do not repeat the same callout without a reason. Show thicknesses, rib widths, depths, and hole positions.
5. **Manufacturing data.** Show threads, surface requirements, material, general tolerances, and geometrical tolerances that the source states.
   Show a requirement that is not in the source only when it is a recorded user decision. Mark it as a user decision, separate from source requirements.
   Do not add other requirements. A missing requirement is a row with its recorded decision (see tolerances-and-changes.md).
6. **Sheet.** Show the drawing border, the title block (ISO 7200 fields), the projection symbol, the units, the scales (ISO 5455), and the revision.
7. **Assumptions.** Mark assumed or inferred geometry, for example assumed hole positions or drill tips. Keep it separate from source requirements and user decisions.

## Coverage table

Record a source-to-output coverage table in the run evidence before `drawing_review`. Keep it current after each drawing or model change.
Each row has these fields:

| Field | Content |
|---|---|
| `item` | The feature, dimension, view, section, manufacturing note, sheet item, or GPS requirement |
| `kind` | `feature`, `dimension`, `view`, `section`, `manufacturing`, `sheet`, or `gps` |
| `source` | The source view and region, or `none` for an item that the source does not show |
| `origin` | `source`, `assumed`, `inferred`, or `user_decision` |
| `output` | The drawing view, section, dimension, or note that shows the item, or `missing` |
| `status` | `covered`, `missing`, `needs_review`, `not_tested`, or `not_applicable` |
| `reason` | Necessary for each status except `covered` |

Use `not_applicable` only with an applicability reason. Use `not_tested` when the tools cannot produce or check the item.
Compare the table with every source view and the final model revision. A row with `missing`, `needs_review`, or `not_tested` blocks an unqualified complete-drawing claim.
Report the open rows in the final report and in `drawing_review`.

## Current tool limits

The tools cannot yet supply each required item. Do not hide a limit with a work-around.

- Use DrawingSpec 2.0 (`drawing_schema` with `schema_version: "2.0"`) for a complete-service drawing. It declares isometric projections,
  sections with cutting planes and hatching, ellipses, the title block, the border, the projection symbol, datums, and tolerance frames.
  `drawing_render` draws all of them. Keep the view frames off the title block at the bottom-right corner.
- Use `drawing_derive_views` for orthographic, isometric, and section views of the validated build. Do not calculate view geometry by hand.
  Refer to each derived view with `derivation` in DrawingSpec 2.0, and add the frame, origin, scale, label, and dimensions.
  Derive the views again after each model change. A stale derivation fails with `derivation_stale`.
- A view with `orientation: "custom"` is not an isometric view. Do not draw hand-calculated isometric lines and call them an isometric view.
- Record each title block field from the source or as a user decision. An empty field is a `needs_review` finding.
- Record each source GPS requirement as a tolerance frame or a datum when the GPS profile supports it.
  Otherwise record it in `unsupported_gps`: the drawing shows it with a red REVIEW mark, and its row stays `needs_review`.
  Do not write a tolerance as a note. A note that looks like a tolerance gets the finding `gps_free_text`.
  A validation pass of a frame is evidence for the declaration only, not for ISO conformity.
- Call `drawing_verify` with the PDF artifact of the final drawing and its SHA-256. It checks the stored PDF bytes against the bound model.
  Record its status in the coverage table. A `fail` or `not_tested` mandatory finding blocks the acceptance; correct the drawing, render it, and verify it again.
  A `needs_review` finding blocks until `drawing_review` decides it in `verification_decisions` with a reason. Do not decide a finding that you did not check.
  A stale verification (`drawing_read`) is not evidence. `drawing_read` returns `acceptance` with the blocking findings.
- The drawing status is `accepted` only after an accepted review of the current verification report. Otherwise it is `unverified`.
- `DIM-06` measures each dimension on the bound STEP geometry. A declared value that differs from the model value fails, also when the specification agrees with itself.
  Dimension features only in orthographic or section views: a dimension in an isometric view fails as not true size.
- `FEAT-01` to `FEAT-03` check each feature of the bound STEP: round features, chamfers, fillets, plane levels, and free-form surfaces.
  Each feature must be visible in a true-size view, not only as hidden lines.
  Each round feature needs a radius or diameter dimension, or a linear dimension from one outline to the other.
  Each chamfer needs two different sizes. Give an angle (an angular dimension with a leg on the chamfer) and a length, or give two lengths.
  Two lengths of a chamfer of a straight edge must have different model directions. The same length in a second view with another orientation
  is the same size. Two diameters at one end of a countersink are one size.
  A countersink needs a diameter and an angle or a depth. The diameters at its two ends do not give its angle or its depth.
  An inclined face (a face with a normal that is not a model axis) needs two sizes. It needs no dimension chain along its normal.
  A chamfer note such as "2 x 45°" does not count.
  Each fillet needs a radius dimension at its profile arc, in a view across the axis of the fillet.
  A groove, a bead, or a ring needs the radius of its profile arc and its size across the axis, for example the diameter of the groove bottom.
  Along each model axis, the plane levels and the hole axes
  must be connected by linear dimensions. Dimension the thickness of each step and the position of each hole from an axis or a face.
  Dimension the depth of a blind hole to the end of its cylinder. A dimension to the tip of the drill point does not locate the hole end.
  Dimension the depth of each blind hole, also when two blind holes share one axis.
  A partial cylinder (a fillet of a straight edge or the end of a slot) needs its radius, but its adjacent faces locate it.
  It is not a `FEAT-03` position. A groove needs an axial position dimension to the center of its profile arc.
  `FEAT-03` is not applicable when the model has only free-form surfaces.
  Use linear dimensions between hole centers: a pitch circle with an angle does not count as a position.
  A free-form surface (for example a B-spline surface or a sphere) has no supported size dimension.
  Show it and mark it with an uncertainty marker at one of its boundary edges. A section curve through the inside of the surface does not count.
  Its finding is then `needs_review`, and `drawing_review` must decide it.
  Mark any other feature that you cannot dimension with an uncertainty marker. Its findings are then `needs_review`.
  `DIM-05` does not test the lines of angular dimensions in the raster. An angular dimension blocks the acceptance until its lines are checked in the raster.
- Verify a supplied source drawing with `source_id` only as an inspection aid. Without a binding, the model rules are `not_tested`.

With these limits, the drawing status can be `accepted` for the supported content, but the final report must name the open rows.
It must not claim a complete technical drawing or conformity with the ISO standards above.

The maintained adapter creates DXF with native linear, radius, diameter, and angular dimension entities, plus a PDF inspection copy.
The same DXF entities supply the PDF render.
A DXF file with text and line segments alone does not prove dimension semantics.

Read `drawing_schema` for the supported declaration. Bind it to the current part revision and description hash.
Read its coordinate rules before sheet layout. Sheet positions use mm from the bottom-left corner, with +Y upward.
View origins, view frames, and note positions are absolute sheet coordinates. A frame is `[xmin, ymin, xmax, ymax]`; do not add the view origin to it.
Geometry and dimension or uncertainty-marker positions use local view coordinates. Apply `sheet_point = origin + scale * local_point` to check their sheet positions.
Reserve space for generated view labels, section notes, dimensions, and the sheet title. Check transformed bounds against both the absolute view frame and the sheet margin.
Supply view geometry, dimensions, manufacturing notes, and uncertainty markers with evidence references.
A line anchor is `start`, `end`, or `center` (midpoint). An arc anchor is `center`, `start`, or `end`. A circle anchor is `center`, `left`, `right`, `top`, or `bottom`.
Layout defects give the computed sheet bounds. Clipping defects for view geometry and view labels also give the view transform. Use these values to move the label, the geometry, or the view frame.
A marker leader goes from the marker label to its primitive. If the leader crosses another label, `drawing_validate` reports `leader_overlap`. A leader that starts or ends inside a label is not a crossing.
Put a marker at each projected feature that depends on assumed, inferred, or unresolved evidence or on a review flag. The defect message names the evidence status and the link (feature evidence, parameter, primitive, or review flag). Explicit evidence without a review flag needs no marker.
For wall draft and inside fillets, apply [draft-and-fillets.md](draft-and-fillets.md).
Use angular and radius dimensions plus scoped notes. Compare general requirements with the source and final model measurements.
Before drawing creation, prepare the coverage table (see "Coverage table").
For each feature, name the view or section and its visible edges, hidden edges, center lines, and cut boundaries.
For each printed source dimension, name its drawing dimension or group callout. Keep assumptions and user decisions in separate rows.
Use `drawing_validate`, then `drawing_render`. Keep its returned DXF, PDF, and layout-report hashes.
Inspect the rendered drawing for missing internal features, incorrect visibility, gaps, and misleading overlaps.
A passed layout check does not prove feature coverage or agreement with the model.
Use `drawing_derive_views` for supported model projections and sections. Review section geometry and its identifying note.
The PDF verifier compares supported model edges and annotations. It does not prove arbitrary drawing-to-solid equivalence or general GD&T conformity.
Semantic PMI requires separate tests.
Passing layout checks cannot prove that the source was interpreted correctly or that the selected views are sufficient.

## Review and consistency

1. Inspect the rendered sheet and necessary details.
2. Verify values against source evidence and recorded assumptions.
3. Verify view directions, section arrows, section letters, and rotated-section labels.
4. Inspect text, symbols, spacing, clipping, and review markers.
5. Compare measured model geometry with the final drawing revision.
6. Record each finding and its disposition.
7. Repeat affected checks after a drawing or model change.

Record `drawing_review` with the current drawing hash, part revision, construction-source hashes, reviewer, decision, and reason.
The final accepted review must follow the current model build. Rebuilding the model invalidates an earlier review.
This is an identified review attestation. Automatic drawing-to-solid equivalence remains `not_tested`.
Complete-service release requires an accepted drawing verified against the released STEP bytes. Use `delivery: "complete_service"`.
Confirm `pair_current: true` on the final `part_read`. A new drawing, verification, or review makes an earlier pair stale.
An explicitly requested STEP-only release records the actual drawing status without claiming a verified pair.
The local-path STEP-only profile does not supply drawing tools. Its result does not establish complete-service drawing delivery.

A drawing can reveal a model error. Do not change the source requirement to conceal that error.
A changed design requires a new revision and a recorded reason.
Keep earlier evidence unchanged.

Use reasonable geometric assumptions for missing data.
Record their source region, reason, value, and affected feature.
Keep each assumption visible in the review list and final drawing.
Block only when no reasonable assumption can support the required construction.

## STEP-only tests

For an isolated STEP-only reconstruction test, STEP is the only source of model content.
A drawing can support a later independent comparison.
It must not supply missing construction, parameters, PMI, or anchor data during reconstruction.

Record drawing delivery and drawing/model consistency separately from STEP-only reconstruction.
A passed geometry import does not prove editability or semantic PMI.
