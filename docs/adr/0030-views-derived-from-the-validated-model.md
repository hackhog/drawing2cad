# 30. Views derived from the validated model

Date: 2026-10-19

## Status

Accepted. Uses the drawing contract 2.0 of [ADR 0029](0029-drawing-contract-2-with-projection-sheet-and-gps-data.md).
Implemented in the MCP (`drawing2cad-mcp/src/drawing2cad_mcp/derived_views.py`, `view_derivation.py`, `domain_service.py`).

## Context

DrawingSpec 2.0 can declare an isometric projection, a section with a cutting plane and hatching, and ellipses.
The agent must still write each primitive by hand. Hand-written view geometry can disagree with the model,
and an agent cannot calculate an isometric view or a section of a complex part reliably.

`model_projection_check` projects the build into axis-aligned views, but only to compare it with the source.
It does not give drawing geometry.

## Decision

### Tool

- The new domain tool `drawing_derive_views` derives up to 8 views from the current validated build.
  It needs a passed build of the current revision. The service checks the candidate path and hash before the worker starts.
- The derivation runs in the restricted headless worker (operation `derive_views`). It uses the hidden-line removal of OpenCASCADE.
  No step needs a GUI.

### Requests

- A request has `id`, `kind` (`orthographic`, `isometric`, `section`), `up`, and `view_direction` (not for a section).
- The service calculates the projection matrix with the rules of ADR 0029 and checks it before the worker starts.
  An isometric request with a direction that is not a body diagonal fails as dimetric or trimetric.
  A perspective request fails, because the drawing views need a parallel projection. A request cannot supply its own matrix.
- A section request has a cutting plane (letter, origin, normal, viewing side, source view). The view direction points from the part
  toward the viewer: it is the normal for `positive_normal` and minus the normal for `negative_normal`.
  The source view must be another requested view that shows the plane as a line.

### Output

- Local view coordinates are the matrix applied to the model point. The projection has no translation.
- Each view is a DrawingSpec 2.0 view draft without evidence and feature references:
  - visible edges, and hidden edges (default for orthographic views only),
  - center lines of cylinder axes in the view plane, and center marks of axes along the view direction (not in isometric views),
  - lines, circles, arcs, and ellipses from the exact curve type, also on cut surfaces, with `approximation_error` 0 for an ellipse,
  - other curves as polylines with an error of at most 0.01 mm: deflection-controlled sampling (0.005 mm) and a simplification (0.005 mm).
    Curves below C2 continuity use the quasi-uniform deflection algorithm.
    The worker measures the error at each sample and at 15 points between each pair of samples. Above 0.01 mm, it keeps all samples.
    If the error is then still above 0.01 mm, the view fails with `VIEW_TOO_COMPLEX`.
    The view records the measured maximum error and the affected primitives.
- A section removes the material between the viewer and the plane. It gives the cut surfaces as `section` primitives,
  one closed hatching boundary for each cut surface, and the visible edges behind the plane without hidden edges.
  The cutting line is the trace of the plane in the source view. It extends 5 mm past the part outline on both sides.
- A view has at most 300 primitives, a curve at most 2,000 points, a cut surface at most 100 boundary primitives, and a section at most 20 cut surfaces,
  as DrawingSpec 2.0 permits. A view that exceeds a limit fails with `VIEW_TOO_COMPLEX`.
- When the kept material has more than one piece, the section uses all pieces.
- A face of the part that was already on the cutting plane is not a cut surface. A plane that only touches the part fails.
- The tool result omits geometry when it exceeds 60,000 characters. The JSON artifact `derived-views.json` contains all of it.

### Binding and stale views

- The service stores the last derivation with its binding: part revision, description hash, and build candidate hash.
  `derivation_sha256` is the hash of the binding and the views.
- A DrawingSpec 2.0 view can refer to a derived view with `derivation`: `derivation_sha256`, `view_id`, `feature_ids`, and `evidence_ids`.
  Before `drawing_validate` and `drawing_render`, the service puts the derived geometry, projection, cutting plane, and hatching into the view.
  The agent supplies the frame, the origin, the scale, the label, and the dimensions. The agent's own primitives follow the derived ones.
- Each derived view can occur once in a drawing. The drawing can give a derived view another id.
  The source view of a derived section must also be a derived view of the drawing; the service changes `source_view_id` to its drawing id.
- The service checks each reference and the total number of derived primitives (at most 3,600) before it copies geometry.
  An invalid reference fails with `derivation_invalid`.
- A reference to another derivation, or a derivation of another revision or build, fails with `derivation_stale`.
  A view that supplies its own projection, cutting plane, or hatching fails with `derivation_mismatch`.
- `drawing_read` reports the stored derivation with status `current` or `stale`.

## Consequences

- Isometric views and sections come from the solid. The agent does not calculate them.
- The renderer cannot draw ellipses, cutting planes, or hatching yet (ADR 0029). Until it can, a drawing with derived isometric views or sections validates but does not render.
- All derived primitives of a view get the same feature and evidence references. A finer assignment to features is not part of this decision.
- The derivation does not check the plane origin against the source view position, because the projection has no translation.
  The derivation sets the cutting line from the origin, so the two agree for a derived view.

## Tests

- `drawing2cad-mcp/tests/test_view_derivation.py`: an asymmetric block gives an isometric view with equal axis scales and 120-degree axes;
  dimetric, perspective, non-axis orthographic, and matrix requests are rejected; local coordinates are the matrix times the model point;
  a flange gives top, front, isometric, and a complete section view; a model change changes the derived geometry;
  the derived flange views validate as DrawingSpec 2.0 except for the dimensions that the agent adds; the derivation runs in the verified sandbox.
- `drawing2cad-mcp/tests/test_derived_views_service.py`: binding to the validated build, artifact registration, `drawing_read` status,
  rejection before the worker, use of the derived geometry, stale detection after a model change, and the mismatch rule.
