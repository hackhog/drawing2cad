# 39. Lines of angular dimensions in the raster

Date: 2026-10-22

## Status

Accepted. Extends `DIM-05` of [ADR 0032](0032-independent-verification-of-the-final-drawing-pdf.md) to angular dimensions.
Implemented in `drawing2cad-mcp/src/drawing2cad_mcp/drawing_verification.py` and `drawing2cad-mcp/src/drawing2cad_mcp/pdf_verifier.py`.

## Context

`DIM-05` checks in the raster that the dimension, extension, and leader lines of each native dimension are present.
It did not check angular dimensions and reported `not_tested` for them. `DIM-05` is a mandatory rule,
and the acceptance gate ([ADR 0033](0033-drawing-acceptance-gate.md)) blocks `not_tested`.
Thus a drawing with an angular dimension was never accepted, also when it was correct.

The renderer creates an angular dimension with `add_angular_dim_3p` of ezdxf. The base point and the value position are the label point.
A test with ezdxf 1.4.5 and the overrides of the renderer (`DIMTAD` 0, `DIMGAP` 0.5, `DIMEXO` 0.5, `DIMEXE` 1.0, `DIMASZ` 1.25, `DIMTMOVE` 2) gives:

- The dimension line is an arc around the vertex through the label point. It goes counterclockwise from the first leg to the second leg.
- The value is centered at the label point, on the arc. It interrupts the arc. A value outside the angle does not interrupt it.
- When the value does not fit on the arc, the arc is complete and the arrows are outside.
- An extension line along each leg starts 0.5 mm from the leg end and goes 1 mm past the arc. When the arc is inside the drawn leg, the extension line is on the leg.

## Decision

- `DIM-05` expects these lines of an angular dimension in sheet coordinates:
  - an extension line along each leg from 0.8 mm after the leg end to the arc, when the arc is more than 2 mm outside the drawn leg,
  - the arc parts beside the value. The value interrupts the arc over the same estimated length as for linear dimensions
    (number of characters × text height × 0.475 + 0.5 mm on each side of the label point). Only arc parts longer than 1 mm count.
  - A part at an arc end starts after the arrowhead (DIMASZ 1.25 mm plus the ink radius of 0.35 mm), because the filled arrowhead covers the arc end.
  - When no arc part remains, the first and the last 1 mm of the arc (the arrow ends).
- The expected line structure of the verification request accepts arc segments
  (`{"type": "arc", "center", "radius", "start_angle", "end_angle"}` in sheet mm and degrees) beside straight segments `[start, end]`.
  `DIM-05` samples each segment and checks it on its own against the coverage threshold 0.8.
- The complete arc and the extension lines up to 1 mm past the arc are expected ink for `MODEL-05`.
- An angular dimension with missing or moved lines fails `DIM-05`. `DIM-05` no longer reports `not_tested` for angular dimensions.
- An angular dimension whose arc has a sheet radius of 1 mm or less cannot be read. `DIM-05` fails for this dimension and gives the radius in its message.
  The dimension is not omitted from the rule.

## Consequences

- A correct drawing with an angular dimension can pass `DIM-05` and the acceptance gate.
- The estimate of the value length is conservative. A part of the arc near the value is not checked.
- The arrow tails outside a short arc are not expected ink. They are shorter than the `MODEL-05` extent limit.
- The rule depends on the dimension rendering of ezdxf. A change of the ezdxf version or of the dimension overrides must keep the tests of the arc and extension lines.
- A test covers an angular dimension with a value 0.9 mm from the vertex: `DIM-05` fails for it.
