"""Agent runs through the web API and the shared domain service (ADR 0018). No model is called."""

import io
import json
import os
from pathlib import Path
import re
import socket
import threading
import time
import zipfile

import httpx2
import pytest
import uvicorn
from fastapi.testclient import TestClient
from pypdf import PdfWriter

from drawing2cad_mcp.local_model_client import DOMAIN_SKILL_REFERENCES
from drawing_demo import api
from drawing_demo.agent import model as model_module
from drawing_demo.agent import runner as runner_module
from drawing_demo.agent.mapping import artifact_view, part_view, phase_for, review_view, sheet_region

SHA = "a" * 64
TEST_MASTER_KEY = "MDEyMzQ1Njc4OWFiY2RlZjAxMjM0NTY3ODlhYmNkZWY="  # Base64 of 32 ASCII bytes, for tests only.


def description(source_id="drawing", source_sha256=SHA):
    source = {"source_id": source_id, "source_sha256": source_sha256, "page": 1, "coordinate_system": "normalized_displayed"}
    return {
        "schema_version": "1.0", "name": "Plate", "units": "mm", "coordinate_system": "right_handed_xyz",
        "evidence": [
            {"id": "e_len", "status": "explicit", "reason": "Printed 10.", "source": {**source, "view": "front", "region": [0.1, 0.1, 0.2, 0.2]}},
            {"id": "e_t", "status": "assumed", "reason": "Thickness not printed.", "source": {**source, "view": "side", "region": [0.5, 0.5, 0.6, 0.6]}},
        ],
        "parameters": [{"name": "length", "value": 10, "unit": "mm", "evidence_ids": ["e_len"]},
                       {"name": "thickness", "value": 5, "unit": "mm", "evidence_ids": ["e_t"]}],
        "features": [{"id": "base", "type": "box", "operation": "base", "length": {"parameter": "length"}, "width": 20,
                      "height": {"parameter": "thickness"}, "evidence_ids": ["e_len", "e_t"]}],
        "review_flags": [{"id": "f_edge", "target_id": "base", "status": "open", "reason": "Edge radius unclear.", "evidence_ids": ["e_t"]}],
    }


def pdf_bytes():
    writer = PdfWriter()
    writer.add_blank_page(width=300, height=200)
    stream = io.BytesIO()
    writer.write(stream)
    return stream.getvalue()


def test_phase_follows_the_tool_sequence():
    assert phase_for("pdf_render_page", "queued") == "analyzing"
    assert phase_for("build_from_description", "analyzing") == "modeling"
    assert phase_for("drawing_render", "modeling") == "drawing"
    assert phase_for("export_step", "drawing") == "validating"
    assert phase_for("part_export_review", "modeling") == "modeling"
    assert phase_for("model_projection_check", "modeling") == "modeling"
    assert phase_for("drawing_derive_views", "modeling") == "drawing"
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


def test_release_reports_its_drawing_status_and_released_files():
    """The STEP release records the drawing status; only files that the release names are released."""
    from drawing2cad_mcp.part_schema import part_validate
    state = {"description": description(), "build": {"status": "pass", "validation": {"checks": []}},
             "release": {"drawing": {"status": "failed", "reason": "The latest drawing render did not pass its checks."}}}
    review = review_view(state, part_validate(state["description"])["review_items"], (200, 100), released=True)
    assert review["release_state"] == "released"
    assert review["drawing"] == {"status": "failed", "reason": "The latest drawing render did not pass its checks.", "current": True,
                                 "delivery": "step_only", "pair_current": None}
    state["release"]["drawing_current"] = False
    assert review_view(state, [], (200, 100), released=True)["drawing"]["current"] is False
    assert review_view(state, [], (200, 100), released=False)["drawing"] is None
    artifact = {"artifact_id": "art_" + "2" * 32, "role": "drawing_diagnostic_preview", "media_type": "application/pdf",
                "filename": "d.pdf", "sha256": SHA, "size_bytes": 3, "revision": 1}
    assert artifact_view(artifact, "b" * 64, frozenset({artifact["artifact_id"]}))["released"] is True
    old = {**artifact, "artifact_id": "art_" + "3" * 32, "role": "technical_drawing"}
    view = artifact_view(old, "b" * 64, frozenset({artifact["artifact_id"]}))
    assert view["role"] == "drawing_pdf" and view["released"] is False


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


@pytest.mark.parametrize(("role", "media_type", "expected"), [
    ("released_step", "model/step", "step"), ("technical_drawing", "application/pdf", "drawing_pdf"),
    ("technical_drawing", "image/vnd.dxf", "drawing_dxf"), ("run_manifest", "application/json", "manifest"),
    ("part_description", "application/json", "part_description"), ("run_trace", "application/json", "trace"),
    ("domain_run_events", "application/json", "events"), ("drawing_report", "application/json", "report"),
    ("source_preview", "image/png", None),
])
def test_only_delivered_domain_artifacts_are_shown(role, media_type, expected):
    artifact = {"artifact_id": "art_" + "1" * 32, "role": role, "media_type": media_type, "filename": "f",
                "sha256": SHA, "size_bytes": 3, "revision": 2}
    view = artifact_view(artifact, "b" * 64)
    assert (view and view["role"]) == expected
    if view:
        assert view["model_revision"] == 2 and view["byte_count"] == 3 and view["source_sha256"] == "b" * 64


@pytest.fixture
def environment(tmp_path, monkeypatch):
    monkeypatch.setenv("DRAWING2CAD_DATA_DIR", str(tmp_path / "data"))
    # A fixed test master key (ADR 0028). It encrypts only test keys in the temporary data directory.
    monkeypatch.setenv("DRAWING2CAD_SECRET_KEY", TEST_MASTER_KEY)
    monkeypatch.delenv("DRAWING2CAD_SECRET_KEY_FILE", raising=False)
    skill = tmp_path / "SKILL.md"
    skill.write_text("skill")
    (tmp_path / "references").mkdir()
    for name in DOMAIN_SKILL_REFERENCES:
        (tmp_path / "references" / name).write_text(name)
    monkeypatch.setenv("DRAWING2CAD_SKILL_PATH", str(skill))
    for name in ("BASE_URL", "MODEL", "API_KEY", "PROFILES"):
        monkeypatch.delenv("DRAWING2CAD_AGENT_" + name, raising=False)
    return monkeypatch


def with_model_endpoint(monkeypatch):
    for name, value in (("BASE_URL", "https://example.test/v1"), ("MODEL", "m"), ("API_KEY", "k")):
        monkeypatch.setenv("DRAWING2CAD_AGENT_" + name, value)


def upload(client):
    res = client.post("/api/sources", files={"file": ("Plate_dwg.pdf", pdf_bytes(), "application/pdf")})
    assert res.status_code == 200, res.text
    return res.json()


def test_runs_are_unavailable_without_model_endpoint(environment):
    with TestClient(api.create_app()) as client:
        source = upload(client)
        capabilities = client.get("/api/capabilities").json()
        assert capabilities["runs"] is False and capabilities["agent_model"] is None
        res = client.post(f"/api/sources/{source['source_id']}/runs")
        assert res.status_code == 503 and res.json()["detail"]["code"] == "CAPABILITY_UNAVAILABLE"


def test_a_run_is_queued_with_a_model_endpoint(environment):
    with_model_endpoint(environment)
    submitted = []
    environment.setattr(runner_module.AgentRunner, "submit", lambda self, run_id, settings: submitted.append(run_id))
    with TestClient(api.create_app()) as client:
        source = upload(client)
        capabilities = client.get("/api/capabilities").json()
        assert capabilities["runs"] is True and capabilities["agent_model"] == "m" and capabilities["agent_profile"] == "Standard"
        res = client.post(f"/api/sources/{source['source_id']}/runs")
        assert res.status_code == 201
        run = res.json()
        assert run["phase"] == "queued" and run["part"] is None and submitted == [run["run_id"]]
        assert run["agent"] == {"model": "m", "profile": "Standard", "reasoning_effort": None, "skill_version": None,
                                "mcp_version": api.mcp_version, "limits": runner_module.LIMITS}
        assert [r["run_id"] for r in client.get(f"/api/sources/{source['source_id']}/runs").json()] == [run["run_id"]]
        assert client.get(f"/api/runs/{run['run_id']}").json()["job"]["status"] == "queued"


def with_two_profiles(monkeypatch):
    monkeypatch.setenv("DRAWING2CAD_AGENT_PROFILES", "Foundry,OpenRouter")
    for prefix, model in (("FOUNDRY", "gpt-a"), ("OPENROUTER", "vendor/b")):
        for name, value in (("BASE_URL", f"https://{prefix.lower()}.test/v1"), ("MODEL", model), ("API_KEY", "secret-" + prefix)):
            monkeypatch.setenv(f"DRAWING2CAD_AGENT_{prefix}_{name}", value)
    monkeypatch.setenv("DRAWING2CAD_AGENT_OPENROUTER_API", "responses")


def test_a_run_uses_the_profile_selected_at_its_start_and_keeps_the_active_profile(environment):
    with_two_profiles(environment)
    environment.setenv("DRAWING2CAD_AGENT_OPENROUTER_STEP_BUDGET", "12")
    environment.setenv("DRAWING2CAD_AGENT_OPENROUTER_REASONING_EFFORT", "low")
    submitted = []
    environment.setattr(runner_module.AgentRunner, "submit", lambda self, run_id, settings: submitted.append(
        (settings.model, settings.api_key, settings.api)))
    with TestClient(api.create_app()) as client:
        source = upload(client)
        runs = f"/api/sources/{source['source_id']}/runs"
        chosen = client.post(runs, json={"profile": "OpenRouter"})
        assert chosen.status_code == 201
        run = chosen.json()
        assert run["agent"]["profile"] == "OpenRouter" and run["agent"]["model"] == "vendor/b"
        assert run["agent"]["reasoning_effort"] == "low" and run["agent"]["limits"]["step_budget"] == 12
        assert submitted == [("vendor/b", "secret-OPENROUTER", "responses")]
        # The active profile of the settings does not change.
        assert client.get("/api/agent/profiles").json()["active"] == "Foundry"
        # Without a selection, a run uses the active profile, as before.
        for body in ({}, {"profile": None}, None):
            res = client.post(runs, json=body) if body is not None else client.post(runs)
            assert res.status_code == 201 and res.json()["agent"]["profile"] == "Foundry"
        for name in ("Missing", ""):
            res = client.post(runs, json={"profile": name})
            assert res.status_code == 422 and res.json()["detail"]["code"] == "UNKNOWN_PROFILE"
        assert len(submitted) == 4
        assert client.get("/api/capabilities").json()["agent_ready"] is True


def test_a_selected_profile_with_a_locked_key_fails_at_start(environment):
    from test_config_store import OPENROUTER, OTHER_MASTER_KEY
    with_model_endpoint(environment)
    with TestClient(api.create_app()) as client:
        client.put("/api/agent/profiles/Hosted", json={**OPENROUTER, "api_key": "k"})
    environment.setenv("DRAWING2CAD_SECRET_KEY", OTHER_MASTER_KEY)
    submitted = []
    environment.setattr(runner_module.AgentRunner, "submit", lambda self, run_id, settings: submitted.append(run_id))
    with TestClient(api.create_app()) as client:
        source = upload(client)
        res = client.post(f"/api/sources/{source['source_id']}/runs", json={"profile": "Hosted"})
        assert res.status_code == 409 and res.json()["detail"]["code"] == "PROFILE_KEY_LOCKED" and submitted == []
        # The active environment profile still starts runs.
        assert client.post(f"/api/sources/{source['source_id']}/runs").status_code == 201


def test_a_selected_profile_without_a_key_fails_at_start(environment, tmp_path):
    from drawing_demo.agent import config_store
    from test_config_store import OPENROUTER, OTHER_MASTER_KEY
    with_model_endpoint(environment)
    with TestClient(api.create_app()) as client:
        client.put("/api/agent/profiles/Hosted", json={**OPENROUTER, "api_key": "k"})
    new = tmp_path / "new.key"
    new.write_text(OTHER_MASTER_KEY, encoding="ascii")
    config_store.main(["forget-keys", "--database", str(tmp_path / "data" / "config.sqlite"), "--new-key-file", str(new), "--yes"])
    environment.setenv("DRAWING2CAD_SECRET_KEY", OTHER_MASTER_KEY)
    environment.setattr(runner_module.AgentRunner, "submit", lambda self, run_id, settings: None)
    with TestClient(api.create_app()) as client:
        source = upload(client)
        res = client.post(f"/api/sources/{source['source_id']}/runs", json={"profile": "Hosted"})
        assert res.status_code == 409 and res.json()["detail"]["code"] == "PROFILE_KEY_MISSING"


def test_capabilities_report_that_runs_cannot_start_without_the_skill(environment, tmp_path):
    with_model_endpoint(environment)
    environment.setenv("DRAWING2CAD_SKILL_PATH", str(tmp_path / "missing" / "SKILL.md"))
    with TestClient(api.create_app()) as client:
        capabilities = client.get("/api/capabilities").json()
        assert capabilities["agent_ready"] is False and capabilities["runs"] is False


def test_profiles_are_listed_without_keys(environment):
    with_two_profiles(environment)
    with TestClient(api.create_app()) as client:
        res = client.get("/api/agent/profiles")
        data = res.json()
        assert data["active"] == "Foundry"
        assert [(p["name"], p["model"], p["api"], p["origin"], p["key_set"]) for p in data["profiles"]] == [
            ("Foundry", "gpt-a", "chat", "env", True), ("OpenRouter", "vendor/b", "responses", "env", True)]
        assert "secret" not in res.text


def test_a_new_run_uses_the_selected_profile(environment):
    with_two_profiles(environment)
    submitted = []
    environment.setattr(runner_module.AgentRunner, "submit", lambda self, run_id, settings: submitted.append(settings.model))
    with TestClient(api.create_app()) as client:
        source = upload(client)
        first = client.post(f"/api/sources/{source['source_id']}/runs").json()
        assert client.put("/api/agent/active", json={"name": "OpenRouter"}).json()["active"] == "OpenRouter"
        capabilities = client.get("/api/capabilities").json()
        assert capabilities["agent_profile"] == "OpenRouter" and capabilities["agent_model"] == "vendor/b"
        second = client.post(f"/api/sources/{source['source_id']}/runs").json()
        assert submitted == ["gpt-a", "vendor/b"]
        assert first["agent"]["profile"] == "Foundry" and second["agent"]["profile"] == "OpenRouter"
        # The first run keeps the profile that was active when it was created.
        assert client.get(f"/api/runs/{first['run_id']}").json()["agent"]["model"] == "gpt-a"


def test_no_profile_disables_runs_and_unknown_profiles_are_rejected(environment):
    with_two_profiles(environment)
    with TestClient(api.create_app()) as client:
        source = upload(client)
        res = client.put("/api/agent/active", json={"name": "Missing"})
        assert res.status_code == 422 and res.json()["detail"]["code"] == "UNKNOWN_PROFILE"
        assert client.put("/api/agent/active", json={"name": None}).json()["active"] is None
        capabilities = client.get("/api/capabilities").json()
        assert capabilities["runs"] is False and capabilities["agent_model"] is None and capabilities["agent_profile"] is None
        assert client.post(f"/api/sources/{source['source_id']}/runs").status_code == 503


@pytest.mark.parametrize("path", ["/api/runs/run_" + "0" * 32, "/api/runs/..%2Fsources", "/api/sources/src_zz/analysis",
                                  "/api/sources/src_" + "0" * 32, "/api/artifacts/art_" + "0" * 32 + "/content",
                                  "/api/artifacts/../../etc/passwd/content"])
def test_unknown_or_malformed_ids_are_not_found(environment, path):
    with TestClient(api.create_app()) as client:
        assert client.get(path).status_code == 404


def test_artifact_download_reads_the_domain_store(environment):
    with TestClient(api.create_app()) as client:
        source = upload(client)
        backend = client.app.state.services.backend
        rendered = backend.call("pdf_render_page", source_id=source["source_id"], include_image=False)
        artifact = rendered["artifact"]
        res = client.get(f"/api/artifacts/{artifact['artifact_id']}/content")
        assert res.status_code == 200 and res.content.startswith(b"\x89PNG")
        assert res.headers["content-type"] == "image/png" and artifact["filename"] in res.headers["content-disposition"]


def test_run_files_list_only_the_record_and_trace_of_the_run(environment):
    with TestClient(api.create_app()) as client:
        source = upload(client)
        jobs = client.app.state.services.jobs
        run_id = jobs.add(source["source_id"])["run_id"]
        (jobs.directory(run_id) / "trace" / "001-model-request.json").write_text("{}")
        listing = client.get(f"/api/runs/{run_id}/files").json()
        paths = [f["path"] for f in listing["files"]]
        assert paths == ["run.json", "trace/001-model-request.json"]
        opened = client.get(listing["files"][1]["url"])
        assert opened.text == "{}" and opened.headers["content-type"].startswith("text/plain")
        assert opened.headers["content-disposition"].startswith("inline")
        with zipfile.ZipFile(io.BytesIO(client.get(listing["archive_url"]).content)) as archive:
            assert archive.namelist() == [f"{run_id}/{p}" for p in paths]
        assert client.get(f"/api/runs/{run_id}/files/../../domain").status_code == 404
        assert client.get(f"/api/runs/{run_id}/files/trace%2F..%2F..%2F..%2Fdomain").status_code == 404


def test_deleting_a_source_removes_it_with_its_runs(environment):
    with TestClient(api.create_app()) as client:
        source, other = upload(client), upload(client)
        jobs = client.app.state.services.jobs
        run = jobs.add(source["source_id"])
        kept = jobs.add(other["source_id"])
        assert client.delete(f"/api/sources/{source['source_id']}").json()["detail"]["code"] == "RUN_ACTIVE"
        jobs.update(run["run_id"], phase="failed", job={"status": "failed"})
        assert client.delete(f"/api/sources/{source['source_id']}").status_code == 204
        assert [s["source_id"] for s in client.get("/api/sources").json()] == [other["source_id"]]
        assert client.get(f"/api/sources/{source['source_id']}").status_code == 404
        assert client.get(f"/api/runs/{run['run_id']}").status_code == 404
        assert client.get(f"/api/runs/{kept['run_id']}").status_code == 200
        assert client.delete(f"/api/sources/{source['source_id']}").status_code == 404


def test_a_restart_fails_unfinished_runs(environment):
    with TestClient(api.create_app()) as client:
        run = client.app.state.services.jobs.add(upload(client)["source_id"])
    with TestClient(api.create_app()) as client:
        assert client.get(f"/api/runs/{run['run_id']}").json()["error"]["code"] == "RUN_INTERRUPTED"


def test_polling_a_run_does_not_use_the_step_budget_of_its_part_run(environment):
    # Each part_read is a recorded CAD call. The UI polls runs every second.
    with TestClient(api.create_app()) as client:
        services = client.app.state.services
        source = upload(client)
        run = services.jobs.add(source["source_id"])
        part_run = run["part_prefix"] + "-plate"
        services.backend.call("part_create", run_id=part_run, description=description(source["source_id"], source["sha256"]),
                              sources=[{"source_id": source["source_id"], "sha256": source["sha256"], "role": "construction"}])
        services.jobs.update(run["run_id"], part_run_id=part_run, job={"status": "running"})
        calls = []
        original = services.backend.call
        environment.setattr(services.backend, "call", lambda operation, **arguments: calls.append(operation) or original(operation, **arguments))
        for _ in range(3):
            assert client.get(f"/api/runs/{run['run_id']}").json()["part"] is None
        assert "part_read" not in calls
        services.jobs.update(run["run_id"], phase="done", job={"status": "succeeded"})
        for _ in range(3):
            assert client.get(f"/api/runs/{run['run_id']}").json()["part"]["revision"] == 1
        assert calls.count("part_read") == 1


def test_run_artifacts_are_in_creation_order(environment):
    # The domain lists artifacts by ID. The UI shows the latest drawing of a revision, so the order must be creation order.
    with TestClient(api.create_app()) as client:
        services = client.app.state.services
        source = upload(client)
        run = services.jobs.add(source["source_id"])
        part_run = run["part_prefix"] + "-plate"
        services.backend.call("part_create", run_id=part_run, description=description(source["source_id"], source["sha256"]),
                              sources=[{"source_id": source["source_id"], "sha256": source["sha256"], "role": "construction"}])
        services.jobs.update(run["run_id"], part_run_id=part_run, phase="done", job={"status": "succeeded"})
        drawing = {"role": "technical_drawing", "media_type": "application/pdf", "sha256": SHA, "size_bytes": 1, "revision": 1}
        listed = [{**drawing, "artifact_id": "art_" + "a" * 32, "filename": "later.pdf", "created": 2.0},
                  {**drawing, "artifact_id": "art_" + "b" * 32, "filename": "earlier.pdf", "created": 1.0}]
        original = api._all
        environment.setattr(api, "_all", lambda backend, operation, **arguments:
                            listed if operation == "artifact_list" else original(backend, operation, **arguments))
        artifacts = client.get(f"/api/runs/{run['run_id']}").json()["artifacts"]
        assert [a["filename"] for a in artifacts] == ["earlier.pdf", "later.pdf"]


def test_a_conversation_error_fails_the_run_even_with_a_built_part(environment):
    with TestClient(api.create_app()) as client:
        services = client.app.state.services
        source = upload(client)
        run = services.jobs.add(source["source_id"])
        services.jobs.update(run["run_id"], part_run_id=run["part_prefix"] + "-plate", phase="drawing")
        summary = {"status": "failed", "error": {"type": "RuntimeError", "message": "Model endpoint returned HTTP 429"}}
        services.runner.finish(run["run_id"], summary)  # The domain part does not exist; keep the conversation error.
        result = services.jobs.get(run["run_id"])
        assert result["error"]["code"] == "AGENT_FAILED" and "HTTP 429" in result["error"]["message"]
        assert result["failed_phase"] == "drawing"


@pytest.mark.parametrize("note_text", ["", "Previous review note"])
def test_a_released_part_succeeds_with_a_warning_when_the_final_report_fails(environment, note_text):
    with TestClient(api.create_app()) as client:
        services = client.app.state.services
        source = upload(client)
        run = services.jobs.add(source["source_id"])
        part_run = run["part_prefix"] + "-plate"
        services.backend.call("part_create", run_id=part_run, description=description(source["source_id"], source["sha256"]),
                              sources=[{"source_id": source["source_id"], "sha256": source["sha256"], "role": "construction"}])
        if note_text:
            services.runner.store_report(part_run, note_text)
        note_url = f"/api/runs/{run['run_id']}/note"
        services.jobs.update(run["run_id"], part_run_id=part_run, phase="validating")
        previous_note = client.get(note_url).json()
        original = services.backend.call
        environment.setattr(services.backend, "call", lambda operation, **arguments:
                            {"part": {"build": {"status": "pass"}, "release": {"sha256": SHA}}}
                            if operation == "part_read" else original(operation, **arguments))
        environment.setattr(services.runner, "store_report", lambda *args:
                            pytest.fail("No final text was supplied; the note must not change."))
        services.runner.finish(run["run_id"], {
            "status": "failed", "error": {"type": "RuntimeError", "message": "Model endpoint returned HTTP 429"}})
        result = services.jobs.get(run["run_id"])
        assert result["phase"] == "done" and result["job"]["status"] == "succeeded"
        assert result["job"]["progress"] == 1 and result["job"]["finished_at"] is not None
        assert result["error"] is None and result["failed_phase"] is None
        assert result["warning"] == {
            "code": "AGENT_REPORT_MISSING",
            "message": "Final report missing: RuntimeError: Model endpoint returned HTTP 429"}
        assert client.get(note_url).json() == previous_note
        assert previous_note["text"] == note_text
        # The web adapter forwards the warning without a domain result.
        view = api.run_view(services, {**result, "part_run_id": None})
        assert view["warning"] == result["warning"] and view["error"] is None


def test_a_built_part_without_release_still_fails_after_a_conversation_error(environment):
    with TestClient(api.create_app()) as client:
        services = client.app.state.services
        source = upload(client)
        run = services.jobs.add(source["source_id"])
        services.jobs.update(run["run_id"], part_run_id=run["part_prefix"] + "-plate", phase="drawing")
        original = services.backend.call
        environment.setattr(services.backend, "call", lambda operation, **arguments:
                            {"part": {"build": {"status": "pass"}, "release": None}}
                            if operation == "part_read" else original(operation, **arguments))
        services.runner.finish(run["run_id"], {
            "status": "failed", "error": {"type": "RuntimeError", "message": "Model endpoint returned HTTP 429"}})
        result = services.jobs.get(run["run_id"])
        assert result["phase"] == "failed" and result["job"]["status"] == "failed"
        assert result["error"]["code"] == "AGENT_FAILED" and "HTTP 429" in result["error"]["message"]
        assert result["failed_phase"] == "drawing" and result["warning"] is None


def test_a_repeated_failed_request_fails_the_run_with_its_tool_field_and_count_without_a_part(environment):
    with TestClient(api.create_app()) as client:
        services = client.app.state.services
        source = upload(client)
        run = services.jobs.add(source["source_id"])
        summary = {"status": "no_progress", "model_turns": 3, "tool_requests": 2, "mcp_calls": 1, "blocked_requests": 1,
                   "no_progress": {"tool": "pdf_calibrate", "code": "INVALID_ARGUMENTS", "repeat_count": 2,
                                   "target": "/references/0/source_region/2", "message": "1 is greater than the maximum of 1"}}
        services.runner.finish(run["run_id"], summary)
        result = client.get(f"/api/runs/{run['run_id']}").json()
        assert result["error"]["code"] == "AGENT_NO_PROGRESS"
        assert result["error"]["field"] == "/references/0/source_region/2"
        assert "pdf_calibrate request 2 times (INVALID_ARGUMENTS" in result["error"]["message"]
        assert result["iterations"]["mcp_calls"] == 1 and result["iterations"]["blocked_requests"] == 1


@pytest.mark.parametrize("phase", ["model_inference", None])
def test_an_exhausted_deadline_without_a_part_is_a_time_budget_result(environment, phase):
    with TestClient(api.create_app()) as client:
        services = client.app.state.services
        source = upload(client)
        run = services.jobs.add(source["source_id"])
        summary = {"status": "time_budget_reached"}
        if phase:
            summary["time_budget"] = {"phase": phase, "message": "RuntimeError: Model endpoint did not answer: timed out"}
        services.runner.finish(run["run_id"], summary)
        error = services.jobs.get(run["run_id"])["error"]
        assert error["code"] == "AGENT_TIME_BUDGET"
        assert ("during model inference" in error["message"] and "did not answer" in error["message"]) == bool(phase)


@pytest.mark.parametrize(("part", "expected"), [
    ({"build": {"status": "pass"}, "release": None}, "AGENT_TIME_BUDGET"),
    ({"build": {"status": "pass"}, "release": {"sha256": "a" * 64}}, None),
])
def test_an_exhausted_deadline_before_a_release_fails_the_run(environment, part, expected):
    with TestClient(api.create_app()) as client:
        services = client.app.state.services
        source = upload(client)
        run = services.jobs.add(source["source_id"])
        services.jobs.update(run["run_id"], part_run_id=run["part_prefix"] + "-plate", phase="drawing")
        original = services.backend.call
        environment.setattr(services.backend, "call", lambda operation, **arguments:
                            {"part": part} if operation == "part_read" else original(operation, **arguments))
        services.runner.finish(run["run_id"], {"status": "time_budget_reached",
                                               "time_budget": {"phase": "model_inference", "message": "timed out"}})
        result = services.jobs.get(run["run_id"])
        assert (result["error"] or {}).get("code") == expected
        if expected:
            assert "before the agent released the STEP model" in result["error"]["message"]
        else:
            assert result["job"]["status"] == "succeeded"


def test_the_run_note_is_revisioned_and_keeps_the_agent_report(environment):
    with TestClient(api.create_app()) as client:
        services = client.app.state.services
        source = upload(client)
        run = services.jobs.add(source["source_id"])
        assert client.get(f"/api/runs/{run['run_id']}/note").json()["detail"]["code"] == "NO_PART"
        part_run = run["part_prefix"] + "-plate"
        services.backend.call("part_create", run_id=part_run, description=description(source["source_id"], source["sha256"]),
                              sources=[{"source_id": source["source_id"], "sha256": source["sha256"], "role": "construction"}])
        services.jobs.update(run["run_id"], part_run_id=part_run, job={"status": "running"})
        note = f"/api/runs/{run['run_id']}/note"
        assert client.get(note).json() == {"revision": 0, "text": ""}
        # The agent writes its report into the note at the end of the run.
        assert client.put(note, json={"expected_revision": 0, "text": "x"}).json()["detail"]["code"] == "RUN_ACTIVE"
        (services.jobs.directory(run["run_id"]) / "summary.json").write_text('{"final_text": "Report"}')
        services.runner.store_report(part_run, "Report")
        services.jobs.update(run["run_id"], phase="done", job={"status": "succeeded"})
        assert client.get(note).json() == {"revision": 1, "text": "Report"}
        assert client.put(note, json={"expected_revision": 1, "text": "Report\nRadius clarified"}).json()["revision"] == 2
        stale = client.put(note, json={"expected_revision": 1, "text": "y"})
        assert stale.status_code == 409 and stale.json()["detail"]["code"] == "REVISION_CONFLICT"
        # The agent report comes from the trace, so a changed note does not change it.
        assert client.get(f"/api/runs/{run['run_id']}").json()["agent_report"] == "Report"
        assert client.get("/api/capabilities").json()["notes"] is True


class Server(uvicorn.Server):
    def install_signal_handlers(self):
        pass  # Keep the signal handlers of the test runner.


def scripted_model(plan, payload, timeout):
    """Create a part through the real MCP endpoint, then answer. The prompt names the source and run prefix."""
    system = payload["messages"][0]["content"]
    source_id, digest = re.search(r"source ID (src_[0-9a-f]{32}) \(SHA-256 ([0-9a-f]{64})\)", system).groups()
    prefix = re.search(r"run IDs that start with (web-[0-9a-f]+)-", system).group(1)
    if len(payload["messages"]) > 2:
        return {"message": {"role": "assistant", "content": "Report: part created, not built."}}
    calls = [
        {"function": {"name": "pdf_info", "arguments": {"source_id": source_id}}},
        {"function": {"name": "part_create", "arguments": {
            "run_id": f"{prefix}-plate", "description": description(source_id, digest),
            "sources": [{"source_id": source_id, "sha256": digest, "role": "construction"}]}}},
    ]
    return {"message": {"role": "assistant", "content": "", "tool_calls": calls}}


def test_an_agent_run_uses_the_mounted_mcp_endpoint(environment):
    with_model_endpoint(environment)
    environment.setattr(runner_module, "make_model_call", lambda settings: scripted_model)
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
        environment.setenv("DRAWING2CAD_MCP_URL", f"http://127.0.0.1:{port}/mcp")
        server = Server(uvicorn.Config(api.create_app(), log_config=None, access_log=False))
        thread = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
        thread.start()
        try:
            base = f"http://127.0.0.1:{port}"
            with httpx2.Client(base_url=base, timeout=30, trust_env=False) as client:
                deadline = time.monotonic() + 10
                while not server.started and time.monotonic() < deadline:
                    time.sleep(0.05)
                source = upload(client)
                run_id = client.post(f"/api/sources/{source['source_id']}/runs").json()["run_id"]
                deadline = time.monotonic() + 60
                while (run := client.get(f"/api/runs/{run_id}").json())["job"]["status"] in ("queued", "running"):
                    assert time.monotonic() < deadline, run
                    time.sleep(0.2)
                files = [f["path"] for f in client.get(f"/api/runs/{run_id}/files").json()["files"]]
                timeline = client.get(f"/api/runs/{run_id}/steps").json()
        finally:
            server.should_exit = True
            thread.join(10)
    # The part exists in the domain store, but without a build there is no model to deliver.
    assert run["error"]["code"] == "AGENT_NO_MODEL", run
    # The run failed while modeling; the report is the run note, not the error message.
    assert run["failed_phase"] == "modeling" and "Report" not in run["error"]["message"]
    assert run["part"]["revision"] == 1 and [p["name"] for p in run["part"]["parameters"]] == ["length", "thickness"]
    assert run["agent_report"] == "Report: part created, not built."
    # Two model turns: one with two tool requests, one with the final answer. Both requests reached the MCP.
    assert run["iterations"] == {"model_turns": 2, "tool_requests": 2, "step_budget": runner_module.LIMITS["step_budget"],
                                 "mcp_calls": 2, "blocked_requests": 0}
    assert run["review"]["release_state"] == "draft" and run["artifacts"] == []
    assert "summary.json" in files and "trace/trace.jsonl" in files
    # The timeline shows the same run: skill references, both model turns, and both tool calls with their results.
    assert [(s["kind"], s.get("tool")) for s in timeline["steps"] if s["kind"] != "skill"] == [
        ("model", None), ("tool", "pdf_info"), ("tool", "part_create"), ("model", None)]
    assert all(s["status"] == "ok" for s in timeline["steps"] if s["kind"] == "tool")
    assert timeline["summary"]["model_turns"] == 2


def test_ui_profiles_are_normalized_keep_their_key_and_persist(environment, tmp_path):
    with TestClient(api.create_app()) as client:
        assert client.get("/api/capabilities").json()["runs"] is False
        res = client.put("/api/agent/profiles/Foundry", json={
            "provider": "azure", "endpoint": "https://res.cognitiveservices.azure.com/openai/deployments/x/chat?api-version=1",
            "model": "gpt-dep", "api": "responses", "api_key": "azure-secret", "reasoning_effort": "medium"})
        assert res.status_code == 200 and "azure-secret" not in res.text
        client.put("/api/agent/profiles/OpenRouter", json={"provider": "openrouter", "model": "vendor/m", "api_key": "or-secret"})
        # A change without key keeps the stored key.
        res = client.put("/api/agent/profiles/OpenRouter", json={"provider": "openrouter", "model": "vendor/n"})
        profiles = {p["name"]: p for p in res.json()["profiles"]}
        assert res.json()["active"] == "Foundry"
        assert profiles["Foundry"]["base_url"] == "https://res.cognitiveservices.azure.com/openai/v1"
        assert profiles["OpenRouter"].pop("revision") > profiles["Foundry"]["revision"]
        assert profiles["OpenRouter"] == {"name": "OpenRouter", "provider": "openrouter", "origin": "ui",
                                          "base_url": "https://openrouter.ai/api/v1", "model": "vendor/n", "api": "chat",
                                          "reasoning_effort": None, "key_set": True, "key_locked": False, "limits": {}}
        assert client.put("/api/agent/active", json={"name": "OpenRouter"}).status_code == 200
        assert client.get("/api/capabilities").json()["agent_model"] == "vendor/n"
    stored = tmp_path / "data" / "config.sqlite"
    if os.name == "posix":  # Windows has no POSIX file modes. The backend runs in its Linux container.
        assert stored.stat().st_mode & 0o077 == 0
    # The database and its write-ahead log contain no key in plain text.
    for path in stored.parent.glob("config.sqlite*"):
        assert b"or-secret" not in path.read_bytes() and b"azure-secret" not in path.read_bytes()
    with TestClient(api.create_app()) as client:
        assert client.get("/api/agent/profiles").json()["active"] == "OpenRouter"
        runner = client.app.state.services.runner
        assert runner.settings.api_key == "or-secret" and runner.settings.api_key_header == "Authorization"
        assert runner.profiles.get("Foundry").api_key_header == "api-key"
        assert client.delete("/api/agent/profiles/OpenRouter").json()["active"] == "Foundry"


@pytest.mark.parametrize("body, field", [
    ({"provider": "azure", "endpoint": "http://res.openai.azure.com", "model": "m", "api_key": "k"}, "endpoint"),
    ({"provider": "openrouter", "model": " ", "api_key": "k"}, "model"),
    ({"provider": "openrouter", "model": "m"}, "api_key"),
    ({"provider": "openrouter", "model": "m", "api_key": "k", "reasoning_effort": "max"}, "reasoning_effort"),
])
def test_invalid_ui_profiles_are_rejected(environment, body, field):
    with TestClient(api.create_app()) as client:
        res = client.put("/api/agent/profiles/P", json=body)
        assert res.status_code == 422 and res.json()["detail"]["field"] == field


def test_environment_profiles_are_read_only(environment):
    with_two_profiles(environment)
    with TestClient(api.create_app()) as client:
        res = client.put("/api/agent/profiles/Foundry", json={"provider": "openrouter", "model": "m", "api_key": "k"})
        assert res.status_code == 409 and res.json()["detail"]["code"] == "PROFILE_READ_ONLY"
        assert client.delete("/api/agent/profiles/Foundry").status_code == 409


def test_the_connection_check_sends_one_request_with_one_tool(environment):
    with_two_profiles(environment)
    sent = []

    def answer(request):
        sent.append((str(request.url), json.loads(request.content)))
        return httpx2.Response(200, json={"output": [{"type": "message", "content": [{"type": "output_text", "text": "OK"}]}]})

    real_client_for = model_module.client_for
    environment.setattr(model_module, "client_for", lambda settings: real_client_for(settings, httpx2.MockTransport(answer)))
    with TestClient(api.create_app()) as client:
        result = client.post("/api/agent/profiles/OpenRouter/check").json()
        assert result["ok"] is True and result["message"] == "OK"
        assert sent[0][0] == "https://openrouter.test/v1/responses"
        assert [tool["name"] for tool in sent[0][1]["tools"]] == ["noop"]
        assert client.post("/api/agent/profiles/Missing/check").status_code == 404


def test_the_skill_version_comes_from_the_front_matter(tmp_path):
    skill = tmp_path / "SKILL.md"
    runner = runner_module.AgentRunner(None, None, None, skill, "")
    assert runner.skill_version is None
    skill.write_text('---\nname: drawing2cad\nmetadata:\n  version: "0.20.0"\n---\n\n# drawing2cad\n')
    assert runner.skill_version == "0.20.0"
    skill.write_text("# drawing2cad\n\n  version: 1\n")
    assert runner.skill_version is None


def test_drawing_acceptance_and_verification_artifacts_are_shown_separately():
    from drawing_demo.agent.mapping import acceptance_view, artifact_view

    acceptance = {"status": "unverified", "reason": "1 mandatory verification findings block the acceptance.",
                  "verification": {"validity": "current", "status": "fail",
                                   "gate": {"passed": False, "blocking_count": 1, "reviewed": [],
                                            "blocking": [{"rule_id": "MODEL-01", "status": "fail", "feature": "top", "message": "Missing edges."}]}}}
    view = acceptance_view(acceptance)
    assert view["status"] == "unverified" and view["verification"]["gate_passed"] is False
    assert view["verification"]["blocking"] == [{"rule_id": "MODEL-01", "status": "fail", "feature": "top", "message": "Missing edges."}]
    assert acceptance_view(None) is None
    base = {"artifact_id": "art_" + "a" * 32, "filename": "f", "sha256": "b" * 64, "size_bytes": 1, "revision": 1}
    report = artifact_view({**base, "role": "drawing_verification_report", "media_type": "application/json"}, "c" * 64)
    preview = artifact_view({**base, "role": "drawing_verification_preview", "media_type": "image/png"}, "c" * 64)
    diagnostic = artifact_view({**base, "role": "drawing_diagnostic_preview", "media_type": "application/pdf"}, "c" * 64)
    assert (report["role"], preview["role"], diagnostic["role"]) == ("verification_report", "verification_preview", "drawing_diagnostic")


def test_run_view_reads_the_drawing_acceptance_for_each_request(tmp_path):
    from types import SimpleNamespace

    from drawing_demo.api import run_view

    states = iter(["accepted", "unverified"])

    class Backend:
        def call(self, operation, **arguments):
            if operation == "source_get":
                return {"source_id": "src", "sha256": SHA}
            if operation == "artifact_list":
                return {"items": [], "next_cursor": None}
            assert operation == "drawing_read" and arguments == {"run_id": "part"}
            return {"revision": 1, "acceptance": {"status": next(states), "reason": None, "verification": None}}

    cached = {"part": {"revision": 1}, "review": {"release_state": "released", "drawing_acceptance": None}, "artifacts": []}
    services = SimpleNamespace(backend=Backend(), result=lambda record, revision=None: cached,
                               analysis=lambda source: {"drawing": {"sheet_size_mm": [420, 297]}},
                               jobs=SimpleNamespace(directory=lambda run_id: tmp_path))
    record = {"run_id": "run", "source_id": "src", "phase": "done", "job": {"status": "succeeded"}, "error": None, "part_run_id": "part"}
    assert run_view(services, record)["review"]["drawing_acceptance"]["status"] == "accepted"
    # The cached result stays, but the acceptance is new.
    assert run_view(services, record)["review"]["drawing_acceptance"]["status"] == "unverified"
    assert cached["review"]["drawing_acceptance"] is None


def test_review_view_marks_a_changed_complete_service_pair_as_outdated():
    from drawing_demo.agent.mapping import review_view

    state = {"build": {"status": "pass"}, "release": {"delivery": "complete_service", "pair_current": False, "drawing_current": True,
                                                      "pair_reason": "The released PDF file changed after the release.",
                                                      "drawing": {"status": "accepted", "reason": None}}}
    drawing = review_view(state, [], (420.0, 297.0), released=True)["drawing"]
    assert drawing == {"status": "accepted", "reason": "The released PDF file changed after the release.", "current": False,
                       "delivery": "complete_service", "pair_current": False}
    state["release"].update(pair_current=True, pair_reason=None)
    assert review_view(state, [], (420.0, 297.0), released=True)["drawing"]["current"] is True


def test_run_view_reads_the_release_freshness_for_each_request(tmp_path):
    from types import SimpleNamespace

    from drawing_demo.api import run_view

    pair = iter([True, False])

    class Backend:
        def call(self, operation, **arguments):
            if operation == "source_get":
                return {"source_id": "src", "sha256": SHA}
            if operation == "artifact_list":
                return {"items": [], "next_cursor": None}
            current = next(pair)
            return {"revision": 1, "acceptance": None, "release": {"delivery": "complete_service", "drawing": {"status": "accepted", "reason": None},
                                                    "drawing_current": True, "pair_current": current,
                                                    "pair_reason": None if current else "The released PDF file changed after the release."}}

    cached = {"part": {"revision": 1}, "review": {"release_state": "released", "drawing": {"status": "accepted"}, "drawing_acceptance": None}, "artifacts": []}
    services = SimpleNamespace(backend=Backend(), result=lambda record, revision=None: cached,
                               analysis=lambda source: {"drawing": {"sheet_size_mm": [420, 297]}}, jobs=SimpleNamespace(directory=lambda run_id: tmp_path))
    record = {"run_id": "run", "source_id": "src", "phase": "done", "job": {"status": "succeeded"}, "error": None, "part_run_id": "part"}
    assert run_view(services, record)["review"]["drawing"]["current"] is True
    stale = run_view(services, record)["review"]["drawing"]
    assert stale["current"] is False and stale["pair_current"] is False and "PDF" in stale["reason"]


def last_result_fixture():
    """Domain-selected files of an older valid build and a failed drawing verification."""
    def artifact(number, role, media, filename):
        return {"artifact_id": "art_" + str(number) * 32, "role": role, "media_type": media,
                "filename": filename, "sha256": SHA, "size_bytes": 7, "revision": 1}
    step = artifact(1, "step_candidate", "model/step", "candidate.step")
    pdf = artifact(2, "technical_drawing", "application/pdf", "drawing.pdf")
    dxf = artifact(3, "technical_drawing", "image/vnd.dxf", "drawing.dxf")
    report = artifact(4, "drawing_verification_report", "application/json", "verification.json")
    preview = artifact(5, "drawing_verification_preview", "image/png", "preview.png")
    return {"released": False, "reason": "The drawing verification blocks release (DIM-06, FEAT-02).",
            "no_step_reason": None,
            "step": {"artifact": step, "build_revision": 1, "description_sha256": SHA, "candidate_sha256": SHA,
                     "current_revision": False, "validation": {"status": "pass", "checks": [
                         {"check": "step_reimport", "status": "pass"}, {"check": "target_cad_open", "status": "not_tested"}]}},
            "drawing": {"part_revision": 1, "drawing_sha256": SHA, "artifacts": [pdf, dxf],
                        "verification": {"status": "fail", "validity": "stale", "artifacts": [report, preview], "blocking": [
                            {"rule_id": "DIM-06", "status": "fail", "feature": "hole", "message": "Dimension missing."},
                            {"rule_id": "FEAT-02", "status": "not_tested", "feature": None, "message": "Not tested."}]}}}


def test_last_results_present_selected_files_and_safe_failure_context():
    from drawing_demo.agent.mapping import last_results_view

    record = {"failed_phase": "drawing", "error": {"code": "AGENT_TIME_BUDGET", "message": "worker C:/private/customer.pdf"}}
    result, artifacts = last_results_view(last_result_fixture(), record, SHA)
    assert result["failed_phase"] == "drawing"
    assert "AGENT_TIME_BUDGET" in result["reason"] and "private" not in str(result)
    assert result["model"]["model_revision"] == 1 and result["no_model_reason"] is None
    assert [v["status"] for v in result["model"]["validation"]] == ["pass", "not_tested"]
    assert [v["rule_id"] for v in result["blocking"]] == ["DIM-06", "FEAT-02"]
    assert [a["role"] for a in artifacts] == ["step_candidate", "drawing_pdf", "drawing_dxf", "verification_report", "verification_preview"]
    assert result["artifact_ids"] == [a["artifact_id"] for a in artifacts]
    assert all(a["released"] is False and a["release_status"] == "not_released" and a["reason"] == result["reason"] for a in artifacts)


def test_a_candidate_is_never_released_even_if_named_by_a_release():
    candidate = last_result_fixture()["step"]["artifact"]
    assert artifact_view(candidate, SHA, frozenset({candidate["artifact_id"]}))["released"] is False


@pytest.mark.parametrize(("release", "expected"), [
    ({"delivery": "complete_service", "drawing": {"status": "unverified"}}, False),
    ({"delivery": "complete_service", "drawing": {"status": "accepted"}, "pair_current": False}, False),
    ({"delivery": "complete_service", "drawing": {"status": "accepted"}, "drawing_current": False}, False),
    ({"delivery": "complete_service", "drawing": {"status": "accepted"}, "pair_current": True}, True),
    ({"delivery": "step_only", "drawing": {"status": "unreviewed"}}, False),
    ({"delivery": "step_only", "drawing": {"status": "accepted"}}, False),
    ({"delivery": "step_only", "drawing": {"status": "failed"}}, False),
])
def test_only_recorded_current_release_drawings_are_released(release, expected):
    from drawing_demo.agent.mapping import released_artifact_ids

    release["artifact"] = {"artifact_id": "step"}
    release["drawing"]["artifacts"] = [{"artifact_id": "drawing"}]
    ids = released_artifact_ids(release)
    assert "step" in ids
    assert ("drawing" in ids) is expected


def test_terminal_run_without_a_part_has_explicit_no_model(environment):
    with TestClient(api.create_app()) as client:
        services = client.app.state.services
        run = services.jobs.add(upload(client)["source_id"])
        services.jobs.update(run["run_id"], phase="failed", failed_phase="analyzing", job={"status": "failed"},
                             error={"code": "RUN_INTERRUPTED", "message": "Private worker details", "field": None, "recovery": None})
        value = client.get(f"/api/runs/{run['run_id']}").json()
        assert value["artifacts"] == [] and value["last_results"]["artifact_ids"] == []
        assert value["last_results"]["model"] is None
        assert value["last_results"]["no_model_reason"] == "No validated model was built."
        assert value["last_results"]["failed_phase"] == "analyzing"


def test_same_revision_last_results_refresh_without_a_part_read(tmp_path):
    from types import SimpleNamespace

    last = last_result_fixture()
    states = iter([None, last])

    class Backend:
        def call(self, operation, **arguments):
            if operation == "source_get":
                return {"source_id": "src", "sha256": SHA}
            if operation == "artifact_list":
                return {"items": [], "next_cursor": None}
            assert operation == "drawing_read"
            return {"revision": 2, "acceptance": None, "release": None, "last_results": next(states)}

    cached = {"part": {"revision": 2}, "review": {"release_state": "released"}, "artifacts": []}
    services = SimpleNamespace(backend=Backend(), result=lambda record, revision=None: cached,
                               analysis=lambda source: {"drawing": {"sheet_size_mm": [420, 297]}},
                               jobs=SimpleNamespace(directory=lambda run_id: tmp_path))
    record = {"run_id": "run", "source_id": "src", "phase": "failed", "failed_phase": "drawing",
              "job": {"status": "failed"}, "error": {"code": "AGENT_FAILED"}, "part_run_id": "part"}
    assert api.run_view(services, record)["last_results"]["model"] is None
    value = api.run_view(services, record)
    assert value["last_results"]["model"]["model_revision"] == 1
    assert len(value["artifacts"]) == 5 and all(not a["released"] for a in value["artifacts"])
    assert "domain_last_results" not in value and cached["artifacts"] == []


def test_same_revision_release_uses_current_ids_and_never_releases_a_candidate(tmp_path):
    from types import SimpleNamespace

    candidate = {**last_result_fixture()["step"]["artifact"], "created": 1}
    step = {**candidate, "artifact_id": "art_" + "6" * 32, "role": "released_step", "created": 2}
    pdf = {**last_result_fixture()["drawing"]["artifacts"][0], "created": 3}
    current = {"artifact": step, "delivery": "step_only", "drawing_current": True,
               "drawing": {"status": "unverified", "artifacts": [pdf, candidate]}}

    class Backend:
        def call(self, operation, **arguments):
            if operation == "source_get":
                return {"source_id": "src", "sha256": SHA}
            if operation == "artifact_list":
                return {"items": [candidate, step, pdf], "next_cursor": None}
            assert operation == "drawing_read"
            return {"revision": 1, "acceptance": None, "release": current}

    cached = {"part": {"revision": 1}, "review": {"release_state": "released"},
              "artifacts": [{**candidate, "released": True}]}
    services = SimpleNamespace(backend=Backend(), result=lambda record, revision=None: cached,
                               analysis=lambda source: {"drawing": {"sheet_size_mm": [420, 297]}},
                               jobs=SimpleNamespace(directory=lambda run_id: tmp_path))
    record = {"run_id": "run", "source_id": "src", "phase": "done", "job": {"status": "succeeded"},
              "error": None, "part_run_id": "part"}
    value = api.run_view(services, record)
    assert value["last_results"] is None
    assert {a["role"]: a["released"] for a in value["artifacts"]} == {"step_candidate": False, "step": True, "drawing_pdf": False}
    current["artifact"] = candidate
    assert all(not a["released"] for a in api.run_view(services, record)["artifacts"])


def seed_failed_verification(services, monkeypatch, *, fail_job=True):
    """Create domain artifacts with fake CAD and verification; this is not CAD acceptance evidence."""
    with monkeypatch.context() as imports:
        imports.syspath_prepend(str(Path(__file__).resolve().parents[3] / "drawing2cad-mcp" / "tests"))
        from test_drafting import drawing_fixture
        from test_drawing_verification_service import VerifyingRunner
    from drawing2cad_mcp import drawing_verification
    from drawing2cad_mcp.drawing_contract import description_digest

    source = services.backend.upload("Synthetic_dwg.pdf", pdf_bytes())
    record = services.jobs.add(source["source_id"])
    part_run = record["part_prefix"] + "-plate"
    description, spec = drawing_fixture()
    description["evidence"][0]["source"].update(source_id=source["source_id"], source_sha256=source["sha256"])
    spec["description_sha256"] = description_digest(description)
    backend = services.backend
    domain = backend.application.domain
    cad = domain._backend(backend.context)[0]
    cad.runner = VerifyingRunner(cad.runner.storage)
    cad.runner.findings = [{"rule_id": rule, "status": "fail" if rule in {"DIM-06", "FEAT-02"} else "pass",
                           "severity": "major", "feature": None, "message": "Synthetic verification finding."}
                          for rule in drawing_verification.MANDATORY_RULES]
    backend.call("part_create", run_id=part_run, description=description,
                 sources=[{"source_id": source["source_id"], "sha256": source["sha256"], "role": "construction"}])
    assert backend.call("build_from_description", run_id=part_run, expected_revision=1)["status"] == "pass"
    rendered = backend.call("drawing_render", run_id=part_run, expected_revision=1, drawing_spec=spec)
    assert rendered["status"] == "pass"
    pdf = next(a for a in rendered["drawing"]["artifacts"] if a["media_type"] == "application/pdf")
    verified = backend.call("drawing_verify", run_id=part_run, expected_revision=1,
                            artifact_id=pdf["artifact_id"], expected_sha256=pdf["sha256"])
    assert verified["status"] == "fail"
    services.jobs.update(record["run_id"], part_run_id=part_run, phase="drawing", job={"status": "running"})
    if fail_job:
        services.runner._fail(record["run_id"], "AGENT_TIME_BUDGET", "Synthetic agent deadline.", "Start again.")
    else:
        services.runner.finish(record["run_id"], {"status": "completed"})
    return record["run_id"]


def test_failed_verification_domain_files_reach_web_downloads(environment):
    with TestClient(api.create_app()) as client:
        run_id = seed_failed_verification(client.app.state.services, environment)
        value = client.get(f"/api/runs/{run_id}").json()
        last = value["last_results"]
        assert value["phase"] == "failed" and last["failed_phase"] == "drawing"
        assert last["model"]["model_revision"] == 1
        assert {b["rule_id"] for b in last["blocking"]} == {"DIM-06", "FEAT-02"}
        selected = [a for a in value["artifacts"] if a["artifact_id"] in last["artifact_ids"]]
        assert {a["role"] for a in selected} == {"step_candidate", "drawing_pdf", "drawing_dxf", "verification_report", "verification_preview"}
        for artifact in selected:
            assert artifact["released"] is False and artifact["release_status"] == "not_released"
            response = client.get(f"/api/artifacts/{artifact['artifact_id']}/content")
            assert response.status_code == 200 and response.content


def test_completed_built_run_uses_domain_failed_verification_phase(environment):
    with TestClient(api.create_app()) as client:
        run_id = seed_failed_verification(client.app.state.services, environment, fail_job=False)
        value = client.get(f"/api/runs/{run_id}").json()
        assert value["job"]["status"] == "succeeded" and value["phase"] == "done"
        assert value["failed_phase"] is None and value["error"] is None
        last = value["last_results"]
        assert last["failed_phase"] == "drawing" and last["released"] is False
        assert {b["rule_id"] for b in last["blocking"]} == {"DIM-06", "FEAT-02"}
        assert "DIM-06" in last["reason"] and "FEAT-02" in last["reason"]
        assert last["model"]["model_revision"] == 1
