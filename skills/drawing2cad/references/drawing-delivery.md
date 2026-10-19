# Technical drawing delivery

Create both the technical drawing and the 3D model for the complete service.
Either artifact can be created first. Compare their final revisions before delivery.

The M1 prototype delivers a validated STEP candidate and an editable JSON part description.
It does not satisfy the complete drawing deliverable.
The M2 domain profile supplies dimensioned DXF and PDF rendering from an explicit drawing specification.

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

- The drawing contract has no isometric camera and no projection matrix. A view with `orientation: "custom"` is not an isometric view.
  Do not draw hand-calculated isometric lines and call them an isometric view. Record the isometric row as `not_tested` with this limit.
- The adapter does not derive views or sections from the solid. It has no cutting-plane definition.
  Supply section geometry, the cutting line, arrows, and letters explicitly, and review them against the model. Record automatic section derivation as `not_tested`.
- The renderer draws a sheet title, not a complete border and title block. Record the border, title-block, and projection-symbol rows as `not_tested`.
- The contract has no structured geometrical tolerance frames, datums, or datum systems. Show a source GPS requirement as a note with its literal text,
  and record its row as `needs_review`. A note does not establish GPS semantics.
- No tool verifies the final PDF bytes independently. Record final-PDF verification as `not_tested`.

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
The adapter does not derive arbitrary projections or sections from the solid.
Section geometry and its identifying note must be supplied and independently reviewed.
Automatic drawing-to-solid equivalence, general GD&T validation, and semantic PMI are unsupported.
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
Domain STEP release requires the model validation gates, not the drawing. The release records the drawing status and its files, or the reason why no drawing exists.
The local-path metric does not require drawing tools. Its result does not establish complete-service drawing delivery.

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
