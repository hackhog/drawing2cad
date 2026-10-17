"""Review flags of an uploaded drawing and the user decisions on them.

A flag marks a location that the vector analysis could not explain: unclear strokes, unrecognized text
characters, or a page without views. The flags do not change the analysis. A user decision on a flag
records the meaning that the user supplies. Decisions are user input for construction and labeled
feedback for the analysis rules.
"""

from __future__ import annotations

from typing import Any

from .vector.model import Kind

# Unclear strokes with boxes closer than this distance form one flag.
CLUSTER_GAP_MM = 3.0

# Stroke classes that the user can assign. The analysis does not produce the classes after `Kind`;
# they name drawing elements that the rules do not know yet.
FEEDBACK_CLASSES = ("frame", "table", "leader", "pitch_circle", "tangent_edge")
STROKE_CLASSES = tuple(k.value for k in Kind if k is not Kind.UNCLEAR) + FEEDBACK_CLASSES
ACTIONS = ("ignore", "classify", "correct")

Box = tuple[float, float, float, float]


def stroke_bbox(s: dict[str, Any]) -> Box:
    if s["type"] == "line":
        (x0, y0), (x1, y1) = s["p0"], s["p1"]
        return min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1)
    (cx, cy), r = s["center"], s["radius"]  # Arc: the full circle is a safe upper limit.
    return cx - r, cy - r, cx + r, cy + r


def _near(a: Box, b: Box, gap: float) -> bool:
    return a[0] - gap <= b[2] and b[0] - gap <= a[2] and a[1] - gap <= b[3] and b[1] - gap <= a[3]


def _union(a: Box, b: Box) -> Box:
    return min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3])


def _cluster(items: list[tuple[int, Box]], gap: float) -> list[tuple[list[int], Box]]:
    """Merge boxes until no two groups are near each other."""
    groups = [([i], b) for i, b in items]
    merged = True
    while merged:
        merged = False
        for a in range(len(groups)):
            for b in range(a + 1, len(groups)):
                if _near(groups[a][1], groups[b][1], gap):
                    ids_b, box_b = groups.pop(b)
                    groups[a] = (groups[a][0] + ids_b, _union(groups[a][1], box_b))
                    merged = True
                    break
            if merged:
                break
    return groups


def review_flags(drawing: dict[str, Any]) -> list[dict[str, Any]]:
    """Flags of one analyzed page. The flag ID depends only on the analysis result, so it is stable
    for the same source bytes and analysis version."""
    flags: list[dict[str, Any]] = []

    if not drawing["views"]:
        flags.append({"flag_id": "views", "kind": "no_views", "bbox": None, "stroke_ids": [], "text": None})

    unclear = [(s["id"], stroke_bbox(s)) for s in drawing["strokes"] if s["kind"] == Kind.UNCLEAR]
    for ids, box in sorted(_cluster(unclear, CLUSTER_GAP_MM), key=lambda g: (g[1][1], g[1][0])):
        ids = sorted(ids)
        flags.append({"flag_id": f"strokes-{ids[0]}", "kind": "unclear_strokes",
                      "bbox": [round(v, 3) for v in box], "stroke_ids": ids, "text": None})

    for t in drawing["text_blocks"]:
        if "?" in t["text"]:
            flags.append({"flag_id": f"text-{t['id']}", "kind": "unreadable_text", "bbox": t["bbox"],
                          "stroke_ids": [], "text": t["text"]})

    return flags


def check_decision(flag: dict[str, Any], action: str, stroke_class: str | None, text: str | None) -> str | None:
    """Return the reason why the decision does not fit the flag, or None."""
    if action == "classify":
        if flag["kind"] != "unclear_strokes":
            return "Only unclear strokes can get a stroke class."
        if stroke_class not in STROKE_CLASSES:
            return "A classify decision requires a supported stroke_class."
    elif stroke_class is not None:
        return "Only a classify decision has a stroke_class."
    if action == "correct":
        if flag["kind"] != "unreadable_text":
            return "Only unreadable text can be corrected."
        if not text or not text.strip() or "?" in text:
            return "A correct decision requires the complete text without '?'."
    elif text is not None:
        return "Only a correct decision has a text."
    return None
