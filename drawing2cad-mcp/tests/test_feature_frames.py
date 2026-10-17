"""Advertised feature coordinates agree with actual asymmetric profile solids."""

from itertools import product

import pytest

from drawing2cad_mcp.cad_service import CadService
from drawing2cad_mcp.config import CadSettings
from drawing2cad_mcp.part_schema import description_schema, parse_description
from test_part_schema import sample_description


def test_part_schema_exposes_basis_at_the_service_boundary(tmp_path):
    service = CadService([tmp_path], tmp_path / "out", CadSettings())
    schema = service.part_schema()["schema"]
    frames = schema["x-feature-coordinate-frames"]
    assert set(frames["basis"]) == {"X", "-X", "Y", "-Y", "Z", "-Z"}
    assert frames["basis"]["Y"]["local_y"] == [0, 0, -1]
    for model in ("ExtrusionFeature", "ProfileExtrusionFeature", "CutFeature"):
        assert "x-feature-coordinate-frames" in schema["$defs"][model]["properties"]["axis"]["description"]


@pytest.mark.parametrize("axis", ["X", "-X", "Y", "-Y", "Z", "-Z"])
@pytest.mark.parametrize("kind", ["extrusion", "profile_extrusion", "cut"])
def test_advertised_basis_matches_profile_vertices(axis, kind):
    pytest.importorskip("build123d")
    from drawing2cad_mcp.cad_kernel import _primitive

    origin = [11, 17, 23]
    points = [[1, 2], [4, 2], [4, 7], [1, 7]]
    description = sample_description()
    feature = {"id": "profile", "type": kind, "origin": origin, "axis": axis,
               "evidence_ids": ["drawing"]}
    if kind == "cut":
        feature["profile"] = {"shape": "polygon", "points": points, "depth": 3}
        description["features"].append(feature)
    else:
        feature.update(operation="base", height=3)
        if kind == "extrusion":
            feature["points"] = points
        else:
            feature["segments"] = [{"kind": "line", "start": points[i], "end": points[(i + 1) % 4]} for i in range(4)]
        description["features"] = [feature]
    part = parse_description(description)
    solid = _primitive(part.features[-1], part, cutting=kind == "cut")
    basis = description_schema()["x-feature-coordinate-frames"]["basis"][axis]
    expected = sorted(tuple(origin[i] + x * basis["local_x"][i] + y * basis["local_y"][i]
                            + z * basis["local_z"][i] for i in range(3))
                      for x, y, z in product((1, 4), (2, 7), (0, 3)))
    actual = sorted(tuple(vertex.center()) for vertex in solid.vertices())
    assert len(actual) == len(expected) == 8
    for observed, declared in zip(actual, expected):
        assert observed == pytest.approx(declared, abs=1e-7)
    assert solid.volume == pytest.approx(45)
