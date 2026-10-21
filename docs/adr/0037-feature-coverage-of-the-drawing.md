# 37. Feature coverage of the drawing

Date: 2026-10-21

## Status

Accepted. Extends the PDF verification of [ADR 0032](0032-independent-verification-of-the-final-drawing-pdf.md),
its acceptance gate ([ADR 0033](0033-drawing-acceptance-gate.md)), and the dimension values of [ADR 0036](0036-dimension-values-against-the-step-geometry.md).
Implemented in `drawing2cad-mcp/src/drawing2cad_mcp/feature_coverage.py` and `pdf_verifier.py`.

## Context

The PDF verification checked that the model edges of each drawn view are present (`MODEL-01`), that each round model edge of an
orthographic view has a radius or diameter dimension (`DIM-03`), and that each dimension states the model value (`DIM-06`).
It did not check that the drawing as a whole shows and dimensions each feature of the STEP model.
A feature that no view shows, or a feature without a size or a position dimension, could be missing from an accepted drawing.

The feature references of the drawing specification cannot identify the features: a derived view gives all its primitives the same
`feature_ids`. The STEP file has no feature names.

## Decision

- The verifier derives a feature inventory from the bound STEP. It does not use the part description:
  - a round feature is a set of cylindrical faces with one axis, one radius, and one side of the material: a hole has the face normal to the axis,
    a boss has it away from the axis. Its extent along the axis comes from the face vertices,
  - a plane level is a set of planar faces with one normal and one offset, for example a face of a step, a pocket floor, or an end face.
    It keeps the box of each face.
- Only true-size views count (orthographic, section, and detail views with the scale convention `true_size`). Isometric views do not count.
- `FEAT-01`: each feature is visible in a true-size view. A round feature is visible as a circle or an arc along its axis, or across its axis
  as its outline lines within its extent. A section edge within the radius also counts, because a cutting plane off the axis cuts the cylinder
  nearer to the axis. A plane level is visible as its edge-on trace inside the projected box of one of its faces. Visible and section edges count.
  A feature that only hidden lines show fails: add a section or a view.
- `FEAT-02`: each round feature has a size dimension: a radius or diameter dimension at its circle, or a linear dimension from one outline
  to the other within its extent.
- `FEAT-03`: along each model axis and each plane normal, the plane levels and the axes of the round features across that direction are positions.
  Linear dimensions connect two positions when their anchors are at these positions along the measurement direction and at a feature of the position:
  inside the projected box of a face of the plane level, or at the center of the round feature in a view along its axis.
  All positions of a direction must be connected. The connected group with the most features is the reference. A feature outside it fails.
  A plane level has no separate size rule: the distance to the next level is its size, and `FEAT-03` checks it.
- A dimension counts for `FEAT-02` and `FEAT-03` only when `DIM-02` and `DIM-06` pass for it.
- `DIM-02` accepts an anchor at the center of a round model edge, for example the position of a hole. Before, only anchors on an edge passed.
- A feature with an uncertainty marker at one of its edges gets `needs_review` instead of `fail`. The acceptance gate then requires a review decision.
- `FEAT-01`, `FEAT-02`, and `FEAT-03` are mandatory rules. Without a model projection of the bound STEP, they are `not_tested`.
  They are not applicable when the inventory has no feature, and `FEAT-02` is not applicable when it has no round feature.
- `FEAT-04` (`not_tested`, not mandatory) lists the faces outside the inventory, for example cones of chamfers and tori of fillets.
- The verification report has the section `feature_coverage`. It lists each feature with its views, size dimensions, positions, markers, and status.
- `DIM-05` expects the dimension line of a linear dimension only beside the value. The value is centered on the line and interrupts it.

## Consequences

- A delivered drawing shows each round feature and each plane level of the bound STEP, gives the size of each round feature,
  and locates each feature by a chain of dimensions, or the drawing is not accepted.
- Positions are only checked along model axes and plane normals. A round feature with an inclined axis is not located along other directions.
- Polar dimensions (a pitch circle diameter and an angle) do not connect positions. Dimension hole positions with linear dimensions between centers.
- A chamfer, a fillet, a cone, or a free-form surface is not in the inventory. `FEAT-04` reports these faces as not tested.
- A pattern of equal holes needs a size dimension for each hole. A note such as "4x" is not read.

## Tests

- `drawing2cad-mcp/tests/test_feature_coverage.py`: the flange inventory (seven round features and three plane levels);
  a completely dimensioned plate passes; missing size, position, and thickness dimensions fail; a dimension that failed its value check does not count;
  a linear dimension across the outlines gives the size; a feature that only hidden lines show fails, and a marker makes it a review item;
  other surfaces are listed as not tested; isometric views do not count; an edge outside the extent of a hole or beside the faces of a plane level
  does not count, and a dimension to it does not locate the face; a section off the hole axis shows the hole; an empty inventory is not applicable.
- `drawing2cad-mcp/tests/test_pdf_verification.py`: each feature of the flange drawing is visible, sized, and located;
  without the disc thickness and the hole positions, the four holes and the disc face fail `FEAT-03`;
  without the bound STEP, the feature rules are `not_tested`.
