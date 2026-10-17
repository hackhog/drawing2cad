# Technical drawing delivery

The filename is retained for existing links. A drawing-first order is no longer required.
Create both the technical drawing and the 3D model for the complete service.
Either artifact can be created first. Compare their final revisions before delivery.

The M1 prototype delivers a validated STEP candidate and an editable JSON part description.
It does not satisfy the complete drawing deliverable.
The M2 milestone adds the dimensioned technical drawing and its headless rendering.

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

The proposed default is DXF with native dimension entities, plus a PDF preview.
This format choice remains subject to the M2 adapter tests.
A DXF file with text and line segments alone does not prove dimension semantics.

## Review and consistency

1. Inspect the rendered sheet and necessary details.
2. Verify values against source evidence and recorded assumptions.
3. Verify view directions, section arrows, section letters, and rotated-section labels.
4. Inspect text, symbols, spacing, clipping, and review markers.
5. Compare measured model geometry with the final drawing revision.
6. Record each finding and its disposition.
7. Repeat affected checks after a drawing or model change.

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
