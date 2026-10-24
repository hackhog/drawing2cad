"""Project a STEP candidate into orthographic drawing views and compare it with the source drawing.

This module runs in the restricted CAD worker. It reads only the files in its work directory.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

from .projection_check import _stage, compare_view

AXES = {"+X": (1, 0, 0), "-X": (-1, 0, 0), "+Y": (0, 1, 0), "-Y": (0, -1, 0), "+Z": (0, 0, 1), "-Z": (0, 0, -1)}
_EDGE_STEP_MM = 0.25
_MAX_EDGE_POINTS = 2000
DRAWING_KINDS = {"contour"}  # Hidden edges are not compared.


def _polyline(edge) -> list[tuple[float, float]]:
    from build123d import Edge
    wrapped = Edge(edge)
    length = wrapped.length
    count = min(_MAX_EDGE_POINTS, max(1, math.ceil(length / _EDGE_STEP_MM)))
    if wrapped.geom_type.name == "LINE":
        count = 1
    points = wrapped.positions([i / count for i in range(count + 1)])
    return [(round(p.X, 6), round(p.Y, 6)) for p in points]


def project(shape, toward_viewer: str, up: str) -> dict[str, list]:
    """Return visible, tangent, and hidden edges as polylines in the view plane (u right, v up, part mm).
    toward_viewer is the model axis from the part to the viewer, for example -Y for a front view."""
    from OCP.BRepLib import BRepLib
    from OCP.HLRAlgo import HLRAlgo_Projector
    from OCP.HLRBRep import HLRBRep_Algo, HLRBRep_HLRToShape
    from OCP.TopAbs import TopAbs_EDGE
    from OCP.TopExp import TopExp_Explorer
    from OCP.gp import gp_Ax2, gp_Dir, gp_Pnt

    if toward_viewer not in AXES or up not in AXES:
        raise ValueError("View axes must be +X, -X, +Y, -Y, +Z, or -Z.")
    view, upward = AXES[toward_viewer], AXES[up]
    if sum(a * b for a, b in zip(view, upward)) != 0:
        raise ValueError("The up axis must be perpendicular to the viewing axis.")
    algorithm = HLRBRep_Algo()
    algorithm.Add(shape.wrapped)
    frame = gp_Ax2(gp_Pnt(0, 0, 0), gp_Dir(*view))
    frame.SetYDirection(gp_Dir(*upward))
    algorithm.Projector(HLRAlgo_Projector(frame))
    algorithm.Update()
    algorithm.Hide()
    shapes = HLRBRep_HLRToShape(algorithm)
    groups = {"visible": (shapes.VCompound(), shapes.OutLineVCompound()),
              "tangent": (shapes.Rg1LineVCompound(),),
              "hidden": (shapes.HCompound(), shapes.OutLineHCompound())}
    result: dict[str, list] = {}
    for name, compounds in groups.items():
        lines = []
        for compound in compounds:
            if compound.IsNull():
                continue
            explorer = TopExp_Explorer(compound, TopAbs_EDGE)
            while explorer.More():
                edge = explorer.Current()
                BRepLib.BuildCurves3d_s(edge, 1e-6)
                lines.append(_polyline(edge))
                explorer.Next()
        result[name] = lines
    return result


def _stroke_polyline(stroke) -> list[tuple[float, float]]:
    geometry = stroke.geom
    if hasattr(geometry, "radius"):
        sweep = 360.0 if geometry.is_circle else geometry.sweep_deg
        count = max(8, math.ceil(abs(math.radians(sweep)) * geometry.radius / 0.1))
        return [(geometry.center[0] + geometry.radius * math.cos(math.radians(geometry.start_deg + sweep * i / count)),
                 geometry.center[1] + geometry.radius * math.sin(math.radians(geometry.start_deg + sweep * i / count)))
                for i in range(count + 1)]
    return [tuple(geometry.p0), tuple(geometry.p1)]


def _inside(stroke, region) -> bool:
    x0, y0, x1, y1 = stroke.bbox()
    return x0 >= region[0] and y0 >= region[1] and x1 <= region[2] and y1 <= region[3]


def check(step_path: Path, pdf_path: Path, page: int, views: list[dict], directory: Path) -> dict[str, Any]:
    """Project the candidate into each requested view and compare it with the drawing strokes in the view region."""
    with _stage("dependencies"):
        from build123d import import_step
        from .vector import extract
    with _stage("step_import"):
        shape = import_step(str(step_path))
    with _stage("source_extraction"):
        drawing = extract(pdf_path, page)
    reports = []
    for view in views:
        with _stage("step_projection"):
            model = project(shape, view["toward_viewer"], view["up"])
        with _stage("source_preparation"):
            strokes = [s for s in drawing.strokes if s.kind.value in DRAWING_KINDS and _inside(s, view["region"])]
            lines = [_stroke_polyline(s) for s in strokes]
        report = compare_view(model, lines, mm_per_sheet_mm=view["mm_per_sheet_mm"])
        report.update(view_id=view["view_id"], region_sheet_mm=list(view["region"]), stroke_count=len(strokes),
                      toward_viewer=view["toward_viewer"], up=view["up"], mm_per_sheet_mm=view["mm_per_sheet_mm"])
        reports.append(report)
    with _stage("result_generation"):
        overlay = _overlay(drawing.sheet_size_mm, reports, directory / "projection-overlay.png")
    # The worker protocol accepts pass or fail. A view that is not tested is not a pass.
    status = "pass" if all(report["status"] == "pass" for report in reports) else "fail"
    for report in reports:
        report.pop("overlay", None)
    return {"status": status, "views": reports, "artifacts": [overlay]}


def _overlay(sheet_size, reports, path: Path) -> dict[str, Any]:
    """Draw the drawing strokes in grey, the aligned model edges in blue, and the worst points in red."""
    from PIL import Image, ImageDraw

    width_mm, height_mm = sheet_size
    scale = min(2000 / width_mm, 2000 / height_mm)
    image = Image.new("RGB", (max(1, round(width_mm * scale)), max(1, round(height_mm * scale))), "white")
    draw = ImageDraw.Draw(image)

    def pixel(point):
        return (point[0] * scale, point[1] * scale)

    for report in reports:
        region = report["region_sheet_mm"]
        draw.rectangle([pixel(region[:2]), pixel(region[2:])], outline=(200, 200, 200))
        overlay = report.get("overlay", {})
        for line in overlay.get("drawing", []):
            draw.line([pixel(p) for p in line], fill=(170, 170, 170), width=4)
        for line in overlay.get("model", []):
            draw.line([pixel(p) for p in line], fill=(0, 90, 220), width=2)
        for item in report.get("worst_points_sheet_mm", []):
            x, y = pixel(item["point"])
            draw.ellipse([x - 5, y - 5, x + 5, y + 5], outline=(220, 0, 0), width=2)
    image.save(path, format="PNG")
    data = path.read_bytes()
    import hashlib
    return {"name": path.name, "path": str(path), "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(),
            "role": "projection_overlay"}
