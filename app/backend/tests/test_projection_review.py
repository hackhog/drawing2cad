"""Source projection presentation uses synthetic reports, not executed geometry checks."""

from copy import deepcopy
import json
from uuid import uuid4

from fastapi.testclient import TestClient
import pytest

from drawing_demo import api
from drawing_demo.agent.mapping import artifact_view
from drawing_demo.agent.projection import projection_result, projection_view
from test_agent_runs import description, environment, upload  # noqa: F401


def report(run_id="part", source_hash="a" * 64, revision=1, status="pass"):
    return {"run_id": run_id, "revision": revision, "source_sha256": source_hash, "page": 1, "status": status,
            "views": [{"view_id": "front", "status": status, "region_sheet_mm": [5, 5, 25, 25],
                       "model_to_drawing": {"p95_mm": 0.1 if status == "pass" else 0.49, "max_mm": 0.8},
                       "drawing_to_model": {"coverage": 0.98}, "checks": {"p95": status, "max": "pass", "coverage": "pass"},
                       "limits": {"p95_mm": 0.3, "max_mm": 1, "coverage_min": 0.85}}]}


@pytest.mark.parametrize("status,expected", [("pass", "matches"), ("fail", "deviates"), ("not_tested", "not_tested")])
def test_projection_mapping_keeps_status_values_and_limits(status, expected):
    data = report(status=status)
    result = projection_view(data, 1, (50.8, 76.2), "report", "overlay")
    assert result["status"] == expected
    assert result["views"][0]["limits"] == data["views"][0]["limits"]
    assert result["views"][0]["metrics"]["coverage"] == 0.98
    assert result["overlay_artifact_id"] == "overlay"


def test_an_incomplete_or_empty_check_never_matches():
    data = report()
    data["views"][0].pop("checks")
    assert projection_view(data, 1, (50.8, 76.2), "report", None)["status"] == "not_tested"
    data["views"] = []
    assert projection_view(data, 1, (50.8, 76.2), "report", None)["status"] == "not_tested"


def test_a_failing_view_makes_a_mixed_check_deviate():
    data = report()
    data["views"] += report(status="fail")["views"]
    assert projection_view(data, 1, (50.8, 76.2), "report", None)["status"] == "deviates"


@pytest.mark.parametrize("region", [[100, 20, 215, 140], [220, 20, 230, 140], [5, 5, 210.001, 297.001]])
def test_outside_sheet_regions_keep_recorded_failures_and_metrics(region):
    data = report(status="fail")
    data["views"][0]["region_sheet_mm"] = region
    result = projection_view(data, 1, (210, 297), "report", "overlay")
    assert result["status"] == "deviates"
    assert result["views"][0]["region_sheet_mm"] == region
    assert result["views"][0]["metrics"]["p95_mm"] == 0.49
    assert result["overlay_artifact_id"] == "overlay"


@pytest.mark.parametrize("field,value", [("source_sha256", "b" * 64), ("revision", 2), ("run_id", "other")])
def test_a_report_with_a_different_binding_is_not_current(field, value):
    data = report()
    data[field] = value
    class Backend:
        def artifact_bytes(self, identifier):
            return {}, json.dumps(data).encode()
    listed = [{"role": "projection_report", "revision": 1, "artifact_id": "report", "size_bytes": 1000}]
    result = projection_result(Backend(), listed, "part", 1, {"sha256": "a" * 64}, (50.8, 76.2))
    assert result["status"] == "not_tested" and "does not match" in result["reason"]


def test_a_later_source_page_uses_its_cropbox_and_rotation():
    data = report()
    data["page"] = 2
    class Backend:
        def artifact_bytes(self, identifier):
            return {}, json.dumps(data).encode()
        def call(self, operation, **arguments):
            assert operation == "pdf_info" and arguments == {"source_id": "source"}
            return {"source": {"sha256": "a" * 64}, "pages": [{}, {
                "effective_cropbox_points": [10, 20, 226, 164], "rotation_degrees": 90}]}
    listed = [{"role": "projection_report", "revision": 1, "artifact_id": "report", "size_bytes": 1000}]
    result = projection_result(Backend(), listed, "part", 1, {"sha256": "a" * 64, "source_id": "source"}, (420, 297))
    assert result["status"] == "matches" and result["page"] == 2
    assert result["sheet_size_mm"] == pytest.approx([50.8, 76.2])


@pytest.mark.parametrize("role,media", [("projection_overlay", "image/png"), ("projection_report", "application/json")])
def test_projection_artifacts_keep_their_roles(role, media):
    value = artifact_view({"artifact_id": "id", "role": role, "media_type": media, "filename": "file",
                           "sha256": "a" * 64, "size_bytes": 1, "revision": 1}, "b" * 64)
    assert value["role"] == role and value["released"] is False


def create_run(client):
    services = client.app.state.services
    source = upload(client)
    run = services.jobs.add(source["source_id"])
    part_run = run["part_prefix"] + "-plate"
    services.backend.call("part_create", run_id=part_run, description=description(source["source_id"], source["sha256"]),
                          sources=[{"source_id": source["source_id"], "sha256": source["sha256"], "role": "construction"}])
    services.jobs.update(run["run_id"], part_run_id=part_run, phase="done", job={"status": "succeeded"})
    return services, source, run, part_run


def evidence(services, part_run, source, *, revision=1, status="pass", overlay=True):
    backend = services.backend
    store = backend.application.domain.store
    ctx = backend.context
    directory = store.namespace_root(ctx) / "synthetic-projection"
    directory.mkdir(exist_ok=True)
    def add(role, data, media):
        path = directory / uuid4().hex
        path.write_bytes(data)
        return store.artifact_register(ctx, path, role, part_run, revision, media, role)
    png = add("projection_overlay", b"synthetic overlay placeholder", "image/png") if overlay else None
    data = report(part_run, source["sha256"], revision, status)
    result = add("projection_report", json.dumps(data).encode(), "application/json")
    return result, png


def test_run_response_refreshes_projection_reports_and_rejects_stale_revisions(environment):
    with TestClient(api.create_app()) as client:
        services, source, run, part_run = create_run(client)
        url = f"/api/runs/{run['run_id']}"
        assert client.get(url).json()["projection"]["status"] == "not_tested"
        first, first_overlay = evidence(services, part_run, source, status="fail")
        failed = client.get(url).json()
        assert failed["projection"]["status"] == "deviates"
        assert failed["projection"]["overlay_artifact_id"] == first_overlay["artifact_id"]
        newest, newest_overlay = evidence(services, part_run, source)
        passed = client.get(url).json()
        assert passed["projection"]["status"] == "matches"
        assert passed["projection"]["report_artifact_id"] == newest["artifact_id"]
        assert passed["projection"]["overlay_artifact_id"] == newest_overlay["artifact_id"]
        assert {a["role"] for a in passed["artifacts"]} >= {"projection_report", "projection_overlay"}
        revised = deepcopy(description(source["source_id"], source["sha256"]))
        revised["parameters"][0]["value"] = 11
        services.backend.call("part_update", run_id=part_run, expected_revision=1, description=revised)
        stale = client.get(url).json()
        assert stale["part"]["revision"] == 2
        assert stale["projection"]["status"] == "not_tested"
        assert "older revision" in stale["projection"]["reason"]
        assert stale["projection"]["overlay_artifact_id"] is None


def test_a_missing_overlay_cannot_use_the_image_of_an_older_check(environment):
    with TestClient(api.create_app()) as client:
        services, source, run, part_run = create_run(client)
        evidence(services, part_run, source)
        latest, _ = evidence(services, part_run, source, overlay=False)
        result = client.get(f"/api/runs/{run['run_id']}").json()["projection"]
        assert result["report_artifact_id"] == latest["artifact_id"]
        assert result["overlay_artifact_id"] is None


def test_a_revision_change_during_loading_cannot_attach_an_older_projection(environment):
    with TestClient(api.create_app()) as client:
        services, source, run, part_run = create_run(client)
        evidence(services, part_run, source)
        original = services.result
        def concurrent_change(record, revision=None):
            revised = deepcopy(description(source["source_id"], source["sha256"]))
            revised["parameters"][0]["value"] = 11
            services.backend.call("part_update", run_id=part_run, expected_revision=1, description=revised)
            return original(record, revision)
        environment.setattr(services, "result", concurrent_change)
        result = client.get(f"/api/runs/{run['run_id']}").json()
        assert result["part"]["revision"] == result["projection"]["revision"] == 2
        assert result["projection"]["status"] == "not_tested"


def test_an_unreadable_report_does_not_fall_back_to_a_passing_report(environment):
    with TestClient(api.create_app()) as client:
        services, source, run, part_run = create_run(client)
        evidence(services, part_run, source)
        latest, _ = evidence(services, part_run, source)
        store = services.backend.application.domain.store
        store._path(services.backend.context, "artifacts", latest["artifact_id"]).write_bytes(b"changed")
        result = client.get(f"/api/runs/{run['run_id']}").json()["projection"]
        assert result["status"] == "not_tested" and "could not be read" in result["reason"]
