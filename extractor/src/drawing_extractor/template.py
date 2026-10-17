"""Feste Geometrie der BCT-Zeichnungsvorlage (A3 quer, Export aus Siemens NX).

Gemessen an allen 9 Beispielzeichnungen, dort identisch. Werte in Millimetern.
"""

from __future__ import annotations

PT_TO_MM = 25.4 / 72.0

# Innerer Zeichnungsrahmen: alles außerhalb ist Rand mit Koordinatenraster.
FRAME = (56.7 * PT_TO_MM, 28.3 * PT_TO_MM, 1162.2 * PT_TO_MM, 813.5 * PT_TO_MM)

# Schriftfeld unten rechts (Maßstab, Titel, Projektionssymbol …).
TITLE_BLOCK = (652.0 * PT_TO_MM, 711.5 * PT_TO_MM, 1162.2 * PT_TO_MM, 813.5 * PT_TO_MM)

# Kleine Toleranz, damit Rahmenlinien selbst sicher als außen gelten.
_EDGE = 0.3


def in_drawing_area(bbox: tuple[float, float, float, float]) -> bool:
    """True, wenn die Box im Zeichenbereich liegt (innerhalb Rahmen, außerhalb Schriftfeld)."""
    x0, y0, x1, y1 = bbox
    fx0, fy0, fx1, fy1 = FRAME
    if x0 < fx0 + _EDGE or y0 < fy0 + _EDGE or x1 > fx1 - _EDGE or y1 > fy1 - _EDGE:
        return False
    tx0, ty0, _, _ = TITLE_BLOCK
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    return not (cx > tx0 and cy > ty0)
