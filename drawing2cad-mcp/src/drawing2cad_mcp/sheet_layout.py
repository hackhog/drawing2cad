"""Sheet layout of DrawingSpec 2.0: title block, border, projection symbol, tolerance frames, datum symbols, and section marks.

The validator and the renderer use these functions, so both use the same positions. All values are sheet mm,
with the origin at the bottom-left corner and positive y up. This module does not import CAD libraries.
"""

from __future__ import annotations

import math
from typing import Any

TITLE_BLOCK_WIDTH = 180.0
TITLE_BLOCK_ROW = 8.0
CAPTION_HEIGHT = 1.8
ZONE_SIZE = 50.0
CUTTING_THICK_LENGTH = 5.0
ARROW_LENGTH = 6.0
ARROW_HEAD = (2.5, 1.6)
TEXT_WIDTH_FACTOR = 0.7
# Rendered text is wider than the label estimate: the text height is the cap height. Frames and title block fields use this factor.
FIELD_TEXT_FACTOR = 0.9
# Modifiers in a circle (ISO 1101, ISO 2692). The other modifiers are plain text.
CIRCLED_MODIFIERS = {"M", "L", "E", "F", "P", "R", "T", "U"}

# Rows from the top: (field, caption, start, end) in mm from the left edge of the title block.
TITLE_BLOCK_ROWS = (
    (("title", "Title", 0, 110), ("legal_owner", "Legal owner", 110, 180)),
    (("document_type", "Document type", 0, 70), ("identification_number", "Identification number", 70, 140),
     ("revision_index", "Revision", 140, 180)),
    (("creator", "Created by", 0, 45), ("approval_person", "Approved by", 45, 90), ("date_of_issue", "Date of issue", 90, 135),
     ("language_code", "Lang.", 135, 150), ("sheet_number", "Sheet", 150, 180)),
    (("units", "Units", 0, 30), ("scale", "Scale", 30, 80), ("projection_symbol", "Projection", 80, 110),
     ("part_revision", "Part revision", 110, 180)),
)
TITLE_BLOCK_HEIGHT = TITLE_BLOCK_ROW * len(TITLE_BLOCK_ROWS)
SYMBOLS = {"straightness", "flatness", "roundness", "cylindricity", "line_profile", "surface_profile", "parallelism",
           "perpendicularity", "angularity", "position", "concentricity", "coaxiality", "symmetry", "circular_runout", "total_runout"}


def text_width(text: str, height: float, factor: float = TEXT_WIDTH_FACTOR) -> float:
    """Estimated text width. Labels use the label factor; frames and fields use FIELD_TEXT_FACTOR."""
    return max(height, len(text) * height * factor)


def scale_text(scales) -> str:
    """ISO 5455 scale text, for example 1:2 or 2:1. Several scales are separated by commas."""
    parts = []
    for scale in sorted(set(float(s) for s in scales), reverse=True):
        if scale >= 1:
            parts.append(f"{_number(scale)}:1")
        else:
            parts.append(f"1:{_number(1 / scale)}")
    return ", ".join(parts)


# Decimal places of a tolerance value. The validator rejects a value that this text cannot show exactly.
VALUE_DECIMALS = 6


def _number(value: float) -> str:
    text = f"{value:.{VALUE_DECIMALS}f}".rstrip("0").rstrip(".")
    return text or "0"


def exact_text(value: float) -> bool:
    """True when the value text shows the value without rounding."""
    return abs(float(_number(value)) - value) <= 1e-12


def has_title_block(drawing: dict) -> bool:
    return drawing.get("title_block") is not None or drawing.get("projection_symbol") is not None


def title_block_rect(sheet: dict) -> list[float]:
    margin = sheet["margin"]
    return [sheet["width"] - margin - TITLE_BLOCK_WIDTH, margin, sheet["width"] - margin, margin + TITLE_BLOCK_HEIGHT]


def title_block_cells(drawing: dict, views: list[dict]) -> list[dict[str, Any]]:
    """Cells of the title block with caption, value, and text positions."""
    sheet = drawing["sheet"]
    x0, y0, _, y1 = title_block_rect(sheet)
    data = dict(drawing.get("title_block") or {})
    data.update(title=drawing["title"], units=drawing["units"], scale=scale_text(view["scale"] for view in views),
                part_revision=str(drawing["part_revision"]), projection_symbol=None)
    height = min(sheet["text_height"], 2.5)
    cells = []
    for row, fields in enumerate(TITLE_BLOCK_ROWS):
        top = y1 - row * TITLE_BLOCK_ROW
        for name, caption, start, end in fields:
            rect = [x0 + start, top - TITLE_BLOCK_ROW, x0 + end, top]
            value = data.get(name)
            cells.append({"field": name, "caption": caption, "rect": rect, "value": None if value is None else str(value),
                          "caption_position": [rect[0] + 0.8, top - CAPTION_HEIGHT - 0.6], "caption_height": CAPTION_HEIGHT,
                          "value_position": [rect[0] + 0.8, rect[1] + 1.0], "value_height": height})
    return cells


def projection_symbol(kind: str, cell: list[float]) -> dict[str, Any]:
    """Projection method symbol (ISO 5456-2) inside a cell: a truncated cone and its end view.

    The cone has its small end on the left in both methods. The end view seen from the small end shows two visible circles.
    First angle puts this view on the right, next to the large end. Third angle puts it on the left, next to the small end.
    """
    big, small, length, gap = 2.0, 1.1, 5.0, 2.0
    cx = (cell[0] + cell[2]) / 2
    cy = cell[1] + 0.6 + big
    total = length + gap + 2 * big
    left = cx - total / 2
    if kind == "first_angle":
        cone_left, circle_center = left, [left + length + gap + big, cy]
    else:
        circle_center, cone_left = [left + big, cy], left + 2 * big + gap
    cone = [[cone_left, cy - small], [cone_left + length, cy - big], [cone_left + length, cy + big], [cone_left, cy + small]]
    return {"cone": cone, "circle_center": circle_center, "radii": [big, small],
            "axis": [[left - 0.5, cy], [left + total + 0.5, cy]]}


def border(sheet: dict, zone_grid: bool) -> dict[str, Any]:
    """Frame, centering marks, and the optional zone grid (ISO 5457)."""
    width, height, margin = sheet["width"], sheet["height"], sheet["margin"]
    frame = [margin, margin, width - margin, height - margin]
    marks = [[[width / 2, 0], [width / 2, margin]], [[width / 2, height - margin], [width / 2, height]],
             [[0, height / 2], [margin, height / 2]], [[width - margin, height / 2], [width, height / 2]]]
    ticks, labels = [], []
    if zone_grid:
        columns = max(2, round((frame[2] - frame[0]) / ZONE_SIZE))
        rows = max(2, round((frame[3] - frame[1]) / ZONE_SIZE))
        step_x = (frame[2] - frame[0]) / columns
        step_y = (frame[3] - frame[1]) / rows
        for i in range(1, columns):
            x = frame[0] + i * step_x
            ticks += [[[x, frame[1] - margin / 2], [x, frame[1]]], [[x, frame[3]], [x, frame[3] + margin / 2]]]
        for i in range(1, rows):
            y = frame[1] + i * step_y
            ticks += [[[frame[0] - margin / 2, y], [frame[0], y]], [[frame[2], y], [frame[2] + margin / 2, y]]]
        for i in range(columns):
            x = frame[0] + (i + 0.5) * step_x
            labels += [{"text": str(i + 1), "position": [x, margin / 2]}, {"text": str(i + 1), "position": [x, height - margin / 2]}]
        for i in range(rows):
            # Letters start at the top edge.
            y = frame[3] - (i + 0.5) * step_y
            letter = chr(ord("A") + i) if i < 26 else str(i + 1)
            labels += [{"text": letter, "position": [margin / 2, y]}, {"text": letter, "position": [width - margin / 2, y]}]
    return {"frame": frame, "marks": marks, "ticks": ticks, "labels": labels,
            "label_height": min(2.5, margin * 0.5)}


def anchor_point(primitive: dict, view: dict) -> list[float]:
    """The sheet point on a primitive that a tolerance frame leader or a datum triangle uses."""
    if primitive["type"] == "line":
        local = [(primitive["start"][i] + primitive["end"][i]) / 2 for i in (0, 1)]
    elif primitive["type"] in {"circle", "arc"}:
        angle = 90.0 if primitive["type"] == "circle" else (
            primitive["start_angle"] + ((primitive["end_angle"] - primitive["start_angle"]) % 360) / 2)
        local = [primitive["center"][0] + primitive["radius"] * math.cos(math.radians(angle)),
                 primitive["center"][1] + primitive["radius"] * math.sin(math.radians(angle))]
    else:
        # A point on the ellipse at the middle of its parameter range.
        angle = math.radians((primitive["start_parameter"] + primitive["end_parameter"]) / 2)
        major = primitive["major_axis"]
        minor = [-major[1] * primitive["ratio"], major[0] * primitive["ratio"]]
        local = [primitive["center"][i] + math.cos(angle) * major[i] + math.sin(angle) * minor[i] for i in (0, 1)]
    return [view["origin"][i] + view["scale"] * local[i] for i in (0, 1)]


def frame_layout(frame: dict, view: dict, text_height: float) -> dict[str, Any]:
    """Compartments of a tolerance frame (ISO 1101). position is the lower-left corner in local view coordinates."""
    height = 2 * text_height + 1.0
    circle = text_height * 0.75
    x = view["origin"][0] + view["scale"] * frame["position"][0]
    y = view["origin"][1] + view["scale"] * frame["position"][1]
    compartments = [{"kind": "symbol", "rect": [x, y, x + height, y + height], "symbol": frame["characteristic"]}]
    left = x + height
    prefix = {"diameter": "Ø", "spherical_diameter": "SØ"}.get(frame["zone"], "")
    texts = [prefix + _number(frame["value"])]
    circled = [m for m in frame["modifiers"] if m in CIRCLED_MODIFIERS]
    texts += [m for m in frame["modifiers"] if m not in CIRCLED_MODIFIERS]
    compartments.append(_compartment("value", left, y, height, " ".join(texts), circled, text_height, circle))
    left = compartments[-1]["rect"][2]
    for reference in frame["datums"]:
        compartments.append(_compartment("datum", left, y, height, reference["letter"],
                                         [m for m in reference["modifiers"] if m in CIRCLED_MODIFIERS], text_height, circle,
                                         [m for m in reference["modifiers"] if m not in CIRCLED_MODIFIERS]))
        left = compartments[-1]["rect"][2]
    return {"rect": [x, y, left, y + height], "compartments": compartments, "text_height": text_height,
            "leader_start": [x, y + height / 2]}


def _compartment(kind, left, y, height, text, circled, text_height, circle, plain=()):
    if plain:
        text = " ".join([text, *plain])
    width = 2.0 + text_width(text, text_height, FIELD_TEXT_FACTOR) + len(circled) * (2 * circle + 0.6)
    width = max(width, height)
    position = [left + 1.0, y + (height - text_height) / 2]
    start = position[0] + text_width(text, text_height, FIELD_TEXT_FACTOR) + 0.6 + circle
    circles = [{"letter": letter, "center": [start + i * (2 * circle + 0.6), y + height / 2], "radius": circle}
               for i, letter in enumerate(circled)]
    return {"kind": kind, "rect": [left, y, left + width, y + height], "text": text, "text_position": position, "circles": circles}


def symbol_strokes(symbol: str, rect: list[float]) -> dict[str, list]:
    """Geometric characteristic symbol (ISO 1101) as lines, circles, and arcs inside a square compartment."""
    x0, y0, x1, y1 = rect
    size = x1 - x0
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    s = size * 0.32
    lines, circles, arcs = [], [], []
    if symbol == "straightness":
        lines = [[[cx - s, cy], [cx + s, cy]]]
    elif symbol == "flatness":
        d = s * 0.4
        lines = [[[cx - s + d, cy + s * 0.5], [cx + s, cy + s * 0.5]], [[cx + s, cy + s * 0.5], [cx + s - d, cy - s * 0.5]],
                 [[cx + s - d, cy - s * 0.5], [cx - s, cy - s * 0.5]], [[cx - s, cy - s * 0.5], [cx - s + d, cy + s * 0.5]]]
    elif symbol == "roundness":
        circles = [[[cx, cy], s * 0.8]]
    elif symbol == "cylindricity":
        circles = [[[cx, cy], s * 0.6]]
        lines = [[[cx - s * 0.2, cy - s], [cx - s * 0.6 - s * 0.4, cy + s]], [[cx + s * 1.0, cy - s], [cx + s * 0.2, cy + s]]]
    elif symbol == "line_profile":
        arcs = [[[cx, cy - s * 0.4], s, 0, 180]]
    elif symbol == "surface_profile":
        arcs = [[[cx, cy - s * 0.4], s, 0, 180]]
        lines = [[[cx - s, cy - s * 0.4], [cx + s, cy - s * 0.4]]]
    elif symbol == "parallelism":
        lines = [[[cx - s, cy - s], [cx - s * 0.2, cy + s]], [[cx + s * 0.2, cy - s], [cx + s, cy + s]]]
    elif symbol == "perpendicularity":
        lines = [[[cx - s, cy - s], [cx + s, cy - s]], [[cx, cy - s], [cx, cy + s]]]
    elif symbol == "angularity":
        lines = [[[cx - s, cy - s], [cx + s, cy - s]], [[cx - s, cy - s], [cx + s, cy + s * 0.6]]]
    elif symbol == "position":
        circles = [[[cx, cy], s * 0.6]]
        lines = [[[cx - s, cy], [cx + s, cy]], [[cx, cy - s], [cx, cy + s]]]
    elif symbol in {"concentricity", "coaxiality"}:
        circles = [[[cx, cy], s * 0.4], [[cx, cy], s * 0.9]]
    elif symbol == "symmetry":
        lines = [[[cx - s, cy], [cx + s, cy]], [[cx - s * 0.6, cy + s * 0.5], [cx + s * 0.6, cy + s * 0.5]],
                 [[cx - s * 0.6, cy - s * 0.5], [cx + s * 0.6, cy - s * 0.5]]]
    elif symbol == "circular_runout":
        lines = [[[cx - s * 0.6, cy - s], [cx + s * 0.6, cy + s]]] + _arrow_head([cx - s * 0.6, cy - s], [cx + s * 0.6, cy + s], s * 0.5)
    elif symbol == "total_runout":
        lines = ([[[cx - s, cy - s], [cx + s * 0.2, cy + s]], [[cx - s * 0.2, cy - s], [cx + s, cy + s]],
                  [[cx - s, cy - s], [cx - s * 0.2, cy - s]]]
                 + _arrow_head([cx - s, cy - s], [cx + s * 0.2, cy + s], s * 0.5)
                 + _arrow_head([cx - s * 0.2, cy - s], [cx + s, cy + s], s * 0.5))
    return {"lines": lines, "circles": circles, "arcs": arcs}


def _arrow_head(start, tip, size):
    direction = [tip[0] - start[0], tip[1] - start[1]]
    length = math.hypot(*direction)
    unit = [direction[0] / length, direction[1] / length]
    normal = [-unit[1], unit[0]]
    back = [tip[0] - unit[0] * size, tip[1] - unit[1] * size]
    return [[tip, [back[0] + normal[0] * size * 0.4, back[1] + normal[1] * size * 0.4]],
            [tip, [back[0] - normal[0] * size * 0.4, back[1] - normal[1] * size * 0.4]]]


def datum_layout(datum: dict, view: dict, primitive: dict, text_height: float) -> dict[str, Any]:
    """Datum symbol (ISO 5459): a filled triangle on the feature, a leader, and a square with the letter."""
    size = 2 * text_height + 1.0
    anchor = anchor_point(primitive, view)
    if datum.get("position") is not None:
        x = view["origin"][0] + view["scale"] * datum["position"][0]
        y = view["origin"][1] + view["scale"] * datum["position"][1]
    else:
        x, y = anchor[0] - size / 2, anchor[1] + 4.0
    box = [x, y, x + size, y + size]
    center = [(box[0] + box[2]) / 2, (box[1] + box[3]) / 2]
    direction = [center[0] - anchor[0], center[1] - anchor[1]]
    length = math.hypot(*direction) or 1.0
    unit = [direction[0] / length, direction[1] / length]
    normal = [-unit[1], unit[0]]
    triangle = [[anchor[0] + normal[0] * 1.5, anchor[1] + normal[1] * 1.5], [anchor[0] - normal[0] * 1.5, anchor[1] - normal[1] * 1.5],
                [anchor[0] + unit[0] * 2.6, anchor[1] + unit[1] * 2.6]]
    entry = _box_entry(box, anchor)
    return {"box": box, "triangle": triangle, "leader": [triangle[2], entry],
            "text_position": [box[0] + (size - text_width(datum["letter"], text_height, FIELD_TEXT_FACTOR)) / 2,
                              box[1] + (size - text_height) / 2]}


def _box_entry(box, point):
    """The point on the edge of a box that is nearest to a point outside it."""
    return [min(max(point[0], box[0]), box[2]), min(max(point[1], box[1]), box[3])]


def leader(layout: dict, target: list[float]) -> list[list[float]]:
    """Leader from the nearest edge point of a tolerance frame to its feature, with an arrow head at the feature."""
    start = _box_entry(layout["rect"], target)
    return [start, target]


def section_marks(plane: dict, source: dict, view_direction, text_height: float) -> dict[str, Any] | None:
    """Cutting line, thick ends, arrows, and letters in the source view (ISO 128-3).

    Return None when the source view does not show the plane as a line. The validator reports that defect.
    """
    to_sheet = [[source["origin"][i] + source["scale"] * float(p[i]) for i in (0, 1)] for p in plane["line"]]
    start, end = to_sheet
    direction = [end[0] - start[0], end[1] - start[1]]
    length = math.hypot(*direction)
    matrix = source["projection"]["matrix"]
    # The arrows show the viewing direction: from the viewer toward the part, that is -view_direction.
    arrow = [-sum(float(matrix[r][c]) * float(view_direction[c]) for c in range(3)) for r in range(2)]
    arrow_length = math.hypot(*arrow)
    if length <= 1e-9 or arrow_length <= 1e-9:
        return None
    unit = [direction[0] / length, direction[1] / length]
    arrow = [arrow[0] / arrow_length, arrow[1] / arrow_length]
    thick = min(CUTTING_THICK_LENGTH, length / 3)
    ends = []
    for point, sign in ((start, 1), (end, -1)):
        inner = [point[0] + sign * unit[0] * thick, point[1] + sign * unit[1] * thick]
        tip = [point[0] + arrow[0] * ARROW_LENGTH, point[1] + arrow[1] * ARROW_LENGTH]
        head_base = [tip[0] - arrow[0] * ARROW_HEAD[0], tip[1] - arrow[1] * ARROW_HEAD[0]]
        normal = [-arrow[1], arrow[0]]
        head = [tip, [head_base[0] + normal[0] * ARROW_HEAD[1] / 2, head_base[1] + normal[1] * ARROW_HEAD[1] / 2],
                [head_base[0] - normal[0] * ARROW_HEAD[1] / 2, head_base[1] - normal[1] * ARROW_HEAD[1] / 2]]
        # The letter is centered at this point. Its box uses the field text factor.
        letter = [tip[0] + arrow[0] * (text_height * 1.2) - sign * unit[0] * 1.5,
                  tip[1] + arrow[1] * (text_height * 1.2) - sign * unit[1] * 1.5]
        half = text_width(plane["letter"], text_height, FIELD_TEXT_FACTOR) / 2 + 0.3
        box = [letter[0] - half, letter[1] - text_height * 0.7, letter[0] + half, letter[1] + text_height * 0.7]
        ends.append({"thick": [point, inner], "shaft": [point, head_base], "head": head, "letter_center": letter, "letter_box": box})
    return {"line": [start, end], "ends": ends, "letter": plane["letter"]}


def review_lines(drawing: dict, text_height: float) -> list[dict[str, Any]]:
    """Unsupported GPS requirements as a review list above the title block, or above the bottom margin."""
    sheet = drawing["sheet"]
    if has_title_block(drawing):
        x, y = title_block_rect(sheet)[0], title_block_rect(sheet)[3] + 2.0
    else:
        x, y = sheet["margin"] + 2.0, sheet["margin"] + 2.0
    lines = []
    for index, item in enumerate(drawing.get("unsupported_gps") or []):
        lines.append({"id": f"review_{item['id']}", "text": f"REVIEW {item['id']}: {item['literal_text']}",
                      "position": [x, y + index * text_height * 1.8]})
    return lines
