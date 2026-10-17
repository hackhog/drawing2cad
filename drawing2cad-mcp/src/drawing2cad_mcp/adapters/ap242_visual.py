"""Headless inspection of model edges and PMI graphics read from an AP242 file.

Run this adapter only in a restricted CAD worker. The pages are a wireframe
inspection aid. They do not establish target-viewer support or conformance.
"""
from __future__ import annotations

import hashlib
import math
from pathlib import Path

MAX_STEP_BYTES = 32 * 1024 * 1024
MAX_PDF_BYTES = 32 * 1024 * 1024
MAX_DIMENSIONS = 128
MAX_SEGMENTS = 100_000
PAGE_WIDTH, PAGE_HEIGHT = 842, 595


def _hash(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _metric_ap242(path):
    from .p21 import sth_p21_parse, sth_p21_validate_refs
    if not 0 < path.stat().st_size <= MAX_STEP_BYTES:
        raise ValueError("STEP inspection input exceeds its size bound or is empty.")
    text = path.read_text(encoding="utf-8")
    if "AP242_MANAGED_MODEL_BASED_3D_ENGINEERING" not in text.split("DATA;", 1)[0]:
        raise ValueError("Inspection requires an AP242 file.")
    records = sth_p21_parse(text)
    sth_p21_validate_refs(records)
    length_units = []
    for kind, args in records.values():
        if kind == "__COMPLEX__":
            components = {item.name: item.args for item in args}
            if "LENGTH_UNIT" in components:
                length_units.append(components.get("SI_UNIT"))
    if not length_units or any(unit != ["MILLI", "METRE"] for unit in length_units):
        raise ValueError("Inspection supports explicit millimetre length units only.")


def _point(point):
    values = tuple(point.Coord(i) for i in (1, 2, 3))
    if any(not math.isfinite(value) or abs(value) > 1e9 for value in values):
        raise ValueError("Inspection geometry exceeds its coordinate bound.")
    return values


def _segments(shape, *, straight_only=False):
    from OCP.BRepAdaptor import BRepAdaptor_Curve
    from OCP.GeomAbs import GeomAbs_Line
    from OCP.TopAbs import TopAbs_EDGE
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopoDS import TopoDS
    result = []
    edges = TopExp_Explorer(shape, TopAbs_EDGE)
    while edges.More():
        curve = BRepAdaptor_Curve(TopoDS.Edge(edges.Current()))
        is_line = curve.GetType() == GeomAbs_Line
        if straight_only and not is_line:
            raise ValueError("Stored nominal PMI must contain straight strokes.")
        first, last = curve.FirstParameter(), curve.LastParameter()
        if not math.isfinite(first) or not math.isfinite(last):
            raise ValueError("Inspection requires bounded curves.")
        count = 1 if is_line else 64
        if len(result) + count > MAX_SEGMENTS:
            raise ValueError("Inspection exceeds its segment bound.")
        points = [_point(curve.Value(first + (last - first) * i / count)) for i in range(count + 1)]
        result.extend((a, b) for a, b in zip(points, points[1:]) if math.dist(a, b) > 1e-10)
        edges.Next()
    return result


def _read_scene(path):
    """Read labels and stored strokes without the construction description."""
    from OCP.IFSelect import IFSelect_RetDone
    from OCP.STEPCAFControl import STEPCAFControl_Reader
    from OCP.TCollection import TCollection_ExtendedString
    from OCP.TDocStd import TDocStd_Document
    from OCP.XCAFDoc import XCAFDoc_DocumentTool, XCAFDoc_Dimension, XCAFDoc_ShapeTool
    from OCP.collections import Sequence_TDF_Label
    from OCP.TopAbs import TopAbs_SOLID
    from OCP.TopExp import TopExp_Explorer

    document = TDocStd_Document(TCollection_ExtendedString("AP242 visual inspection"))
    reader = STEPCAFControl_Reader()
    reader.SetGDTMode(True)
    if reader.ReadFile(str(path)) != IFSelect_RetDone or not reader.Transfer(document):
        raise ValueError("AP242 inspection import failed.")
    shapes = XCAFDoc_DocumentTool.ShapeTool_s(document.Main())
    roots = Sequence_TDF_Label()
    shapes.GetFreeShapes(roots)
    products = []
    for index in range(1, roots.Length() + 1):
        candidate = XCAFDoc_ShapeTool.GetShape_s(roots.Value(index))
        if TopExp_Explorer(candidate, TopAbs_SOLID).More():
            products.append(candidate)
    if len(products) != 1:
        raise ValueError("Inspection requires exactly one product with solid geometry.")
    model_segments = _segments(products[0])
    if not model_segments:
        raise ValueError("Imported model has no visible edges.")
    labels = Sequence_TDF_Label()
    XCAFDoc_DocumentTool.DimTolTool_s(document.Main()).GetDimensionLabels(labels)
    if not 1 <= labels.Length() <= MAX_DIMENSIONS:
        raise ValueError("Inspection requires 1 to 128 stored PMI dimensions.")
    dimensions = []
    for index in range(1, labels.Length() + 1):
        obj = XCAFDoc_Dimension.Set_s(labels.Value(index)).GetObject()
        presentation = obj.GetPresentation()
        if presentation.IsNull() or not obj.HasPlane():
            raise ValueError("Stored PMI graphics or annotation plane is missing.")
        segments = _segments(presentation, straight_only=True)
        if len(segments) < 4:
            raise ValueError("Stored PMI graphics are empty or incomplete.")
        if sum(len(d["segments"]) for d in dimensions) + len(segments) > MAX_SEGMENTS:
            raise ValueError("PMI inspection exceeds its segment bound.")
        notes = {obj.GetDescriptionName(k).ToCString(): obj.GetDescription(k).ToCString()
                 for k in range(obj.NbDescriptions())}
        identifier = notes.get("drawing2cad dimension id", f"dimension-{index}")
        if len(identifier) > 128 or any(ord(char) < 32 for char in identifier):
            raise ValueError("PMI identifier exceeds the inspection text bound.")
        value = obj.GetValue()
        if not math.isfinite(value) or value <= 0:
            raise ValueError("Inspection requires a finite positive nominal value.")
        plane = obj.GetPlane()
        kind = {15: "diameter", 2: "linear distance"}.get(int(obj.GetType()))
        if kind is None:
            raise ValueError("Inspection supports nominal diameter and linear PMI only.")
        dimensions.append({"id": identifier, "kind": kind, "value": value, "unit": "mm",
                           "segments": segments, "basis": (_point(plane.XDirection()), _point(plane.YDirection())),
                           "uncertain": any(value.startswith(("assumed:", "inferred:")) for value in notes.values())})
    return model_segments, dimensions


def _project(segments, basis):
    return [tuple(tuple(sum(point[i] * axis[i] for i in range(3)) for axis in basis)
                  for point in segment) for segment in segments]


def _panel(page, box, title, model, dimensions, basis):
    """Fit all imported vertices inside the panel, including PMI leaders."""
    import pymupdf
    box = pymupdf.Rect(box)
    page.draw_rect(box, color=(.65, .68, .72), width=.5)
    page.insert_text((box.x0 + 8, box.y0 + 15), title, fontsize=10)
    inside = pymupdf.Rect(box.x0 + 15, box.y0 + 30, box.x1 - 15, box.y1 - 15)
    groups = [(_project(model, basis), (.52, .55, .59), .45)] if model else []
    groups.extend((_project(d["segments"], basis), (.75, .12, .08) if d["uncertain"] else (.02, .20, .62), .85) for d in dimensions)
    points = [point for segments, _, _ in groups for segment in segments for point in segment]
    if not points:
        raise ValueError("Inspection panel has no geometry.")
    minimum = tuple(min(p[i] for p in points) for i in (0, 1))
    maximum = tuple(max(p[i] for p in points) for i in (0, 1))
    span = tuple(maximum[i] - minimum[i] for i in (0, 1))
    if max(span) <= 1e-10:
        raise ValueError("Inspection projection is empty.")
    scale = min(inside.width / max(span[0], 1e-10), inside.height / max(span[1], 1e-10))
    center = tuple((minimum[i] + maximum[i]) / 2 for i in (0, 1))
    def transform(point):
        return pymupdf.Point((inside.x0 + inside.x1) / 2 + (point[0] - center[0]) * scale,
                             (inside.y0 + inside.y1) / 2 - (point[1] - center[1]) * scale)
    count = 0
    for segments, color, width in groups:
        drawing = page.new_shape()
        for first, second in segments:
            a, b = transform(first), transform(second)
            if any(point.x < inside.x0 - 1e-5 or point.x > inside.x1 + 1e-5
                   or point.y < inside.y0 - 1e-5 or point.y > inside.y1 + 1e-5 for point in (a, b)):
                raise ValueError("Inspection geometry is clipped.")
            if abs(a.x - b.x) + abs(a.y - b.y) > 1e-8:
                drawing.draw_line(a, b)
                count += 1
        drawing.finish(color=color, width=width)
        drawing.commit()
    if count == 0:
        raise ValueError("Inspection panel has no visible strokes.")
    return {"name": title, "visible_segments": count, "clipping": "pass", "scale_points_per_mm": scale}


def render_ap242_inspection(step_path: Path, directory: Path):
    """Create bounded PDF/PNG evidence from the exact exported STEP bytes."""
    import pymupdf
    step_path, directory = Path(step_path), Path(directory)
    source_hash = _hash(step_path) if step_path.stat().st_size <= MAX_STEP_BYTES else None
    _metric_ap242(step_path)
    model, dimensions = _read_scene(step_path)
    document = pymupdf.open()
    panels = []
    def page(title):
        item = document.new_page(width=PAGE_WIDTH, height=PAGE_HEIGHT)
        item.insert_text((24, 25), title, fontsize=14)
        item.insert_text((24, 43), "Gray: imported model edges. Blue: stored PMI strokes. Red: recorded uncertainty. Units: mm.", fontsize=8)
        item.insert_text((24, 568), "Wireframe inspection: curved model edges are sampled; no hidden-line removal. Same OCCT reader as the server.", fontsize=8)
        item.insert_text((24, 582), "STEP SHA-256: " + source_hash, fontsize=7)
        return item
    overview = page("AP242 model and stored PMI - inspection overview")
    overview.insert_text((24, 55), "PMI can be edge-on or reversed in fixed views. Use annotation-plane detail pages to read stored strokes.", fontsize=8)
    views = [("Top (XY)", ((1, 0, 0), (0, 1, 0))),
             ("Front (XZ)", ((1, 0, 0), (0, 0, 1))),
             ("Side (YZ)", ((0, 1, 0), (0, 0, 1))),
             ("Isometric", ((1/math.sqrt(2), -1/math.sqrt(2), 0), (-1/math.sqrt(6), -1/math.sqrt(6), 2/math.sqrt(6))))]
    boxes = [(24, 64, 414, 297), (428, 64, 818, 297), (24, 307, 414, 550), (428, 307, 818, 550)]
    for (title, basis), box in zip(views, boxes):
        panels.append(_panel(overview, box, title, model, dimensions, basis))
    # Four detail panels per page keep the page count below the PMI count bound.
    for start in range(0, len(dimensions), 2):
        detail = page(f"Stored PMI detail - dimensions {start + 1} to {min(start + 2, len(dimensions))}")
        for offset, dim in enumerate(dimensions[start:start + 2]):
            top = 54 + offset * 248
            inventory = f"{dim['id'][:80]} | read semantic value: {dim['kind']} {dim['value']:g} mm"
            detail.insert_text((30, top + 12), inventory, fontsize=8)
            if dim["uncertain"]:
                detail.insert_text((30, top + 24), "Recorded assumption or inference. Confirm against source evidence.", fontsize=8, color=(.75, .12, .08))
            boxes_detail = [(24, top + 30, 414, top + 240), (428, top + 30, 818, top + 240)]
            panels.append(_panel(detail, boxes_detail[0], "Model and stored PMI - annotation plane", model, [dim], dim["basis"]))
            panels.append(_panel(detail, boxes_detail[1], "Stored strokes only - not regenerated text", [], [dim], dim["basis"]))
    directory.mkdir(parents=True, exist_ok=True)
    pdf_path = directory / "ap242-inspection.pdf"
    png_path = directory / "ap242-inspection.png"
    detail_path = directory / "ap242-inspection-detail.png"
    data = document.tobytes(garbage=4, deflate=True)
    if len(data) > MAX_PDF_BYTES:
        raise ValueError("Inspection PDF exceeds its size bound.")
    pdf_path.write_bytes(data)
    raster = document[0].get_pixmap(matrix=pymupdf.Matrix(1.5, 1.5), alpha=False)
    raster.save(str(png_path))
    document[1].get_pixmap(matrix=pymupdf.Matrix(1.5, 1.5), alpha=False).save(str(detail_path))
    page_count = len(document)
    document.close()
    if _hash(step_path) != source_hash:
        raise ValueError("STEP input changed during inspection.")
    artifacts = [{"path": str(path), "sha256": _hash(path), "bytes": path.stat().st_size,
                  "media_type": media, "role": role}
                 for path, media, role in [(pdf_path, "application/pdf", "ap242_visual_inspection"),
                                           (png_path, "image/png", "ap242_visual_overview"),
                                           (detail_path, "image/png", "ap242_visual_detail")]]
    return {"status": "pass", "source_sha256": source_hash, "source_bytes": step_path.stat().st_size,
            "units": "mm", "page_count": page_count, "model_segment_count": len(model),
            "png_preview_pages": [1, 2],
            "dimensions": [{k: v for k, v in dim.items() if k not in {"segments", "basis"}} |
                           {"stored_stroke_count": len(dim["segments"])} for dim in dimensions],
            "panels": panels, "artifacts": artifacts,
            "scope": "Imported OCCT wireframe and stored PMI graphics; sampled curves, no hidden-line removal.",
            "visual_review": "not_tested", "target_cad_opening": "not_tested", "external_conformance": "not_tested"}
