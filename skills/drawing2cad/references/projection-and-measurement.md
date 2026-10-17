# Projection and measurement

Use drawing evidence before applying a projection convention.
Record the source symbol or an assumed convention in the review list.
An isometric view helps interpretation. Do not use it as a dimension scale.

## View and section orientation

| Convention | View arrangement relative to the front view |
|---|---|
| ISO first-angle | Top view below; right-side view on the left. |
| Third-angle | Top view above; right-side view on the right. |

These arrangements do not identify an unlabeled view by themselves.
Compare common edges, hole axes, hidden lines, and dimensions across views.

Section arrows define the viewing direction.
The cutting line defines the section plane.
Match section letters and any rotation statement before assigning model axes.
A rotated or oblique section needs its own frame.
Do not silently rotate a section to fit a preferred global frame.

If the projection is absent, select the convention that best agrees with the available geometry.
Record the alternatives, reason, source regions, and resulting axis mapping as an assumption.
Block only if no reasonable consistent interpretation remains.

## Scale and measurement

Prefer PDF vector geometry for measurable edges and circle candidates.
Sheet millimeters are not part millimeters.
Read the drawing scale and verify it with two independent printed dimensions.

For image measurement:

1. Use the same rendered page or crop coordinate convention for both calibration dimensions.
2. Identify their endpoints and record the printed values and units.
3. Compute scale for each dimension independently.
4. Compare the scales with the run's calibration tolerance.
5. Resolve inconsistent endpoints, view scales, page transforms, or perspective before use.
6. Record measured values as derived or assumed, with their source region and uncertainty.

Use two different directions where possible.
A crop can change image coordinates without changing physical scale.
Record the render size, crop bounds, rotation, and DPI.
Do not apply page coordinates directly as CAD coordinates.

Circle detection supplies candidates, centers, diameters, and confidence.
Inspect a candidate before treating it as a hole.
A circle can represent a boss, thread convention, center mark, or dimension symbol.
Detecting the circle does not establish depth or machining intent.

Source thicknesses, depths, and repeated-feature spacing need their own evidence.
If absent, use a reasonable geometric assumption and keep it visible.
A measurement derived from the construction constants is not independent drawing validation.
