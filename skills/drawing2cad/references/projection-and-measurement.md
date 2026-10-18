# Projection and measurement

Use drawing evidence before applying a projection convention.
Read the projection symbol (truncated cone) in the title block. It identifies first-angle or third-angle projection.
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

## View index

Before you assign model axes, make a view index in the run evidence. Make one row for each title on each page:

| Field | Content |
|---|---|
| Title | The printed title, for example `A-A`, `Schnitt A-A`, `SECTION A-A`, `Ansicht B`, `VIEW B`, `Einzelheit C`, or `DETAIL C`. |
| Title location | The page and the view region of the title. |
| Marker location | The page and the view that show the cutting line, the view arrow, or the detail circle with the same letter. |
| Plane or region | The cutting plane in model coordinates, for example `Z = -48`, or the detail region. Use a printed datum or a calibrated measurement. |
| Viewing direction | The direction of the section or view arrows. |

A section has a cutting line with the letter at each end and an arrow at each end. A view has one arrow with its letter. A detail has a circle with its letter.
Search all pages for the marker. The marker can be on another page or in another view on the same page.
If you cannot find a marker after a search of all pages, record the title as `unresolved` and list the pages that you searched.
Do not record a cutting plane as absent without this search.

## Scale and measurement

Prefer PDF vector geometry for measurable edges and circle candidates.
Sheet millimeters are not part millimeters.
Read the drawing scale and verify it with two independent printed dimensions.
`pdf_calibrate` returns a scale only when the two printed references agree within `relative_tolerance` (default 0.02, maximum 0.05).
Use 0.01 when both references are clear vector edges. If the references do not agree, select other references or a tighter crop. Do not increase the tolerance to get a pass.
Compare the calibrated scale with the scale in the title block, for example `1:2`, `M 1:2`, or `SCALE 1:2`. A difference of more than 2 % is a conflict. Record it in the review list with both values.
A view with its own scale statement, for example a detail at `5:1`, needs its own calibration.

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

## Replaced evidence

A later step can prove an evidence item wrong, for example a misread value or a wrong view assignment.
Do not delete the old item. Set its `review_status` to `rejected` and write the reason and the ID of the new item in its `reason`.
Add the new item with its own source region and status. Move the parameter, feature, and measurement references to the new item.
`part_validate` reports a reference to rejected evidence as `unresolved_input`. The rejected item stays in the review list.
Then continue with the next step. Do not repeat the finished steps unless the new item changes them.
