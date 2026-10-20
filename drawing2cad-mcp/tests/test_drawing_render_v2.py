"""Flange regression: a complete DrawingSpec 2.0 drawing from derived views, rendered as DXF and PDF."""

import hashlib
import math

import pytest

pytest.importorskip("build123d")
ezdxf = pytest.importorskip("ezdxf")
pymupdf = pytest.importorskip("pymupdf")

from drawing2cad_mcp.derived_views import expand, normalize_requests  # noqa: E402
from drawing2cad_mcp.drafting import render_drawing  # noqa: E402
from drawing2cad_mcp.drawing_contract import description_digest, drawing_validate  # noqa: E402
from drawing2cad_mcp.view_derivation import derive  # noqa: E402
from test_view_derivation import FRONT, ISO, TOP, candidate, flange  # noqa: E402

SECTION = {"id": "section_a", "kind": "section", "up": [0, 0, 1],
           "cutting_plane": {"letter": "A", "origin": [0, 0, 0], "normal": [0, -1, 0], "viewing_side": "negative_normal",
                             "source_view_id": "top"}}


def flange_drawing(tmp_path):
    description = flange()
    step = candidate(description, tmp_path / "model")
    derived = derive(step, normalize_requests([TOP, FRONT, ISO, SECTION]))
    assert derived["status"] == "pass", derived
    digest = description_digest(description)
    state = {"revision": 1, "description_sha256": digest,
             "build": {"status": "pass", "description_revision": 1, "description_sha256": digest,
                       "candidate_sha256": hashlib.sha256(step.read_bytes()).hexdigest()}}
    record = {"binding": {"part_revision": 1, "description_sha256": digest, "candidate_sha256": state["build"]["candidate_sha256"]},
              "views": derived["views"], "derivation_sha256": "d" * 64}
    views = {view["id"]: view for view in derived["views"]}

    def circle(view_id, radius, near=None):
        items = [item for item in views[view_id]["geometry"] if item["type"] == "circle" and item["style"] == "visible"
                 and abs(item["radius"] - radius) < 1e-6]
        if near is not None:
            items.sort(key=lambda item: math.dist(item["center"], near))
        return items[0]["id"]

    def diameter(identifier, primitive, value, label):
        return {"id": identifier, "type": "diameter", "primitive": primitive, "expected": value, "label_position": label,
                "evidence_ids": ["drawing"]}

    bolts = [(26.870057685, 26.870057685), (-26.870057685, 26.870057685), (-26.870057685, -26.870057685), (26.870057685, -26.870057685)]
    top_dimensions = [diameter("d_disc", circle("top", 50), 100, [40, 58]), diameter("d_hub", circle("top", 25), 50, [-66, 48]),
                      diameter("d_bore", circle("top", 15), 30, [8, -64])]
    for index, (center, label) in enumerate(zip(bolts, ([40, 40], [-66, 30], [-66, -34], [40, -42]))):
        top_dimensions.append(diameter(f"d_bolt{index + 1}", circle("top", 5, center), 10, label))
    bore = next(item for item in views["front"]["geometry"] if item["type"] == "line" and item["style"] == "hidden"
                and abs(item["start"][0] + 15) < 1e-6 and abs(abs(item["end"][1] - item["start"][1]) - 32) < 1e-6)
    bottom = next(item for item in views["front"]["geometry"] if item["type"] == "line" and item["style"] == "visible"
                  and abs(item["start"][1]) < 1e-6 and abs(item["end"][1]) < 1e-6)
    top_face = next(item for item in views["front"]["geometry"] if item["type"] == "line" and item["style"] == "visible"
                    and abs(item["start"][1] - 12) < 1e-6 and abs(item["end"][1] - 12) < 1e-6)
    front_dimensions = [{"id": "h_total", "type": "linear", "axis": "vertical", "p1": {"primitive": bore["id"], "point": "start"},
                         "p2": {"primitive": bore["id"], "point": "end"}, "expected": 32, "label_position": [-72, 16],
                         "evidence_ids": ["drawing"]}]

    def view(identifier, label, kind, origin, frame, scale, dimensions=()):
        return {"id": identifier, "label": label, "kind": kind, "orientation": "isometric" if kind == "isometric" else "custom",
                "origin": origin, "frame": frame, "scale": scale, "geometry": [], "dimensions": list(dimensions),
                "derivation": {"derivation_sha256": "d" * 64, "view_id": identifier, "feature_ids": ["disc"], "evidence_ids": ["drawing"]}}

    spec = {"schema_version": "2.0", "part_revision": 1, "description_sha256": digest, "units": "mm", "title": "Synthetic flange",
            "sheet": {"width": 420.0, "height": 297.0}, "required_view_ids": ["top", "front", "iso", "section_a"],
            "views": [view("top", "Top", "orthographic", [100, 205], [20, 132, 182, 285], 1.0, top_dimensions),
                      view("front", "Front", "orthographic", [100, 80], [20, 52, 182, 128], 1.0, front_dimensions),
                      view("iso", "Isometric", "isometric", [305, 215], [215, 140, 400, 285], 0.8),
                      view("section_a", "Section A-A", "section", [290, 80], [200, 52, 400, 128], 1.0)],
            "title_block": {"legal_owner": "Synthetic Test Owner", "identification_number": "FL-0001", "revision_index": "A",
                            "date_of_issue": "2026-10-20", "document_type": "Detail drawing", "creator": "Test", "approval_person": "Reviewer",
                            "sheet_number": "1/1", "language_code": "en"},
            "border": {"zone_grid": True}, "projection_symbol": "first_angle",
            "datums": [{"letter": "A", "feature_ids": ["disc"], "view_id": "front", "primitive_id": bottom["id"],
                        "position": [-30, -20], "evidence_ids": ["drawing"]}],
            "tolerance_frames": [
                {"id": "flat", "characteristic": "flatness", "value": 0.05, "feature_ids": ["disc"], "view_id": "front",
                 "primitive_id": top_face["id"], "position": [58, 14], "evidence_ids": ["drawing"]},
                {"id": "bolt_position", "characteristic": "position", "value": 0.1, "zone": "diameter", "modifiers": ["M"],
                 "datums": [{"letter": "A"}], "feature_ids": ["bolt0"], "view_id": "top", "primitive_id": circle("top", 5, bolts[0]),
                 "position": [48, 14], "evidence_ids": ["drawing"]},
                {"id": "profile", "characteristic": "surface_profile", "value": 0.2, "datums": [{"letter": "A"}],
                 "feature_ids": ["hub"], "view_id": "front", "primitive_id": top_face["id"], "position": [58, 26], "evidence_ids": ["drawing"]}],
            "unsupported_gps": [{"id": "customer", "literal_text": "Flatness per customer standard XY-17", "evidence_ids": ["drawing"],
                                 "reason": "The source names a customer standard."}]}
    expanded, failure = expand(spec, record, state)
    assert failure is None
    return description, expanded


def test_flange_renders_a_complete_drawing(tmp_path):
    description, spec = flange_drawing(tmp_path)
    report = drawing_validate(spec, description, 1)
    assert report["status"] == "pass", report["defects"][:6]
    out = tmp_path / "out"
    out.mkdir()
    result = render_drawing(spec, description, 1, out)
    assert result["status"] == "pass", result["defects"][:6]
    assert result["native_dimension_count"] == 8
    assert result["sheet_items"] == {"title_block": True, "border": True, "tolerance_frames": 3, "datums": 1, "sections": 1,
                                     "review_marks": 2}
    document = ezdxf.readfile(out / "drawing.dxf")
    modelspace = document.modelspace()
    assert len(modelspace.query("ELLIPSE")) > 0
    # One hatching for each cut surface: left and right of the bore.
    assert [len(hatch.paths) for hatch in modelspace.query("HATCH")] == [1, 1]
    texts = {entity.dxf.text for entity in modelspace.query("TEXT")}
    assert {"Synthetic flange", "FL-0001", "Synthetic Test Owner", "1:1, 1:1.25", "mm", "A", "REVIEW", "Isometric | Scale 1:1.25"} <= texts
    assert "REVIEW customer: Flatness per customer standard XY-17" in texts
    assert len(modelspace.query('LINE[layer=="CUTTING"]')) == 1
    assert len(modelspace.query('SOLID[layer=="CUTTING_THICK"]')) == 2
    # The supported frames are on GPS. The frame outside the profile has the review style and is not a supported frame.
    owners = {entity.get_xdata("DRAWING2CAD")[1][1]: entity.dxf.layer for entity in modelspace.query("LWPOLYLINE")
              if entity.has_xdata("DRAWING2CAD")}
    assert owners["flat"] == "GPS" and owners["bolt_position"] == "GPS" and owners["profile"] == "GPS_REVIEW"
    assert owners["datum_A"] == "GPS"


def test_dxf_and_pdf_come_from_the_same_revision(tmp_path):
    description, spec = flange_drawing(tmp_path)
    out = tmp_path / "out"
    out.mkdir()
    result = render_drawing(spec, description, 1, out)
    assert result["status"] == "pass", result["defects"][:6]
    dxf_sha256 = hashlib.sha256((out / "drawing.dxf").read_bytes()).hexdigest()
    assert result["dxf_sha256"] == dxf_sha256
    with pymupdf.open(out / "drawing.pdf") as pdf:
        keywords = pdf.metadata["keywords"]
        assert f"part_revision:1" in keywords and f"dxf_sha256:{dxf_sha256}" in keywords
        assert spec["description_sha256"] in keywords
        page = pdf[0]

        def ink(box):
            x0, y0, x1, y1 = box
            clip = pymupdf.Rect(x0 * page.rect.width / 420, (297 - y1) * page.rect.height / 297,
                                x1 * page.rect.width / 420, (297 - y0) * page.rect.height / 297)
            raster = page.get_pixmap(matrix=pymupdf.Matrix(2, 2), clip=clip, colorspace=pymupdf.csGRAY)
            return sum(value < 200 for value in raster.samples)

        assert ink([230, 10, 410, 42]) > 500      # Title block.
        assert ink([250, 82, 270, 92]) > 50       # Hatching of the section (x 40..50 of the disc, left of the bore).
        assert ink([12, 12, 408, 14]) > 100       # Border frame.
    entities = ezdxf.readfile(out / "drawing.dxf").modelspace()
    assert {entity.get_xdata("DRAWING2CAD")[2][1] for entity in entities if entity.has_xdata("DRAWING2CAD")} == {"part_revision:1"}


def test_free_text_tolerance_needs_review(tmp_path):
    description, spec = flange_drawing(tmp_path)
    spec["notes"] = [{"text": "Flatness 0.05 on the sealing face.", "position": [25, 20], "evidence_ids": ["drawing"]}]
    report = drawing_validate(spec, description, 1)
    assert "gps_free_text" in {item["code"] for item in report["findings"]}


def test_view_on_the_title_block_and_long_values_fail(tmp_path):
    description, spec = flange_drawing(tmp_path)
    spec["views"][3]["frame"] = [200, 30, 400, 128]
    spec["title_block"]["legal_owner"] = "A very long legal owner name that does not fit"
    codes = {item["code"] for item in drawing_validate(spec, description, 1)["defects"]}
    assert {"sheet_overlap", "title_block_text"} <= codes


def test_projection_symbols_put_the_end_view_beside_the_correct_cone_end():
    from drawing2cad_mcp.sheet_layout import projection_symbol

    for kind, end_view_right in (("first_angle", True), ("third_angle", False)):
        symbol = projection_symbol(kind, [0, 0, 30, 8])
        cone = symbol["cone"]
        small_end_x, large_end_x = cone[0][0], cone[1][0]
        assert abs(cone[0][1] - cone[3][1]) < abs(cone[1][1] - cone[2][1])  # The small end is on the left.
        assert (symbol["circle_center"][0] > large_end_x) is end_view_right
        assert (symbol["circle_center"][0] < small_end_x) is not end_view_right


def test_tolerance_values_are_never_rounded(tmp_path):
    description, spec = flange_drawing(tmp_path)
    spec["tolerance_frames"][0]["value"] = 0.0000004
    report = drawing_validate(spec, description, 1)
    assert any(d["code"] == "gps_frame" and "decimal places" in d["message"] for d in report["defects"])


def test_leader_through_a_note_fails(tmp_path):
    description, spec = flange_drawing(tmp_path)
    # The flatness leader runs from the frame at the right to the top face of the disc. Put a note on its path.
    spec["notes"] = [{"text": "Note", "position": [130, 92.5], "evidence_ids": ["drawing"]}]
    defects = drawing_validate(spec, description, 1)["defects"]
    assert any(d["code"] == "sheet_overlap" and "leader crosses" in d["message"] for d in defects), defects[:4]
