# 36. Dimension values against the STEP geometry

Date: 2026-10-21

## Status

Accepted. Extends the PDF verification of [ADR 0032](0032-independent-verification-of-the-final-drawing-pdf.md) and its acceptance gate ([ADR 0033](0033-drawing-acceptance-gate.md)).
Implemented in `drawing2cad-mcp/src/drawing2cad_mcp/pdf_verifier.py`.

## Context

The PDF verification read each dimension value from the raster (`DIM-01`) and compared it with the drawing specification.
It compared the value with the STEP geometry only for radius and diameter dimensions (`DIM-04`).
For linear and angular dimensions, it checked that the anchors lie on model edges (`DIM-02`), not that the stated value is the model value.
A specification that agrees with itself, but not with the bound STEP, could therefore state a wrong length, height, depth, or angle.

## Decision

- The mandatory rule `DIM-06` compares each dimension in a view with a model projection with the bound STEP geometry.
- The model value comes from the model geometry that the verifier derives again from the STEP (ADR 0032), not from the anchor coordinates of the specification:
  - a linear dimension takes the model end points or centers nearest to its two anchors and measures their distance along its axis
    (horizontal, vertical, or aligned),
  - a radius or diameter dimension takes the round model edge at its center,
  - an angular dimension takes the model points nearest to its vertex and its two legs and measures the counterclockwise angle.
  A model point counts only within 5 mm of a declared anchor. Without such a point, the dimension fails.
- The finding reports three values: the model value, the declared value of the specification, and the value read from the PDF (`observed`).
  It passes when the declared value differs from the model value by at most 0.01 mm or 0.01 degrees and `DIM-01` read the value from the PDF.
  Theoretically exact dimensions are dimensions and get the same check.
- A dimension in a view that is not true size (an isometric view, or a projection without the scale convention `true_size`) fails.
  Its value is not a model value. Dimension the feature in an orthographic or section view.
- The comparison tolerances are thresholds of the verification profile: `anchor_snap_mm`, `dimension_value_mm`, and `dimension_value_deg`.
- Tolerance values of tolerance frames are read from the PDF (`GPS-02`). The part description has no structured GPS values to compare them with,
  so the report lists `GPS-10` as `not_tested`. `GPS-10` is not mandatory.

## Consequences

- A delivered dimension states the value of the bound STEP, within the profile tolerance, or the drawing is not accepted.
- The nearest-point rule can take another model point when the model differs strongly from the specification. The dimension then fails with the
  measured value of that point. A correct model always has a point at distance 0.
- A wrong tolerance value that the source states differently is not detected until the part description has structured GPS values.

## Tests

- `drawing2cad-mcp/tests/test_pdf_verification.py`: each of the eight dimensions of the flange states the model value with model, declared, and read values;
  a bound STEP with a taller hub makes the height dimension fail although the specification agrees with itself;
  synthetic views: a length of 38 mm on a model of 40 mm fails, a right angle passes, and a dimension in an isometric view fails as not true size.
