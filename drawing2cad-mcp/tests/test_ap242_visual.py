"""Inspect actual exported STEP graphics without the source construction recipe."""
import hashlib

import pytest
pytest.importorskip("build123d")
from build123d import Solid
import pymupdf

from drawing2cad_mcp.adapters.ap242_visual import render_ap242_inspection
from drawing2cad_mcp.adapters.semantic_pmi import export_ap242
from test_semantic_pmi import cylinder_case


def exported(tmp_path, *, pmi=True):
    part, spec = cylinder_case()
    path = tmp_path / "source.step"
    export_ap242(Solid.make_cylinder(10, 30), path, "Inspection cylinder",
                 spec if pmi else None, part if pmi else None)
    return path


def test_actual_imported_strokes_and_model_are_visible(tmp_path):
    source = exported(tmp_path)
    report = render_ap242_inspection(source, tmp_path / "inspection")
    assert report["source_sha256"] == hashlib.sha256(source.read_bytes()).hexdigest()
    assert report["page_count"] == 2
    assert report["png_preview_pages"] == [1, 2]
    assert report["model_segment_count"] > 100
    assert {dim["id"] for dim in report["dimensions"]} == {"diameter", "height"}
    assert sorted(dim["value"] for dim in report["dimensions"]) == [20, 30]
    assert all(dim["stored_stroke_count"] > 5 for dim in report["dimensions"])
    assert all(panel["visible_segments"] > 0 and panel["clipping"] == "pass" for panel in report["panels"])
    assert report["visual_review"] == report["target_cad_opening"] == "not_tested"
    with pymupdf.open(report["artifacts"][0]["path"]) as document:
        text = "".join(page.get_text() for page in document)
        assert "read semantic value: diameter 20 mm" in text
        assert "Stored strokes only - not regenerated text" in text
        assert "PMI can be edge-on or reversed" in text
        for page in document:
            strokes = page.get_drawings()
            assert sum(1 for stroke in strokes if stroke.get("color", (0, 0, 0))[2] > .6) > 1
            assert all(page.rect.contains(stroke["rect"]) for stroke in strokes)
    from PIL import Image
    with Image.open(report["artifacts"][1]["path"]) as image:
        pixels = list(image.get_flattened_data())
        blue = sum(b > r * 1.6 and b > g * 1.3 for r, g, b in pixels)
        gray = sum(abs(r - b) < 30 and 70 < r < 210 for r, g, b in pixels)
        assert blue > 100
        assert gray > 500
    for artifact in report["artifacts"]:
        from pathlib import Path
        path = Path(artifact["path"])
        assert artifact["sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
        assert artifact["bytes"] == path.stat().st_size


def test_missing_pmi_does_not_produce_fake_graphics(tmp_path):
    with pytest.raises(ValueError, match="stored PMI dimensions"):
        render_ap242_inspection(exported(tmp_path, pmi=False), tmp_path / "inspection")


def test_missing_stored_presentation_rejected(tmp_path):
    import re
    source = exported(tmp_path)
    text = source.read_text()
    # Keep semantics but omit the draughting association. No recipe can repair it.
    text = re.sub(r"DRAUGHTING_MODEL_ITEM_ASSOCIATION\([^;]+;", "DRAUGHTING_MODEL_ITEM_ASSOCIATION('','',#1,#1,());", text)
    source.write_text(text)
    with pytest.raises((ValueError, RuntimeError), match="graphics|PMI|import"):
        render_ap242_inspection(source, tmp_path / "inspection")


def test_source_change_during_inspection_rejected(tmp_path, monkeypatch):
    from drawing2cad_mcp.adapters import ap242_visual
    source = exported(tmp_path)
    read = ap242_visual._read_scene
    def changed(path):
        result = read(path)
        path.write_text(path.read_text().replace("Inspection cylinder", "Changed cylinder"))
        return result
    monkeypatch.setattr(ap242_visual, "_read_scene", changed)
    with pytest.raises(ValueError, match="changed during inspection"):
        render_ap242_inspection(source, tmp_path / "inspection")


def test_non_mm_units_rejected(tmp_path):
    source = exported(tmp_path)
    source.write_text(source.read_text().replace("SI_UNIT(.MILLI.,.METRE.)", "SI_UNIT($,.METRE.)"))
    with pytest.raises(ValueError, match="millimetre"):
        render_ap242_inspection(source, tmp_path / "inspection")


def test_assumed_dimensions_visible_in_red(tmp_path):
    part, spec = cylinder_case()
    part["evidence"][0]["status"] = "assumed"
    for dim in spec["dimensions"]:
        dim["uncertainty_acknowledged"] = True
    path = tmp_path / "uncertain.step"
    export_ap242(Solid.make_cylinder(10, 30), path, "Assumed cylinder", spec, part)
    report = render_ap242_inspection(path, tmp_path / "inspection")
    assert all(dim["uncertain"] for dim in report["dimensions"])
    with pymupdf.open(report["artifacts"][0]["path"]) as document:
        assert any(stroke.get("color", (0, 0, 0))[0] > .7 and stroke.get("color", (0, 0, 0))[1] < .2
                   for stroke in document[0].get_drawings())


@pytest.mark.parametrize("axis,x_axis", [("X", "Y"), ("Y", "X"), ("Z", "X")])
def test_annotation_plane_pages_fit_all_strokes(tmp_path, axis, x_axis):
    part, spec = cylinder_case()
    for dim in spec["dimensions"]:
        dim["annotation"].update(normal=axis, x_axis=x_axis)
    path = tmp_path / "planes.step"
    export_ap242(Solid.make_cylinder(10, 30), path, "Plane cylinder", spec, part)
    report = render_ap242_inspection(path, tmp_path / "inspection")
    assert all(panel["clipping"] == "pass" for panel in report["panels"])


def test_empty_projection_is_rejected():
    from drawing2cad_mcp.adapters.ap242_visual import _panel
    with pymupdf.open() as document:
        page = document.new_page()
        with pytest.raises(ValueError, match="projection is empty"):
            _panel(page, (10, 10, 200, 200), "Empty", [((0, 0, 0), (0, 0, 10))], [], ((1, 0, 0), (0, 1, 0)))
