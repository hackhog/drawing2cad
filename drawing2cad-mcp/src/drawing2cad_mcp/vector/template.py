"""Fixed BCT drawing template for A3 landscape sheets from Siemens NX.

These dimensions were measured from the nine original regression drawings.
All limits are in millimeters on the sheet.
"""

from __future__ import annotations

PT_TO_MM = 25.4 / 72.0

# Exclude the outer margin and coordinate grid.
FRAME = (56.7 * PT_TO_MM, 28.3 * PT_TO_MM, 1162.2 * PT_TO_MM, 813.5 * PT_TO_MM)

# Exclude the lower-right title block.
TITLE_BLOCK = (652.0 * PT_TO_MM, 711.5 * PT_TO_MM, 1162.2 * PT_TO_MM, 813.5 * PT_TO_MM)

# Keep the frame lines outside the accepted area.
_EDGE = 0.3


def in_drawing_area(bbox: tuple[float, float, float, float]) -> bool:
    """Accept boxes inside the frame and outside the title block."""
    x0, y0, x1, y1 = bbox
    fx0, fy0, fx1, fy1 = FRAME
    if x0 < fx0 + _EDGE or y0 < fy0 + _EDGE or x1 > fx1 - _EDGE or y1 > fy1 - _EDGE:
        return False
    tx0, ty0, _, _ = TITLE_BLOCK
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    return not (cx > tx0 and cy > ty0)
