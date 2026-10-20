# 29. Drawing contract 2.0 with projection, sheet, and GPS data

Date: 2026-10-19

## Status

Accepted. Extends the drawing contract of [ADR 0016](0016-shared-domain-service-and-drawing-delivery.md).
[ADR 0031](0031-render-complete-drawings-from-contract-2.md) replaces the section "Rendering". Implemented in the MCP (`drawing2cad-mcp/src/drawing2cad_mcp/drawing_contract.py`, `drawing_contract_v2.py`).

## Context

A complete-service drawing needs an isometric view, complete sections, a border, a title block, a projection symbol, and the geometrical tolerances of the source
(see `skills/drawing2cad/references/drawing-delivery.md`). DrawingSpec 1.0 cannot declare these items:

- A view has an orientation label. The label does not rotate geometry or create a projection.
- A section is supplied geometry with a free-text cutting-plane note.
- The sheet has a title, but no border, title block fields, or projection symbol.
- Geometrical tolerances and datums are notes with literal text.

The later steps (isometric projection, section derivation, sheet rendering, GPS rendering) need structured data first.

## Decision

### Versions

- The contract accepts `schema_version` `"1.0"` and `"2.0"`. Version 1.0 stays the default of `drawing_schema` and keeps its behavior.
- A 1.0 drawing that contains 2.0 content fails with code `schema_version`. The defect names the fields. The agent changes the version or removes the fields.
- `drawing_schema` takes an optional `schema_version`. Each version gets its own JSON schema. The 1.0 schema does not contain 2.0 content.
  For 2.0, the result also describes the new content, the render limits, the isometry rule, and the GPS profile.

### Projection and views

- A view can have a `projection`: parallel, `view_direction`, `up`, right-handed, `scale_convention`, and a 2 × 3 `matrix`.
- The validator calculates the matrix from the directions and the scale convention. A supplied matrix that does not agree fails.
- View kind `isometric` needs a projection. The view direction must be a body diagonal. The projected axes must have equal lengths and be 120 degrees apart.
  A dimetric or trimetric direction fails. A label or an orientation alone does not create an isometric view.
- The scale convention `isometric_drawing` gives full-length axes (factor √1.5 of the true projection). `isometric_projection` gives the true projection.
- An orthographic view with a projection needs `true_size` and a model axis as view direction.

### Curves and sections

- Version 2.0 adds an `ellipse` primitive with an explicit `approximation_error` in mm. The value is necessary, because a later renderer can approximate the curve.
- A 2.0 section view needs a `cutting_plane` (letter, origin, normal, viewing side, source view, cutting line, evidence),
  `hatching` with boundary primitives of the view, and a `projection`.
- The validator checks the letter, the `L-L` label, the source view, the cutting line inside the source frame, the cutting-plane evidence,
  the closed hatching boundary without repeated primitives, and the agreement of the section view direction with the plane normal and the viewing side.
- When the source view has a projection, the source view must show the plane as a line, and the cutting line must be parallel to that trace.
  The projection has no translation. Thus the check does not compare `origin` with the position of the cutting line.
  When the source view has no projection, the trace check gets status `needs_review`.

### Sheet data

- Version 2.0 adds `title_block` (ISO 7200 fields), `border`, and `projection_symbol`.
- A missing border, projection symbol, title block, mandatory title block field, or isometric view is a finding with status `needs_review`.
  It is not a defect, because the source can lack the data. The agent records the item from the source or as a decision.

### GPS profile

- Version 2.0 adds `datums`, `tolerance_frames`, theoretically exact dimensions, and `unsupported_gps`.
- The supported profile is `drawing2cad-gps-1`. It contains the form, orientation, and run-out characteristics, position, coaxiality, and the modifiers M and L.
- A frame fails for an invalid declaration: a form tolerance with datums, an orientation or run-out tolerance without datums, repeated datum letters,
  an unknown or invalid datum, a tolerance value of 0 without M or L, M and L together, or a diameter zone on a characteristic without one.
- A characteristic, modifier, or datum modifier outside the profile (each datum modifier), a position tolerance without datum, and each `unsupported_gps` item get status `needs_review`. They never pass automatically.
- A pass means agreement with this bounded profile. It is not ISO conformity and not a manufacturing acceptance.

### Rendering

- The renderer does not draw 2.0 content yet. `drawing_validate` reports `render_support`.
- `drawing_render` rejects ellipses, cutting planes, hatching, theoretically exact dimensions, sheet data, and GPS data with code `render_unsupported`.
  The domain service and the worker apply this check before the worker writes a file. The check `render_support` is then `fail`. A 2.0 drawing without such content renders like a 1.0 drawing.

### Validation results

- Each result has `schema_version`, `findings`, and `render_support`. This includes schema and version failures.
  After a schema failure, `render_support` is null, and `schema_version` is null for an unknown version.
- A 2.0 result after a successful schema check also has `gps` (profile and status of each frame) and the checks
  `isometric_projection`, `gps_profile`, and `sheet_items`. A schema or version failure does not have these fields.

## Consequences

- An agent can declare and check the complete-drawing items before the renderer supports them.
- Until the renderer supports 2.0 content, the delivered drawing does not contain these items. The coverage table records them as `not_tested`.
- The isometric matrix is a declaration. The contract does not derive the view geometry from the solid. Projection of the model is a separate step.
- Old 1.0 drawings stay valid.

## Tests

- `drawing2cad-mcp/tests/test_drawing_contract_v2.py`: a complete 2.0 drawing passes; an isometric view without projection, dimetric and trimetric directions,
  and a distorted matrix fail; section, hatching, and cutting-line defects; GPS defects and review findings; missing sheet items; 1.0 rejection of 2.0 content;
  the render gate; the schema versions.
- The existing drawing tests stay unchanged and pass.
