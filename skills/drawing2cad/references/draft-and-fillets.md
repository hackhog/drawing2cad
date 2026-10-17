# Drafted walls and inside fillets

Use the declarative part description through `drawing2cad-mcp`.
Read the live `part_schema` before construction.
Schema 1.1 adds tapered cylinders, cuts and pockets, adjacent-plane edge selection, and dedicated draft and fillet measurements.
Legacy schema 1.0 descriptions remain supported within their original feature scope.

## Construct a drafted cavity

Use one continuous base and a tapered `cut` or `pocket` for a continuous wall.
This method avoids draft on artificial joins between separate wall pieces.
The cutter can use a box, cylinder, polygon, or closed line-and-arc profile.
For a profile, use `shape: "profile"`, `segments`, and `depth` from the live contract.

Set `taper_angle` from source evidence or a recorded assumption.
Positive taper reduces the cutter along its signed local axis.
For a cavity cut downward from its opening, the cavity becomes smaller toward its floor.
If the outer wall also requires draft, taper the outer base. A tapered pocket changes only the cavity.
Inspect the local coordinate basis, opening plane, depth, and remaining floor thickness before the build.
Do not increase the draft angle or remove required walls to obtain a valid solid.
For a round boss, use a cylinder with `taper_angle`. Positive taper reduces its radius along the signed axis.

## Select and apply fillets

Apply the draft before floor-to-wall fillets.
Use the edge-center bounds and exact `expected_count` to identify the required edges.
When necessary, add `adjacent_plane` with an `origin` and `normal` for the adjacent planar floor or section face.
The plane filter restricts the candidate edges. It does not identify a feature by construction history.
Keep the region narrow enough to exclude other edges on that plane.
An empty selection or an unexpected edge count must fail.
Read `EDGE_SELECTION.details` before changing the selector.
Its bounded edge summaries give geometry, center, bounds, and length for the selected edges.
Inspect `selected_count` and `truncated`; the list can omit additional selected edges.
Do not increase `expected_count` without identifying each additional edge.

For section transitions, derive the edge association from the source section and the part coordinate system.
Apply separate fillet features when different regions require different radii.
After an earlier fillet changes the topology, review later selectors against the new shape.

## Validate the final surfaces

Add independent `draft_angle` and `fillet_radius` measurements for the affected regions.
Use a surface `position`, plus the required axis or direction from the live schema.
An anchor must identify the intended trimmed face, away from neighboring transitions.
Do not place a fillet measurement anchor on the center axis.

`draft_angle` measures a planar, conical, or cylindrical wall relative to the pull direction.
Its result is a nonnegative magnitude; opposite slopes have the same angle.
Verify the taper direction with independent section sizes or positions.
`fillet_radius` measures the supported cylindrical, toroidal, or spherical fillet surface.
For a cylindrical or toroidal fillet, align the measurement axis or direction with the surface axis.
Either axis sign is permitted. A spherical radius does not depend on that direction.
For a nonanalytic B-spline fillet, supply `fillet_section_normal` from the intended section plane.
Use a finite, nonzero vector in global coordinates. This field applies only to `fillet_radius`.
The analytic cylinder, torus, and sphere checks retain their existing axis rules.

The B-spline check measures a local surface neighborhood around the projected anchor.
It selects the principal curvature with the larger absolute value without using the expected radius.
The smaller absolute curvature must not exceed half the larger value.
At the anchor, the direction of the smaller curvature must align with the section normal; the absolute dot product must be at least 0.9999.
The check samples the anchor and four nearby points along the surface parameters.
The approximate sample spacing is the smaller of 0.25 mm and one tenth of the measured radius.
All five points must remain on the trimmed face and have regular, separated principal curvatures.
Their radius spread must not exceed `tolerance`, and each radius must agree with the expected radius within that tolerance.
This check verifies the local neighborhood only. It does not prove a constant radius on the complete face.
A wrong section normal gives `fail`. A missing section normal, singular surface, invalid sample, or unsupported curvature gives `not_tested`.

Set `tolerance` in degrees for draft and millimeters for radius.
The default measurement tolerance is 0.01 in the applicable unit.
`spatial_tolerance` is the separate anchor-selection tolerance in millimeters; its default is 0.01 mm.
Select tolerances from the drawing requirement and the numerical measurement scope.
Do not loosen tolerances to conceal a construction error.

Inspect each result as `pass`, `fail`, or `not_tested` after the build and fresh-worker STEP import.
Unsupported requested surface measurements remain `not_tested` and prevent candidate export.
Keep the expected angle and radius unchanged while correcting geometry or an incorrect anchor.

## Show the requirements on the drawing

Use native angular and radius dimensions where the supplied view geometry supports them.
Add evidence-linked notes for general requirements, including wall draft and inside floor fillets.
Each note must identify the affected region, value, unit, and exceptions.
For example: `Inside floor-to-wall fillets: R1.5 mm, except marked transitions.`
A general note does not replace a required radius dimension on a separate round primitive.

Render the drawing and inspect the notes, section transitions, dimensions, and uncertainty markers.
Compare them with the source and the corresponding final model measurements before `drawing_review`.
Layout validation does not establish source completeness or drawing-to-solid equivalence.
