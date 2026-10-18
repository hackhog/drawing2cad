"""Drawing templates: frame and title block limits in millimeters on the unrotated sheet.

The BCT A3 landscape limits were measured from the nine original regression drawings.
The CAx template has a higher title block. On A3, its top line is at y 233 mm from x 243 mm to the frame.
The A4 portrait limits were measured from the four A4 sample drawings: inner frame from 20 to 200 mm
and from 10 to 287 mm, title block from x 33 mm and y 233 mm.
A sheet of another size uses the A3 profile.
"""

from __future__ import annotations

PT_TO_MM = 25.4 / 72.0

Box = tuple[float, float, float, float]
Area = tuple[Box, tuple[Box, ...]]  # Frame and title blocks

# Exclude the outer margin and coordinate grid.
FRAME = (56.7 * PT_TO_MM, 28.3 * PT_TO_MM, 1162.2 * PT_TO_MM, 813.5 * PT_TO_MM)

# Exclude the lower-right title block.
TITLE_BLOCK = (652.0 * PT_TO_MM, 711.5 * PT_TO_MM, 1162.2 * PT_TO_MM, 813.5 * PT_TO_MM)
CAX_A3_TITLE_BLOCK = (242.5, 232.5, 1162.2 * PT_TO_MM, 813.5 * PT_TO_MM)  # Slightly outside x 243 and y 233.

A4_FRAME = (20.0, 10.0, 200.0, 287.0)
A4_TITLE_BLOCK = (32.5, 232.5, 200.0, 287.0)  # Slightly outside the block lines at x 33 and y 233.

BCT_A3_AREA: Area = (FRAME, (TITLE_BLOCK,))
CAX_A3_AREA: Area = (FRAME, (TITLE_BLOCK, CAX_A3_TITLE_BLOCK))
A4_PORTRAIT_AREA: Area = (A4_FRAME, (A4_TITLE_BLOCK,))
AREA_NAMES = {BCT_A3_AREA: "bct_a3", CAX_A3_AREA: "cax_a3", A4_PORTRAIT_AREA: "a4_portrait"}

# Keep the frame lines outside the accepted area.
_EDGE = 0.3
_SIZE_TOLERANCE = 1.0  # mm
_LINE_TOLERANCE = 0.5  # mm


def is_a4_portrait(sheet: tuple[float, float]) -> bool:
    return abs(sheet[0] - 210.0) <= _SIZE_TOLERANCE and abs(sheet[1] - 297.0) <= _SIZE_TOLERANCE


def has_cax_a3_title_block(drawings: list[dict]) -> bool:
    """Find the top line of the CAx A3 title block: horizontal at y 233 mm, from x 243 mm to the frame at 410 mm.
    The template draws this line in several pieces, so the pieces must cover the complete span."""
    spans = []
    for drawing in drawings:
        for item in drawing.get("items", ()):
            if item[0] != "l":
                continue
            a, b = item[1], item[2]
            y0, y1 = a.y * PT_TO_MM, b.y * PT_TO_MM
            if abs(y0 - y1) <= 0.05 and abs(y0 - 233.0) <= _LINE_TOLERANCE:
                spans.append(tuple(sorted((a.x * PT_TO_MM, b.x * PT_TO_MM))))
    reach = None
    for x0, x1 in sorted(spans):
        if reach is None:
            if abs(x0 - 243.0) > _LINE_TOLERANCE:
                continue
            reach = x1
        elif x0 <= reach + _LINE_TOLERANCE:
            reach = max(reach, x1)
    return reach is not None and abs(reach - FRAME[2]) <= 1.0


def drawing_area(sheet: tuple[float, float] | None, drawings: list[dict] | None = None) -> Area:
    """Return the frame and title blocks for an unrotated sheet and its drawing paths."""
    if sheet is not None and is_a4_portrait(sheet):
        return A4_PORTRAIT_AREA
    if drawings is not None and has_cax_a3_title_block(drawings):
        return CAX_A3_AREA
    return BCT_A3_AREA


def in_drawing_area(bbox: Box, area: Area = BCT_A3_AREA) -> bool:
    """Accept boxes inside the frame and outside the title blocks."""
    frame, title_blocks = area
    x0, y0, x1, y1 = bbox
    fx0, fy0, fx1, fy1 = frame
    if x0 < fx0 + _EDGE or y0 < fy0 + _EDGE or x1 > fx1 - _EDGE or y1 > fy1 - _EDGE:
        return False
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    return not any(cx > tx0 and cy > ty0 for tx0, ty0, _, _ in title_blocks)
