"""Review-Flags aus dem Extraktor-JSON: Stellen, die ein Mensch prüfen muss, statt sie zu raten.

Bisher zwei Quellen: Striche der Klasse `unclear` (räumlich zu Gruppen zusammengefasst)
und Textblöcke mit nicht sicher erkannten Zeichen (`?`).
"""

from __future__ import annotations

from typing import Any

# Unklare Striche, deren Rahmen näher als das beieinander liegen, bilden eine Stelle
CLUSTER_GAP_MM = 3.0

Box = tuple[float, float, float, float]


def stroke_bbox(s: dict[str, Any]) -> Box:
    if s["type"] == "line":
        (x0, y0), (x1, y1) = s["p0"], s["p1"]
        return min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1)
    (cx, cy), r = s["center"], s["radius"]  # Bogen: Vollkreis als sichere Obergrenze
    return cx - r, cy - r, cx + r, cy + r


def _near(a: Box, b: Box, gap: float) -> bool:
    return a[0] - gap <= b[2] and b[0] - gap <= a[2] and a[1] - gap <= b[3] and b[1] - gap <= a[3]


def _union(a: Box, b: Box) -> Box:
    return min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3])


def _cluster(items: list[tuple[int, Box]], gap: float) -> list[tuple[list[int], Box]]:
    """Fasst Rahmen zusammen, bis keine zwei Gruppen mehr nah beieinander liegen."""
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
    flags: list[dict[str, Any]] = []

    if not drawing["views"]:
        flags.append({"kind": "no_views", "message": "Keine Ansicht erkannt", "bbox": None, "stroke_ids": []})

    unclear = [(s["id"], stroke_bbox(s)) for s in drawing["strokes"] if s["kind"] == "unclear"]
    for ids, box in sorted(_cluster(unclear, CLUSTER_GAP_MM), key=lambda g: (g[1][1], g[1][0])):
        flags.append({
            "kind": "unclear_strokes",
            "message": f"{len(ids)} Strich(e) ohne sichere Bedeutung",
            "bbox": [round(v, 3) for v in box],
            "stroke_ids": sorted(ids),
        })

    for t in drawing["text_blocks"]:
        if "?" in t["text"]:
            flags.append({
                "kind": "unreadable_text",
                "message": f"Text nicht sicher gelesen: „{t['text']}“",
                "bbox": t["bbox"],
                "stroke_ids": [],
            })

    return flags
