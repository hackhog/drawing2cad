"""Service boundary of drawing_derive_views with fake worker output; this is not CAD acceptance."""

import hashlib
from copy import deepcopy

import pytest

from drawing2cad_mcp.domain_store import DomainError
from drawing2cad_mcp.drawing_contract import description_digest
from test_domain_service import CTX, domain  # noqa: F401
from test_m3_service import ReplayRunner

TOP = {"id": "top", "kind": "orthographic", "view_direction": [0, 0, 1], "up": [0, 1, 0]}


class DerivationRunner(ReplayRunner):
    def __init__(self, storage, description):
        super().__init__(storage, description)
        self.received = None
        self.offset = 0.0

    def run(self, operation, *, input_step=None, description=None, **kwargs):
        if operation != "derive_views":
            return super().run(operation, input_step=input_step, description=description, **kwargs)
        self.calls.append(operation)
        self.received = {"step": hashlib.sha256(input_step.read_bytes()).hexdigest(), "views": kwargs["views"]}
        length = 60.0 + self.offset
        corners = [[0, 0], [length, 0], [length, 30], [0, 30]]
        geometry = [{"id": f"top_v{i + 1}", "type": "line", "start": corners[i], "end": corners[(i + 1) % 4], "style": "visible"}
                    for i in range(4)]
        return {"status": "pass", "views": [{"id": "top", "kind": "orthographic", "projection": kwargs["views"][0]["projection"],
                                             "geometry": geometry, "hatching": [], "cutting_plane": None,
                                             "bounds": [0, 0, length, 30], "approximations": [], "counts": {"visible": 4}}]}


def prepare(domain, *, build=True):
    service, source, description, spec, _ = domain
    cad = service._backend(CTX)[0]
    runner = DerivationRunner(cad.runner.storage, description)
    cad.runner = runner
    if build:
        assert service.call(CTX, "build_from_description", {"run_id": "plate", "expected_revision": 1})["status"] == "pass"
    return service, cad, runner, description, spec


def derive(service, revision=1, views=None):
    return service.call(CTX, "drawing_derive_views", {"run_id": "plate", "expected_revision": revision, "views": views or [TOP]})


def derived_spec(spec, derivation_sha256):
    spec = deepcopy(spec)
    spec["schema_version"] = "2.0"
    top = spec["views"][0]
    top["geometry"] = [item for item in top["geometry"] if item["type"] == "circle"]
    for dimension in top["dimensions"]:
        if dimension["type"] == "linear":
            dimension["p1"]["primitive"] = dimension["p2"]["primitive"] = "top_v1"
            dimension["expected"] = 60
            dimension["label_position"] = [30, -12]
    top["derivation"] = {"derivation_sha256": derivation_sha256, "view_id": "top", "feature_ids": ["base"], "evidence_ids": ["drawing"]}
    return spec


def test_derivation_binds_the_validated_build_and_registers_an_artifact(domain):
    service, cad, runner, _, _ = prepare(domain)
    result = derive(service)
    built = cad._load(cad._directory("plate"))["build"]
    assert result["status"] == "pass"
    assert runner.received["step"] == built["candidate_sha256"] == result["binding"]["candidate_sha256"]
    assert runner.received["views"][0]["projection"]["matrix"] == [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]]
    assert [item["role"] for item in result["artifacts"]] == ["derived_views"]
    read = service.call(CTX, "drawing_read", {"run_id": "plate"})
    assert read["derived_views"]["status"] == "current"
    assert read["derived_views"]["derivation_sha256"] == result["derivation_sha256"]


def test_derivation_requires_a_current_validated_build(domain):
    service, _, runner, _, _ = prepare(domain, build=False)
    with pytest.raises(DomainError) as error:
        derive(service)
    assert error.value.code == "VALIDATED_BUILD_REQUIRED"
    assert "derive_views" not in runner.calls


@pytest.mark.parametrize("view", [
    {**TOP, "kind": "isometric", "view_direction": [1, -1, 2], "up": [0, 0, 1]},
    {**TOP, "projection_type": "perspective"},
    {**TOP, "view_direction": [1, 1, 0]},
    {**TOP, "matrix": [[1, 0, 0], [0, 1, 0]]},
])
def test_invalid_view_requests_fail_before_the_worker(domain, view):
    service, _, runner, _, _ = prepare(domain)
    with pytest.raises(DomainError) as error:
        derive(service, views=[view])
    # The tool schema rejects unknown fields; the service rejects invalid projections.
    assert error.value.code in {"INVALID_VIEW", "INVALID_ARGUMENT"}
    assert "derive_views" not in runner.calls


def test_drawing_uses_the_derived_geometry_and_detects_a_stale_derivation(domain):
    service, _, runner, description, spec = prepare(domain)
    derivation = derive(service)["derivation_sha256"]
    drawing = derived_spec(spec, derivation)
    report = service.call(CTX, "drawing_validate", {"run_id": "plate", "expected_revision": 1, "drawing_spec": drawing})
    assert report["status"] == "pass", report["defects"]

    changed = deepcopy(description)
    changed["parameters"][0]["value"] = 70
    changed["measurements"][0]["expected"] = [70, 30, 10]
    assert service.call(CTX, "part_update", {"run_id": "plate", "expected_revision": 1, "description": changed})["revision"] == 2
    assert service.call(CTX, "build_from_description", {"run_id": "plate", "expected_revision": 2})["status"] == "pass"
    assert service.call(CTX, "drawing_read", {"run_id": "plate"})["derived_views"]["status"] == "stale"
    drawing.update(part_revision=2, description_sha256=description_digest(changed))
    report = service.call(CTX, "drawing_validate", {"run_id": "plate", "expected_revision": 2, "drawing_spec": drawing})
    assert report["defects"][0]["code"] == "derivation_stale"
    rendered = service.call(CTX, "drawing_render", {"run_id": "plate", "expected_revision": 2, "drawing_spec": drawing})
    assert rendered["status"] == "fail" and rendered["defects"][0]["code"] == "derivation_stale"
    assert "drawing" not in runner.calls

    runner.offset = 10.0
    fresh = derive(service, revision=2)["derivation_sha256"]
    assert fresh != derivation
    drawing["views"][0]["derivation"]["derivation_sha256"] = fresh
    drawing["views"][0]["dimensions"][0]["expected"] = 70
    report = service.call(CTX, "drawing_validate", {"run_id": "plate", "expected_revision": 2, "drawing_spec": drawing})
    assert report["status"] == "pass", report["defects"]


def test_derived_view_must_not_supply_derived_items(domain):
    service, _, _, _, spec = prepare(domain)
    drawing = derived_spec(spec, derive(service)["derivation_sha256"])
    drawing["views"][0]["projection"] = {"view_direction": [0, 0, 1], "up": [0, 1, 0], "scale_convention": "true_size",
                                         "matrix": [[1, 0, 0], [0, 1, 0]]}
    report = service.call(CTX, "drawing_validate", {"run_id": "plate", "expected_revision": 1, "drawing_spec": drawing})
    assert report["defects"][0]["code"] == "derivation_mismatch"


def expansion_case():
    from drawing2cad_mcp import derived_views

    state = {"revision": 1, "description_sha256": "a" * 64,
             "build": {"status": "pass", "description_revision": 1, "description_sha256": "a" * 64, "candidate_sha256": "b" * 64}}
    line = {"id": "top_v1", "type": "line", "start": [0, 0], "end": [10, 0], "style": "visible"}
    section_line = {"id": "cut_s1", "type": "line", "start": [0, 0], "end": [10, 0], "style": "section"}
    record = {"binding": derived_views.binding(state), "derivation_sha256": "c" * 64,
              "views": [{"id": "top", "kind": "orthographic", "projection": {}, "geometry": [line], "hatching": [], "cutting_plane": None},
                        {"id": "cut", "kind": "section", "projection": {}, "geometry": [section_line],
                         "hatching": [{"boundary_primitive_ids": ["cut_s1"]}],
                         "cutting_plane": {"letter": "A", "origin": [0, 0, 0], "normal": [0, 1, 0], "viewing_side": "positive_normal",
                                           "source_view_id": "top", "line": [[0, 0], [10, 0]]}}]}

    def reference(view_id, **changes):
        return {"derivation_sha256": "c" * 64, "view_id": view_id, "feature_ids": ["base"], "evidence_ids": ["drawing"], **changes}

    spec = {"schema_version": "2.0", "views": [{"id": "sheet_top", "kind": "orthographic", "derivation": reference("top")},
                                               {"id": "section_a", "kind": "section", "derivation": reference("cut")}]}
    return derived_views, state, record, spec, reference


def test_expansion_renames_the_source_view_of_a_derived_section():
    derived_views, state, record, spec, _ = expansion_case()
    expanded, failure = derived_views.expand(spec, record, state)
    assert failure is None
    assert expanded["views"][1]["cutting_plane"]["source_view_id"] == "sheet_top"
    assert expanded["views"][1]["cutting_plane"]["evidence_ids"] == ["drawing"]
    without_source = {**spec, "views": spec["views"][1:]}
    assert derived_views.expand(without_source, record, state)[1]["defects"][0]["code"] == "derivation_source_missing"


@pytest.mark.parametrize("change", [{"view_id": []}, {"view_id": {}}, {"feature_ids": "base"}, {"extra": 1}])
def test_malformed_references_fail_without_an_exception(change):
    derived_views, state, record, spec, reference = expansion_case()
    spec["views"][0]["derivation"] = reference("top", **change) if "extra" in change else {**reference("top"), **change}
    assert derived_views.expand(spec, record, state)[1]["defects"][0]["code"] == "derivation_invalid"


def test_repeated_references_and_large_expansions_fail_before_copying(monkeypatch):
    derived_views, state, record, spec, reference = expansion_case()
    repeated = {**spec, "views": [{"id": f"v{i}", "kind": "orthographic", "derivation": reference("top")} for i in range(3)]}
    assert derived_views.expand(repeated, record, state)[1]["defects"][0]["code"] == "derivation_invalid"
    monkeypatch.setattr(derived_views, "MAX_EXPANDED_PRIMITIVES", 1)
    monkeypatch.setattr(derived_views, "deepcopy", lambda value: pytest.fail("The expansion copied before the limit check."))
    assert derived_views.expand(spec, record, state)[1]["defects"][0]["code"] == "derivation_invalid"


def test_malformed_schema_version_and_geometry_fail_without_an_exception():
    derived_views, state, record, spec, _ = expansion_case()
    assert derived_views.expand({**spec, "schema_version": []}, record, state)[1]["schema_version"] is None
    spec["views"][0]["geometry"] = {"type": "line"}
    assert derived_views.expand(spec, record, state)[1]["defects"][0]["code"] == "derivation_invalid"
