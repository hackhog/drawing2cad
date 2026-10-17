# Technical drawing delivery

The filename is retained for existing links. A drawing-first order is no longer required.
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

The maintained adapter creates DXF with native linear, radius, diameter, and angular dimension entities, plus a PDF inspection copy.
The same DXF entities supply the PDF render.
A DXF file with text and line segments alone does not prove dimension semantics.

Read `drawing_schema` for the supported declaration. Bind it to the current part revision and description hash.
Read its coordinate rules before sheet layout. Sheet positions use mm from the bottom-left corner, with +Y upward.
View origins, view frames, and note positions are absolute sheet coordinates. A frame is `[xmin, ymin, xmax, ymax]`; do not add the view origin to it.
Geometry and dimension or uncertainty-marker positions use local view coordinates. Apply `sheet_point = origin + scale * local_point` to check their sheet positions.
Reserve space for generated view labels, section notes, dimensions, and the sheet title. Check transformed bounds against both the absolute view frame and the sheet margin.
Supply view geometry, dimensions, manufacturing notes, and uncertainty markers with evidence references.
Before drawing creation, prepare two coverage tables in the run evidence:

- List each required feature and the view or section that shows it. Identify visible edges, hidden edges, centre lines, and cut boundaries.
- List each printed source dimension and its drawing dimension or group callout. Keep assumptions and user decisions in separate rows.

Compare both tables with every source view and the final model revision.
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
STEP release requires the current drawing and its accepted review, in addition to the model validation gates.

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
