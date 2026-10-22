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
This applies to all features: holes, bosses, chamfers, fillets, plane levels, and free-form surfaces.

The feature references of the drawing specification cannot identify the features: a derived view gives all its primitives the same
`feature_ids`. The STEP file has no feature names.

## Decision

- The verifier derives a feature inventory from the bound STEP. It does not use the part description. Each face of the model belongs to one feature:
  - a round feature is a set of cylindrical faces with one axis, one radius, and one side of the material: a hole has the face normal to the axis,
    a boss has it away from the axis. Its extent along the axis comes from points on the boundary edges of its faces,
    so that inclined and curved ends count. A straight edge gives its two ends; a curved edge gives 361 points. For a circle,
    the largest gap to an extreme point is then less than 0.05 mm up to a radius of 1300 mm,
  - a conical feature (`cone`) is a set of conical faces with one axis, one apex, one angle, and one side of the material (hole or boss).
    It is a chamfer of a round edge or a countersink. It has the radius at each end of its extent and its half angle,
  - a torus feature (`torus`) is a toroidal face with one axis, one center, a major radius, and a minor radius. It is a fillet of a round edge,
  - a plane level is a set of planar faces with one normal and one offset, for example a face of a step, a pocket floor, or an end face.
    It keeps points on the boundary edges of each face. A plane level is inclined when its normal is not a model axis
    and no other plane level has the same normal. An example is the chamfer of a straight edge,
  - a free-form surface (`surface`) is one face of any other type, for example a B-spline surface or a sphere. It keeps points on its boundary edges.
- Only true-size views count (orthographic, section, and detail views with the scale convention `true_size`). Isometric views do not count.
- `FEAT-01`: each feature is visible in a true-size view. Visible and section edges count. A feature that only hidden lines show fails: add a section or a view.
  - A round feature is visible as a circle or an arc along its axis, or across its axis as its outline lines within its extent.
    In a section, a cutting plane parallel to the axis at the distance d from the axis cuts the cylinder at sqrt(r² − d²) from the axis.
    A section edge there counts. A cutting plane that does not cut the cylinder gives no section edge of it.
  - A conical feature is visible across its axis as outline lines on the cone, between the radii at the ends of its extent.
    A section edge counts only when the cutting plane contains the axis. Along its axis, it is visible as the circles at its end radii.
  - A torus feature is visible across its axis as the profile circles at the major radius from the axis.
    The derivation can give a profile circle as an arc or as a polyline. The arc, or the vertices of the polyline, must be on the profile circle.
    A section edge counts only when the cutting plane contains the axis. Along its axis, a torus feature is visible as the circles with the radius R + r and R − r.
  - A plane level is visible as its edge-on trace between the ends of the projection of one of its faces.
  - A free-form surface is visible when a drawn edge lies on the projected boundary of its faces.
- `FEAT-02`: each round, conical, and torus feature, each inclined plane level, and each free-form surface has its size:
  - a round feature: a radius or diameter dimension at its circle, or a linear dimension from one outline to the other within its extent,
  - a conical feature: two sizes. They are an angle (an angular dimension with a leg on an outline) and a length or diameter,
    or two lengths or diameters. A length has an anchor on an outline. A diameter is at an end circle along the axis,
  - a torus feature: a radius dimension at a profile arc, in a view across the axis. The radius is the minor radius of the torus,
  - an inclined plane level: two sizes. They are an angle with a leg on its trace and a length to its trace, or two lengths to its trace,
  - a free-form surface: no supported size dimension exists. `FEAT-02` always fails for it.
    With an uncertainty marker at one of its edges, the finding becomes `needs_review`, and the acceptance gate requires a review decision.

  A plane level along a model axis has no separate size rule: the distance to the next level is its size, and `FEAT-03` checks it.
- Ambiguity: an edge that fits more than one feature of the same group in a view does not show which feature it belongs to, and counts for none of them.
  The groups are the cylinders (holes and bosses), the cones, and the tori. Examples are the common circle of a bore below a boss with one radius,
  or the coinciding outlines of two holes behind each other. The same applies to a size dimension that fits more than one feature of the same group.
  Another view or a section must show and size these features. An edge between features of two groups counts for both.
  An example is the circle between a hole and its chamfer.
- `FEAT-03`: along each model axis and each plane normal, the plane levels and the axes of the round, conical, and torus features across that direction are positions.
  Linear dimensions connect two positions when their anchors are at these positions along the measurement direction and at a feature of the position:
  on the projection of a face of the plane level, or at the center of the axial feature in a view along its axis.
  Features at the same coordinate share a position. Thus aligned holes share their dimensions, as in a hole grid with one row of X dimensions
  and one column of Y dimensions.
  All positions of a direction must be connected. The connected group with the most features is the reference. A feature outside it fails.
  A free-form surface has no position rule.
- A dimension counts for `FEAT-02` and `FEAT-03` only when `DIM-02` and `DIM-06` pass for it.
- `DIM-03` runs after the feature coverage. A round edge whose radius belongs to a round feature that `FEAT-02` sized counts as dimensioned,
  also when a linear dimension across the outlines sizes it.
- `DIM-02` accepts an anchor at the center of a round model edge, for example the position of a hole. Before, only anchors on an edge passed.
- A feature with an uncertainty marker at one of its edges gets `needs_review` instead of `fail`. The acceptance gate then requires a review decision.
- `FEAT-01`, `FEAT-02`, and `FEAT-03` are mandatory rules. Without a model projection of the bound STEP, they are `not_tested`.
  They are not applicable when the inventory has no feature. `FEAT-02` is not applicable when the model has only plane levels along model axes.
- The verification report has the section `feature_coverage`. It lists each feature with its views, size dimensions, positions, markers, and status.
  It does not contain the boundary points of the faces.
- `DIM-05` expects the dimension line of a linear dimension only beside the value. The value is centered on the line and interrupts it.

## Consequences

- A delivered drawing shows each feature of the bound STEP, gives the size of each feature that has a supported size dimension,
  and locates each round, conical, and torus feature and each plane level by a chain of dimensions, or the drawing is not accepted.
- Positions are only checked along model axes and plane normals. A feature with an inclined axis is not located along other directions.
- Polar dimensions (a pitch circle diameter and an angle) do not connect positions. Dimension hole positions with linear dimensions between centers.
- A free-form surface always needs an uncertainty marker and a review decision, because `FEAT-02` has no supported size for it.
  A sphere counts as a free-form surface.
- The verifier recognizes the size of a chamfer only from angular and linear dimensions. It does not read a chamfer note such as "2 x 45°".
- `DIM-05` does not test the lines of angular dimensions in the raster and reports `not_tested`. The acceptance gate therefore blocks
  a drawing with an angular dimension until the lines of this dimension are checked in the raster.
- A pattern of equal holes needs a size dimension for each hole. A note such as "4x" is not read.

## Tests

- `drawing2cad-mcp/tests/test_feature_coverage.py`: the flange inventory (seven round features and three plane levels, and no cone, torus, or free-form surface);
  an inventory of a real build123d part with a chamfer of a straight edge, a chamfer of a hole, a fillet, and a sphere;
  a completely dimensioned plate passes; missing size, position, and thickness dimensions fail; a dimension that failed its value check does not count;
  a linear dimension across the outlines gives the size; a feature that only hidden lines show fails, and a marker makes it a review item;
  a chamfer of a straight edge needs an angle and a length, or two lengths; a chamfer of a hole needs the same sizes, and a line beside the cone does not show it;
  a fillet needs its radius at the profile arc, and a polyline profile is visible; a free-form surface fails `FEAT-02`, becomes a review item with a marker,
  and has no `FEAT-03`; isometric views do not count; an edge outside the extent of a hole or beside the faces of a plane level
  does not count, and a dimension to it does not locate the face; a section off the hole axis shows the hole, and a section that misses the hole
  does not; an edge that fits two round features shows neither, and a diameter at it sizes neither; an empty inventory is not applicable.
- `drawing2cad-mcp/tests/test_drawing_acceptance.py`: `DIM-03` accepts a radius that `FEAT-02` sized.
- `drawing2cad-mcp/tests/test_pdf_verification.py`: each feature of the flange drawing is visible, sized, and located;
  without the disc thickness and the hole positions, the four holes and the disc face fail `FEAT-03`;
  without the bound STEP, the feature rules are `not_tested`.
