"""Projection check on a generated vector drawing and real build123d geometry, without the sandbox."""

from copy import deepcopy

import pytest

pytest.importorskip("build123d")

from drawing2cad_mcp.cad_kernel import build  # noqa: E402
from drawing2cad_mcp.drafting import render_drawing  # noqa: E402
from drawing2cad_mcp.projection import check, project  # noqa: E402
from drawing2cad_mcp.vector import extract  # noqa: E402
from test_drafting import drawing_fixture  # noqa: E402


def views_for(spec, sheet_height):
    def region(frame):
        # The drawing contract uses a bottom-left origin; drawing_extract uses the top-left corner.
        return [frame[0], sheet_height - frame[3], frame[2], sheet_height - frame[1]]

    return [{"view_id": "top", "toward_viewer": "+Z", "up": "+Y", "region": region(spec["views"][0]["frame"]), "mm_per_sheet_mm": 1.0},
            {"view_id": "front", "toward_viewer": "-Y", "up": "+Z", "region": region(spec["views"][1]["frame"]), "mm_per_sheet_mm": 1.0}]


@pytest.fixture
def drawing(tmp_path):
    description, spec = drawing_fixture()
    assert render_drawing(spec, description, 1, tmp_path)["status"] == "pass"
    sheet_height = extract(tmp_path / "drawing.pdf", 1).sheet_size_mm[1]
    return description, spec, tmp_path / "drawing.pdf", views_for(spec, sheet_height)


def model_step(description, directory):
    directory.mkdir()
    result = build(description, directory)
    assert result["status"] == "pass"
    return directory / "candidate.step"


def test_generated_drawing_and_its_model_agree(drawing, tmp_path):
    description, _, pdf, views = drawing
    result = check(model_step(description, tmp_path / "model"), pdf, 1, views, tmp_path)
    assert result["status"] == "pass", result
    assert all(view["model_to_drawing"]["max_mm"] < 0.3 for view in result["views"])
    assert result["artifacts"][0]["name"] == "projection-overlay.png"
    assert (tmp_path / "projection-overlay.png").stat().st_size > 0


def test_shifted_hole_fails_in_the_top_view_only(drawing, tmp_path):
    description, _, pdf, views = drawing
    changed = deepcopy(description)
    hole = next(feature for feature in changed["features"] if feature["id"] == "hole")
    hole["position"][0] += 4
    result = check(model_step(changed, tmp_path / "model"), pdf, 1, views, tmp_path)
    top, front = result["views"]
    assert top["status"] == "fail" and top["checks"]["max"] == "fail"
    assert front["status"] == "pass"


def test_swapped_view_axes_fail(drawing, tmp_path):
    description, _, pdf, views = drawing
    views[0].update(toward_viewer="+Z", up="+X")
    result = check(model_step(description, tmp_path / "model"), pdf, 1, views, tmp_path)
    assert result["views"][0]["status"] == "fail"


def test_projection_frame_is_right_handed():
    from build123d import Box, Cylinder, Pos
    part = Box(40, 20, 10) - Pos(12, 0, 0) * Cylinder(3, 10)
    for toward, up, expected_u in (("+Z", "+Y", 12), ("-Z", "+Y", -12), ("-Y", "+Z", None)):
        edges = project(part, toward, up)
        if expected_u is None:
            assert edges["visible"] and edges["hidden"]
            continue
        circle = max(edges["visible"], key=len)
        assert sum(point[0] for point in circle) / len(circle) == pytest.approx(expected_u, abs=0.05)
    with pytest.raises(ValueError):
        project(part, "+Z", "-Z")
