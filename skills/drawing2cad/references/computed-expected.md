# Calculated volumes and extents

Call `part_validate` with the complete part description.
Read `computed_expected.features` and `computed_expected.final` from the successful response.
Use these calculated reference values. Do not calculate expected volumes or overall extents by hand.

Each feature row describes the cumulative solid after that operation.
Each row contains the feature ID, volume in cubic millimeters, and global extents in millimeters.
The calculation resolves parameter references without a CAD kernel.
It does not change the description, evidence, or printed dimensions.

## Result types

- `exact`: The supported analytic rule gives the value, subject to floating-point precision.
- `bound`: The result is an interval. A value inside this interval does not prove exact agreement.
- No `kind` or value: Read `reason`. The calculation has no supported rule for this state.

An exact bounding box contains `min`, `max`, and `size` in global X, Y, Z order.
A bounded result contains `lower` and `upper`. The bounding box also contains its outer `min` and `max` envelope.
Do not convert an unavailable result or a bound into an exact measurement.

The exact calculation supports boxes and constant-section cylinders, polygons, and profiles with lines and circular arcs.
It evaluates ordered additions and removals in axial layers. Overlapping removals share one removed region.
Plain holes and counterbores use the same Boolean calculation as pockets and cuts.
Signed feature axes use the coordinate frames from `part_schema`.
Mixed-axis combinations can have conservative bounds instead of exact results.

Chamfers, fillets, taper, conical countersinks, and drill tips have no exact rule in this calculation.
An unsupported operation makes dependent cumulative values unavailable.
Numerical ambiguity or the calculation budget can also prevent a result. Retain the reason in the review record.

## Build comparison

Call `build_from_description` after validation.
Read `computed_checks` in each `feature_results` row and the checks for the final solid and fresh STEP import.
The comparison uses an absolute tolerance of `0.00001` and a relative tolerance of `0.0000001`.
The effective tolerance is the larger value. Units are millimeters or cubic millimeters for the compared quantity.
Agent comparison also uses the supplied measurement tolerance when it is larger.

`computed_volume` and `computed_bbox` compare the calculation with the actual geometry.
Bounding-box comparison includes position and size. A translated body cannot pass from size alone.
`computed_agent_volume` and `computed_agent_bbox` compare the calculation with supplied measurement expectations.
These rows retain the measurement ID, evidence IDs, build value, difference, and tolerance.
A difference outside the permitted interval and tolerance fails the build with the feature ID.
An unavailable calculation has status `not_tested`; it does not prove agreement.

## Source evidence

Keep printed dimensions in their original measurement and evidence records.
Do not copy a calculated value into a field that claims a printed dimension or an independent measurement.
If the calculation conflicts with a printed dimension, review the description against the source.
Correct the construction or interpretation. Do not replace the source value to obtain a pass.

The calculation tests the declared construction against the CAD result.
It cannot detect a feature that the description omits, or prove that a source interpretation is correct.
Continue the source inventory, local measurements, and drawing review from [verification-loop.md](verification-loop.md).
