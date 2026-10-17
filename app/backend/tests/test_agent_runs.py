"""Agent runs through the web API and the collection of MCP results (ADR 0016). No model is called."""

from hashlib import sha256
import io
import zipfile

from build123d import Box, export_step
import pytest
from fastapi.testclient import TestClient

from drawing_demo import api
from drawing_demo.agent.mapping import part_view, phase_for, review_view, sheet_region
from drawing_demo.agent.runner import AgentRunner, part_state
from drawing_demo.store import Store

client = TestClient(api.app)
SHA = "a" * 64
ANALYSIS = {"drawing": {"sheet_size_mm": [200, 100]}, "review": []}


@pytest.fixture
def store(tmp_path):
    return Store(tmp_path / "data")


@pytest.fixture
def step_file(tmp_path):
    path = tmp_path / "box.step"
    export_step(Box(10, 20, 5), str(path))
    return path


def description():
    return {
        "schema_version": "1.0", "name": "Plate", "units": "mm", "coordinate_system": "right_handed_xyz",
        "evidence": [
            {"id": "e_len", "status": "explicit", "reason": "Printed 10.", "source": {
                "source_id": "drawing", "source_sha256": SHA, "page": 1, "view": "front", "region": [0.1, 0.1, 0.2, 0.2],
                "coordinate_system": "normalized_displayed"}},
            {"id": "e_t", "status": "assumed", "reason": "Thickness not printed.", "source": {
                "source_id": "drawing", "source_sha256": SHA, "page": 1, "view": "side", "region": [0.5, 0.5, 0.6, 0.6],
                "coordinate_system": "normalized_displayed"}},
        ],
        "parameters": [{"name": "length", "value": 10, "unit": "mm", "evidence_ids": ["e_len"]},
                       {"name": "thickness", "value": 5, "unit": "mm", "evidence_ids": ["e_t"]}],
        "features": [{"id": "base", "type": "box", "operation": "base", "length": {"parameter": "length"}, "width": 20,
                      "height": {"parameter": "thickness"}, "evidence_ids": ["e_len", "e_t"]}],
        "review_flags": [{"id": "f_edge", "target_id": "base", "status": "open", "reason": "Edge radius unclear.", "evidence_ids": ["e_t"]}],
    }


def test_phase_follows_the_tool_sequence():
    assert phase_for("pdf_render_page", "queued") == "analyzing"
    assert phase_for("build_from_description", "analyzing") == "modeling"
    assert phase_for("export_step", "modeling") == "validating"
    assert phase_for("cad_worker_probe", "modeling") == "modeling"
    assert phase_for("part_schema", "analyzing") == "analyzing"


def test_source_regions_become_sheet_millimeters():
    assert sheet_region({"region": [0.1, 0.2, 0.3, 0.4], "coordinate_system": "normalized_displayed"}, (200, 100)) == [20, 20, 60, 40]
    assert sheet_region({"region": [72, 0, 144, 72]}, (200, 100)) == pytest.approx([25.4, 0, 50.8, 25.4])
    assert sheet_region({"region": [1, 1, 2, 2], "coordinate_system": "pixels"}, (200, 100)) is None


def test_part_view_lists_parameters_with_origin_and_operations():
    part = part_view({"revision": 3, "description": description()})
    assert part["revision"] == 3
    assert [(p["name"], p["origin"], p["feature"]) for p in part["parameters"]] == [("length", "source", "base"), ("thickness", "assumed", "base")]
    assert part["operations"] == [{"index": 1, "kind": "box", "label": "base", "parameters": ["length", "thickness"]}]


def test_review_keeps_assumptions_flags_and_untested_checks_apart():
    from drawing2cad_mcp.part_schema import part_validate
    state = {"description": description(), "build": {"status": "pass", "validation": {"checks": [
        {"check": "step_reimport", "status": "pass"}, {"check": "target_cad_open", "status": "skipped"}]}}}
    review = review_view(state, part_validate(state["description"])["review_items"], (200, 100), released=False)
    assert review["release_state"] == "blocked"
    assert [a["id"] for a in review["assumptions"]] == ["e_t"]
    assert review["assumptions"][0]["source_region"] == [100, 50, 120, 60]
    assert [u["id"] for u in review["uncertainties"]] == ["f_edge"]
    assert [v["status"] for v in review["validation"]] == ["pass", "not_tested"]


def _state(store, step_file, released):
    target = store.mcp / "cad" / "runs" / "web-x"
    target.mkdir(parents=True)
    data = step_file.read_bytes()
    path = target / "candidate.step"
    path.write_bytes(data)
    build = {"status": "pass", "candidate_path": str(path), "candidate_sha256": sha256(data).hexdigest(), "validation": {"checks": []}}
    release = {"path": str(path), "sha256": sha256(data).hexdigest()} if released else None
    return {"revision": 2, "description": description(), "build": build, "release": release}


@pytest.mark.parametrize("released", [True, False])
def test_collect_stores_step_and_preview(store, step_file, released):
    source = store.add_source("Plate_dwg.pdf", b"%PDF-1.7", ANALYSIS)
    run = store.add_run(source["source_id"])
    runner = AgentRunner(store, None, store.root / "missing.md")
    runner._collect(run["run_id"], source, {"status": "released" if released else "stopped_without_release"}, _state(store, step_file, released))
    result = store.run(run["run_id"])
    assert result["phase"] == "done" and result["job"]["status"] == "succeeded" and result["error"] is None
    assert result["review"]["release_state"] == ("released" if released else "blocked")
    roles = {a["role"]: a for a in result["artifacts"]}
    assert set(roles) == {"step", "model_preview"}
    assert roles["step"]["model_revision"] == 2
    assert roles["step"]["filename"].endswith("freigegeben.step" if released else "diagnose.step")
    assert store.artifact(roles["model_preview"]["artifact_id"])[1].read_bytes().startswith(b"glTF")


def test_collect_rejects_a_changed_or_foreign_step(store, step_file, tmp_path):
    source = store.add_source("Plate_dwg.pdf", b"%PDF-1.7", ANALYSIS)
    run = store.add_run(source["source_id"])
    state = _state(store, step_file, released=False)
    state["build"]["candidate_path"] = str(step_file)  # Outside the MCP store.
    AgentRunner(store, None, store.root / "missing.md")._collect(run["run_id"], source, {"status": "x"}, state)
    result = store.run(run["run_id"])
    assert result["phase"] == "failed" and result["artifacts"] == [] and result["error"]["code"] == "AGENT_NO_MODEL"


def test_collect_without_part_fails_the_run(store):
    source = store.add_source("Plate_dwg.pdf", b"%PDF-1.7", ANALYSIS)
    run = store.add_run(source["source_id"])
    AgentRunner(store, None, store.root / "missing.md")._collect(run["run_id"], source, {"status": "failed"}, None)
    assert store.run(run["run_id"])["error"]["code"] == "AGENT_NO_PART"


def test_a_model_endpoint_error_is_reported_as_such(store):
    source = store.add_source("Plate_dwg.pdf", b"%PDF-1.7", ANALYSIS)
    run = store.add_run(source["source_id"])
    summary = {"status": "failed", "error": {"type": "RuntimeError", "message": "Model endpoint returned HTTP 400"}}
    AgentRunner(store, None, store.root / "missing.md")._collect(run["run_id"], source, summary, None)
    error = store.run(run["run_id"])["error"]
    assert error["code"] == "AGENT_FAILED" and "HTTP 400" in error["message"]


@pytest.fixture
def web(tmp_path, monkeypatch):
    monkeypatch.setenv("DRAWING2CAD_DATA_DIR", str(tmp_path / "data"))
    skill = tmp_path / "SKILL.md"
    skill.write_text("skill")
    monkeypatch.setenv("DRAWING2CAD_SKILL_PATH", str(skill))
    for name in ("DRAWING2CAD_AGENT_BASE_URL", "DRAWING2CAD_AGENT_MODEL", "DRAWING2CAD_AGENT_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    api.services.cache_clear()
    store, _ = api.services()
    yield store, monkeypatch
    api.services.cache_clear()


def test_runs_are_unavailable_without_model_endpoint(web):
    store, _ = web
    source = store.add_source("Plate_dwg.pdf", b"%PDF-1.7", ANALYSIS)
    assert client.get("/api/capabilities").json()["runs"] is False
    res = client.post(f"/api/sources/{source['source_id']}/runs")
    assert res.status_code == 503 and res.json()["detail"]["code"] == "CAPABILITY_UNAVAILABLE"


def test_a_run_is_queued_with_a_model_endpoint(web):
    store, monkeypatch = web
    for name, value in (("BASE_URL", "https://example.test/v1"), ("MODEL", "m"), ("API_KEY", "k")):
        monkeypatch.setenv("DRAWING2CAD_AGENT_" + name, value)
    api.services.cache_clear()
    store, runner = api.services()
    submitted = []
    monkeypatch.setattr(runner, "submit", submitted.append)
    source = store.add_source("Plate_dwg.pdf", b"%PDF-1.7", ANALYSIS)
    assert client.get("/api/capabilities").json()["runs"] is True
    res = client.post(f"/api/sources/{source['source_id']}/runs")
    assert res.status_code == 201
    run = res.json()
    assert run["phase"] == "queued" and submitted == [run["run_id"]]
    assert client.get(f"/api/sources/{source['source_id']}/runs").json()[0]["run_id"] == run["run_id"]
    assert client.get(f"/api/runs/{run['run_id']}").json()["job"]["status"] == "queued"


@pytest.mark.parametrize("path", ["/api/runs/run_0000000000000000", "/api/runs/..%2Fsources", "/api/sources/src_zz/analysis",
                                  "/api/artifacts/art_0123456789abcdef/content", "/api/artifacts/../../etc/passwd/content"])
def test_unknown_or_malformed_ids_are_not_found(web, path):
    assert client.get(path).status_code == 404


def test_artifact_download_and_source_delete(web, step_file):
    store, _ = web
    source = store.add_source("Plate_dwg.pdf", b"%PDF-1.7", ANALYSIS)
    run = store.add_run(source["source_id"])
    artifact = store.add_artifact(run["run_id"], "step", "model/step", "Plätte.step", b"ISO-10303-21;", source["sha256"], 1)
    store.update_run(run["run_id"], artifacts=[artifact], phase="done", job={"status": "succeeded"})
    res = client.get(f"/api/artifacts/{artifact['artifact_id']}/content")
    assert res.content == b"ISO-10303-21;" and "UTF-8''Pl%C3%A4tte.step" in res.headers["content-disposition"]
    assert client.delete(f"/api/sources/{source['source_id']}").status_code == 204
    assert client.get(f"/api/runs/{run['run_id']}").status_code == 404


def test_run_files_list_open_and_archive_trace_and_part_state(web):
    store, _ = web
    source = store.add_source("Plate_dwg.pdf", b"%PDF-1.7", ANALYSIS)
    run_id = store.add_run(source["source_id"])["run_id"]
    (store.run_dir(run_id) / "trace" / "001-model-request.json").write_text("{}")
    part = store.mcp / "cad" / "runs" / ("web-" + run_id.removeprefix("run_") + "-plate")
    part.mkdir(parents=True)
    (part / "state.json").write_text('{"revision": 1}')
    (store.mcp / "cad" / "runs" / "web-0000000000000000-other").mkdir()

    listing = client.get(f"/api/runs/{run_id}/files").json()
    paths = [f["path"] for f in listing["files"]]
    assert paths == ["lauf/run.json", "lauf/trace/001-model-request.json", f"cad/{part.name}/state.json"]
    opened = client.get(listing["files"][2]["url"])
    assert opened.text == '{"revision": 1}' and opened.headers["content-type"].startswith("text/plain")
    assert opened.headers["content-disposition"].startswith("inline")
    with zipfile.ZipFile(io.BytesIO(client.get(listing["archive_url"]).content)) as archive:
        assert archive.namelist() == [f"{run_id}/{p}" for p in paths]
    assert client.get(f"/api/runs/{run_id}/files/lauf/../../sources").status_code == 404
    assert client.get(f"/api/runs/{run_id}/files/lauf%2F..%2F..%2Fsources%2F{source['source_id']}%2Fsource.pdf").status_code == 404


def test_a_restart_fails_unfinished_runs(web):
    store, _ = web
    source = store.add_source("Plate_dwg.pdf", b"%PDF-1.7", ANALYSIS)
    run = store.add_run(source["source_id"])
    api.services.cache_clear()
    restarted, _ = api.services()
    assert restarted.run(run["run_id"])["error"]["code"] == "RUN_INTERRUPTED"


def test_part_state_reads_serialized_results_of_either_field_style():
    assert part_state({"isError": False, "structuredContent": {"part": {"revision": 1}}}) == {"revision": 1}
    assert part_state({"is_error": False, "structured_content": {"part": {"revision": 2}}}) == {"revision": 2}
    assert part_state({"isError": True, "structuredContent": {"part": {"revision": 1}}}) is None


def test_part_state_from_a_real_call_tool_result():
    from mcp.types import CallToolResult, TextContent
    result = CallToolResult(content=[TextContent(type="text", text="{}")], structuredContent={"part": {"revision": 3}}, isError=False)
    assert part_state(result.model_dump(mode="json", by_alias=True)) == {"revision": 3}
