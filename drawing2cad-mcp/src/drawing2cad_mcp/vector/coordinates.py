"""Transform canonical sheet coordinates to the displayed PDF orientation."""

from __future__ import annotations

from .model import Arc, Drawing, Line, Point


def rotate_point(point: Point, size: Point, rotation: int) -> Point:
    """Rotate clockwise in top-left, positive-y-down coordinates."""
    x, y = point
    width, height = size
    return {0: (x, y), 90: (height - y, x), 180: (width - x, height - y),
            270: (y, width - x)}[rotation]


def display_rotation(drawing: Drawing, rotation: int) -> Drawing:
    """Transform every location after canonical classification and glyph reading."""
    if rotation not in (0, 90, 180, 270):
        raise ValueError("Page rotation must be a multiple of 90 degrees.")
    size = drawing.sheet_size_mm

    def point(value):
        return rotate_point(value, size, rotation)

    def box(value):
        corners = [point((x, y)) for x in (value[0], value[2]) for y in (value[1], value[3])]
        return (min(p[0] for p in corners), min(p[1] for p in corners),
                max(p[0] for p in corners), max(p[1] for p in corners))

    for stroke in drawing.strokes:
        geometry = stroke.geom
        if isinstance(geometry, Line):
            geometry.p0, geometry.p1 = point(geometry.p0), point(geometry.p1)
        elif isinstance(geometry, Arc):
            geometry.center = point(geometry.center)
            geometry.start_deg = (geometry.start_deg + rotation) % 360
    for text in drawing.texts:
        text.bbox = box(text.bbox)
        text.angle_deg = (text.angle_deg - rotation) % 360
    for view in drawing.views:
        view.bbox = box(view.bbox)
    if drawing.raster_bbox:
        drawing.raster_bbox = box(drawing.raster_bbox)
    if rotation in (90, 270):
        drawing.sheet_size_mm = size[1], size[0]
    drawing.rotation_degrees = rotation
    return drawing
