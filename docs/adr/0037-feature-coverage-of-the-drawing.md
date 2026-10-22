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
    the largest gap to an extreme point is then less than 0.05 mm up to a radius of 1300 mm.
    A round feature is partial when its faces do not go around the axis: the angles of its boundary points around the axis
    have a gap of more than 5 degrees. Examples are a fillet of a straight edge and the end of a slot,
  - a conical feature (`cone`) is a set of conical faces with one axis, one apex, one angle, and one side of the material (hole or boss).
    It is a chamfer of a round edge or a countersink. It has the radius at each end of its extent and its half angle,
  - a torus feature (`torus`) is a set of toroidal faces with one axis, one center, a major radius, and a minor radius.
    Its profile span is the angular range of its boundary points around the center of the profile circle.
    Its extent along the axis comes from the boundary points, as for a round feature.
    With a profile span of more than 91 degrees, it is a groove, a bead, or a ring. Otherwise, it is a fillet of a round edge,
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
    A section curve through the inside of the surface does not count.
- `FEAT-02`: each round, conical, and torus feature, each inclined plane level, and each free-form surface has its size:
  - a round feature: a radius or diameter dimension at its circle, or a linear dimension from one outline to the other within its extent,
  - a conical feature: two different sizes. They are an angle (an angular dimension with a leg on an outline) and a length or diameter,
    or two lengths or diameters. A length has an anchor on an outline. A diameter is at an end circle along the axis,
    or it is a linear dimension across the axis with an anchor on an outline,
  - a torus feature: a radius dimension at a profile arc, in a view across the axis. The radius is the minor radius of the torus.
    A groove, a bead, or a ring (profile span of more than 91 degrees) also needs its size across the axis:
    a diameter or radius dimension in a view along the axis, centered on the axis, with the radius R − r, R, or R + r
    (for example the diameter of the groove bottom), or a linear dimension across the axis in a view with the axis in the view plane,
    with anchors on opposite sides of the axis at one of these radii and within the station of the torus ± r.
    A fillet torus needs only the radius of its profile arc,
  - an inclined plane level: two different sizes. They are an angle with a leg on its trace and a length to its trace,
    or two lengths to its trace in different directions of the view,
  - a free-form surface: no supported size dimension exists. `FEAT-02` always fails for it.
    With an uncertainty marker at one of its edges, the finding becomes `needs_review`, and the acceptance gate requires a review decision.

  Each size dimension of a chamfer gets a constraint tag. Two dimensions with the same tag give the same size,
  and a chamfer needs two different tags:
  - a cone: `angle`; `axial` for a linear dimension along the axis; `diameter@<radius>` for a diameter or radius dimension at an end circle,
    or a linear dimension across the axis, with the radius that it measures (the cone radius at the station of the anchor on the outline),
    rounded to 0.001 mm; `length@<direction>` for a linear dimension in another direction, with the model direction of the measurement
    (or its opposite, with the first component that is not zero positive), rounded to 4 decimals, for example `length@[1, 0, 0]`,
  - an inclined plane level: `angle`; `length@<direction>` for a linear dimension, with the model direction of the measurement as above.

  Thus two diameter dimensions at one end of a countersink, or one chamfer length under two identifiers, are one size.
  The same length in two views with different orientations, for example horizontal in the front view and vertical in a rotated view, is also one size.
  A round feature and a fillet torus need one size. A groove needs the tags `radius` (its profile radius) and `major` (its size across the axis).

  A plane level along a model axis has no separate size rule: the distance to the next level is its size, and `FEAT-03` checks it.
- Ambiguity: an edge that fits more than one feature of the same group in a view does not show which feature it belongs to, and counts for none of them.
  The groups are the cylinders (holes and bosses), the cones, and the tori. Examples are the common circle of a bore below a boss with one radius,
  or the coinciding outlines of two holes behind each other. The same applies to a size dimension that fits more than one feature of the same group.
  Another view or a section must show and size these features. An edge between features of two groups counts for both.
  An example is the circle between a hole and its chamfer.
- `FEAT-03`: along each model axis and each plane normal, the plane levels and the axes of the full round, conical, and torus features across that direction are positions.
  A partial round feature is not a position: its adjacent faces locate it. Its `FEAT-03` passes.
  Along its axis, a groove (a torus with a profile span of more than 91 degrees) is also a position: the center of its profile arc,
  with its station along the axis. An anchor is at the groove in a view with the axis in the view plane,
  at the station of the torus and at the major radius from the axis. A fillet torus has no position along its axis: its tangency locates it.
  Along its axis, each end of the extent of a full round feature is a position, unless it is anchored.
  An end is anchored at the coordinate of a plane level, or at an end of a cone or a torus on the same axis whose other end is anchored
  (repeated until no end changes). Examples are a through hole, a step of a shaft, and a hole with a chamfer to a face.
  The bottom of a blind hole is not anchored: the tip of a drill point is not at a plane level. Thus a blind hole needs a depth dimension.
  An anchor is at a cylinder end in a view with the axis in the view plane, at the station of the end and at most the radius from the axis,
  for example the end of an outline or the bottom line of the hole.
  Linear dimensions connect two positions when their anchors are at these positions along the measurement direction and at a feature of the position:
  on the projection of a face of the plane level, or at the center of the axial feature in a view along its axis.
  Features at the same coordinate share a position. Thus aligned holes share their dimensions, as in a hole grid with one row of X dimensions
  and one column of Y dimensions.
  All positions of a direction must be connected. The connected group with the most features is the reference. A feature outside it fails.
  A free-form surface has no position rule. When the model has only free-form surfaces, `FEAT-03` is not applicable.
- A dimension counts for `FEAT-02` and `FEAT-03` only when `DIM-02` and `DIM-06` pass for it.
- `DIM-03` runs after the feature coverage. A round edge whose radius belongs to a round, conical, or torus feature that `FEAT-02` sized counts as dimensioned,
  also when a linear dimension across the outlines sizes it. The radii are the cylinder radius, the end radii of a cone that are not zero,
  and the radii R + r and R − r of a torus (R − r only when it is more than zero). A groove gives R + r and R − r only when its size across the axis is dimensioned.
- `DIM-02` accepts an anchor at the center of a round model edge, for example the position of a hole. Before, only anchors on an edge passed.
- A feature with an uncertainty marker at one of its edges gets `needs_review` instead of `fail`. The acceptance gate then requires a review decision.
- `FEAT-01`, `FEAT-02`, and `FEAT-03` are mandatory rules. Without a model projection of the bound STEP, they are `not_tested`.
  They are not applicable when the inventory has no feature. `FEAT-02` is not applicable when the model has only plane levels along model axes.
  `FEAT-03` is not applicable when the model has only free-form surfaces.
- The verification report has the section `feature_coverage`. It lists each feature with its views, size dimensions, positions, markers, and status.
  It does not contain the boundary points of the faces.
- `DIM-05` expects the dimension line of a linear dimension only beside the value. The value is centered on the line and interrupts it.

## Consequences

- A delivered drawing shows each feature of the bound STEP, gives the size of each feature that has a supported size dimension,
  and locates each round, conical, and torus feature and each plane level by a chain of dimensions, or the drawing is not accepted.
- Positions are only checked along model axes and plane normals. A feature with an inclined axis is not located along other directions.
- A partial cylinder, for example a fillet of a straight edge or the end of a slot, needs a radius, but no position dimension.
  The drawing locates it by its adjacent faces. A groove needs an axial position dimension to the center of its profile arc,
  and a size across its axis, for example the diameter of the groove bottom.
- A blind hole needs a depth dimension to the end of its cylinder. A dimension to the tip of the drill point does not locate the end.
- A chamfer length counts once for each model direction. A second view with another orientation does not give a second size.
- A free-form surface is shown and marked at one of its boundary edges. A section curve through the inside of the surface
  does not show it and does not take a marker for it.
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
  two diameters at one end of a cone, or a diameter and a linear dimension across that end, are one size, and a diameter with an angle,
  the diameters at both ends, or a diameter with the depth along the axis are two sizes; two horizontal lengths of a chamfer of a straight edge
  are one size, and a horizontal and a vertical length are two sizes; `DIM-03` gets the radii of sized cylinders, cones, and tori;
  a fillet of a straight edge (a partial cylinder) passes `FEAT-03` without a position, and the same feature as a full cylinder fails;
  the inventory of a rounded rectangle has four partial cylinders and a full hole, and the inventory of a shaft with a groove
  has a profile span of 180 degrees (90 degrees for a fillet); a groove without an axial dimension fails `FEAT-03`,
  a dimension from an end face to the profile center makes it pass, and a fillet torus needs no axial dimension;
  a fillet needs its radius at the profile arc, and a polyline profile is visible; a free-form surface fails `FEAT-02`, becomes a review item with a marker,
  and a model with only this surface has `FEAT-03` not applicable; isometric views do not count;
  a blind hole with a drill point fails `FEAT-03` without a depth dimension and with a dimension to the drill point tip, and passes with a dimension
  from the top face to the end of the cylinder; a through hole and a hole with a chamfer to the top face need no dimension along their axis;
  in the real build123d part, the plane levels anchor each cylinder end, also through the chamfer and the fillet (the fillet torus has the extent 5 to 6 mm);
  a groove with only its profile radius fails `FEAT-02`, and passes with the diameter of the groove bottom or with a linear dimension across the axis
  at the groove bottom; a linear dimension beside the groove does not count, and a fillet torus needs only its profile radius;
  `DIM-03` gets the radii of a groove only when its size across the axis is dimensioned;
  one chamfer length, horizontal in the front view and vertical in a rotated view, is one size, and lengths along two model directions are two sizes; an edge outside the extent of a hole or beside the faces of a plane level
  does not count, and a dimension to it does not locate the face; a section off the hole axis shows the hole, and a section that misses the hole
  does not; an edge that fits two round features shows neither, and a diameter at it sizes neither; an empty inventory is not applicable.
- `drawing2cad-mcp/tests/test_drawing_acceptance.py`: `DIM-03` accepts a radius that `FEAT-02` sized.
- `drawing2cad-mcp/tests/test_pdf_verification.py`: each feature of the flange drawing is visible, sized, and located;
  without the disc thickness and the hole positions, the four holes and the disc face fail `FEAT-03`;
  without the bound STEP, the feature rules are `not_tested`.
