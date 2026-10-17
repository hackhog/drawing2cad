"""A visibility split does not need duplicate dimensions or lose provenance."""

from copy import deepcopy

import pytest

from drawing2cad_mcp.drawing_contract import description_digest, drawing_validate
from test_drafting import drawing_fixture


def split_fixture():
    description, spec = drawing_fixture()
    visible = spec["views"][0]["geometry"][-1]
    visible.update(type="arc", start_angle=270, end_angle=90)
    hidden = deepcopy(visible)
    hidden.update(id="hidden_half", start_angle=90, end_angle=270, style="hidden")
    spec["views"][0]["geometry"].append(hidden)
    return description, spec, hidden


def test_one_dimension_covers_visible_and_hidden_arcs_of_same_circle():
    description, spec, _ = split_fixture()
    result = drawing_validate(spec, description, 1)
    assert result["status"] == "pass", result
    assert len(result["measurements"]) == 3


@pytest.mark.parametrize("change", ["center", "radius", "feature", "evidence", "view"])
def test_round_dimension_cannot_cover_different_geometry_or_provenance(change):
    description, spec, hidden = split_fixture()
    if change == "center":
        hidden["center"][0] += 0.1
    elif change == "radius":
        hidden["radius"] += 0.1
    elif change == "feature":
        hidden["feature_ids"] = ["base"]
    elif change == "evidence":
        other = deepcopy(description["evidence"][0])
        other["id"] = "other_source_dimension"
        description["evidence"].append(other)
        hidden["evidence_ids"] = [other["id"]]
        spec["description_sha256"] = description_digest(description)
    else:
        spec["views"][0]["geometry"].remove(hidden)
        spec["views"][1]["geometry"].append(hidden)
    result = drawing_validate(spec, description, 1)
    assert any(item["code"] == "unmarked_radius" and item["id"] == "hidden_half"
               for item in result["defects"]), result
