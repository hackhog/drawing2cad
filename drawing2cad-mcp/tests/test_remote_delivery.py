"""Verify synthetic drawing and STEP delivery through a real remote MCP client.

These tests check the service contract. They do not establish source drawing
interpretation, independent STEP conformance, AP242, or target CAD acceptance.
"""

import asyncio
import base64
from contextlib import asynccontextmanager
from copy import deepcopy
import hashlib
from io import StringIO
import json
import os

import httpx2
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
import pytest

from drawing2cad_mcp.config import CadSettings, DomainSettings, PdfSettings, Settings
from drawing2cad_mcp.drawing_contract import description_digest
from drawing2cad_mcp.server import Application
from drawing2cad_mcp.worker_runner import WorkerRunner
from test_drafting import drawing_fixture
from test_http import running_server


@asynccontextmanager
async def delivery_session(url):
    async with httpx2.AsyncClient(timeout=180, trust_env=False) as client:
        async with streamable_http_client(url, http_client=client) as streams:
            async with ClientSession(*streams, read_timeout_seconds=180) as session:
                await session.initialize()
                yield session


def assert_public(value):
    if isinstance(value, dict):
        for key, item in value.items():
            assert key not in {"path", "candidate_path", "work_dir", "logs", "stdout", "stderr"}
            assert not key.endswith("_path")
            assert_public(item)
    elif isinstance(value, list):
        for item in value:
            assert_public(item)
    elif isinstance(value, str):
        assert "/tmp/pytest/" not in value
        assert "execution/cad/" not in value


async def call(session, name, **arguments):
    response = await session.call_tool(name, arguments)
    # Show the complete public result. The default assertion text truncates the build report.
    assert not response.is_error, json.dumps(response.structured_content or response.model_dump(), indent=1, default=str)
    result = response.structured_content
    assert_public(result)
    return result


async def expect_error(session, name, code, **arguments):
    response = await session.call_tool(name, arguments)
    assert response.is_error, response
    assert_public(response.structured_content)
    assert response.structured_content["error"]["code"] == code, response


def source_pdf_bytes():
    """Create an in-memory source fixture with the declared plate dimensions."""
    import pymupdf
    with pymupdf.open() as document:
        page = document.new_page(width=595, height=842)
        page.insert_text((40, 40), "Synthetic plate: 60 x 30 x 10 mm. Hole diameter 8 mm.")
        page.insert_text((40, 60), "Hole center: X 30 mm, Y 15 mm. Through thickness.")
        page.draw_rect(pymupdf.Rect(50, 100, 350, 250))
        page.draw_circle((200, 175), 20)
        page.insert_text((50, 280), "TOP: length 60, width 30. FRONT: length 60, height 10.")
        page.draw_rect(pymupdf.Rect(50, 320, 350, 370))
        page.insert_text((50, 410), "Synthetic contract fixture. Dimensions are in mm.")
        return document.tobytes()


async def upload(session, data):
    digest = hashlib.sha256(data).hexdigest()
    started = await call(session, "upload_begin", filename="plate.pdf", size_bytes=len(data), sha256=digest)
    for offset in range(0, len(data), 512):
        await call(session, "upload_chunk", upload_id=started["upload_id"], offset=offset,
                   data_base64=base64.b64encode(data[offset:offset + 512]).decode("ascii"))
    result = await call(session, "upload_complete", upload_id=started["upload_id"])
    assert result["sha256"] == digest
    return result


async def download(session, artifact):
    metadata = await call(session, "artifact_get", artifact_id=artifact["artifact_id"])
    assert metadata["sha256"] == artifact["sha256"]
    content = bytearray()
    while True:
        result = await call(session, "artifact_read", artifact_id=artifact["artifact_id"], offset=len(content), length=4096)
        data = base64.b64decode(result["data_base64"], validate=True)
        assert result["offset"] == len(content)
        assert result["length"] == len(data)
        assert result["sha256"] == artifact["sha256"]
        content.extend(data)
        if result["eof"]:
            break
        assert data
    assert len(content) == metadata["size_bytes"]
    assert hashlib.sha256(content).hexdigest() == artifact["sha256"]
    return bytes(content)


async def wait_job(session, job_id):
    async with asyncio.timeout(150):
        while True:
            job = await call(session, "job_get", job_id=job_id)
            if job["state"] in {"succeeded", "failed", "cancelled", "interrupted"}:
                assert job["state"] == "succeeded", job
                return job
            await asyncio.sleep(0.1)


def coverage(source):
    return {"reviewer": "Synthetic integration test", "source_hashes": [source["sha256"]],
            "views": {"total": 2, "reviewed": 2}, "features": {"total": 2, "reviewed": 2},
            "printed_dimensions": {"total": 6, "reviewed": 6}, "critical_measurement_ids": ["overall"],
            "reason": "Synthetic service contract test. No customer source or target CAD acceptance."}


def assert_fresh_validation(result, expected_length):
    assert result["status"] == "pass", result
    assert result["released"] is False
    build = result["build"]
    assert build["build"]["worker"]["worker_id"] != build["validation"]["worker"]["worker_id"]
    assert build["validation"]["status"] == "pass"
    assert build["agreement"]["status"] == "pass"
    assert build["validation"]["measured"]["bbox_size"] == pytest.approx([expected_length, 30, 10])
    checks = {row["check"]: row["status"] for row in build["validation"]["checks"]}
    assert checks["step_reimport"] == checks["drawing_measurements"] == checks["overall"] == "pass"
    assert checks["semantic_pmi"] == checks["target_cad_open"] == "not_tested"


async def check_drawing_downloads(session, drawing, expected_length):
    import ezdxf
    import pymupdf
    artifacts = {item["filename"]: item for item in drawing["artifacts"]}
    dxf = await download(session, artifacts["drawing.dxf"])
    document = ezdxf.read(StringIO(dxf.decode("utf8")))
    dimensions = list(document.modelspace().query("DIMENSION"))
    assert sorted(d.get_measurement() for d in dimensions) == pytest.approx([8, 10, expected_length])
    assert all(d.has_xdata("DRAWING2CAD") for d in dimensions)
    pdf = await download(session, artifacts["drawing.pdf"])
    with pymupdf.open(stream=pdf, filetype="pdf") as document:
        assert len(document) == 1
        assert len(document[0].get_drawings()) > 10
    response = await session.call_tool("artifact_preview", {"artifact_id": artifacts["drawing.pdf"]["artifact_id"]})
    assert not response.is_error, response
    preview = response.structured_content
    assert_public(preview)
    assert preview["source_artifact"]["sha256"] == artifacts["drawing.pdf"]["sha256"]
    assert preview["artifact"]["media_type"] == "image/png"
    assert preview["preview"]["width_pixels"] > 0
    images = [block for block in response.content if block.type == "image"]
    assert len(images) == 1
    assert base64.b64decode(images[0].data, validate=True).startswith(b"\x89PNG\r\n\x1a\n")
    return artifacts


@pytest.fixture
def delivery_app(tmp_path):
    capability = WorkerRunner.capabilities()
    if os.environ.get("DRAWING2CAD_REQUIRE_SANDBOX") == "1":
        assert capability["available"], capability
    if not capability["available"]:
        pytest.skip("The complete delivery test requires the verified Linux sandbox.")
    return Application(Settings(
        pdf=PdfSettings(allowed_roots=[tmp_path / "private"], output_root=tmp_path / "private",
                        pdftoppm=os.environ.get("DRAWING2CAD_PDFTOPPM")),
        cad=CadSettings(enabled=True, timeout_seconds=90),
        domain=DomainSettings(enabled=True, root=tmp_path / "store"),
    ))


async def test_remote_drawing_step_delivery_and_parameter_revision(delivery_app):
    async with running_server(delivery_app) as url:
        async with delivery_session(url) as session:
            tools = {tool.name: tool for tool in (await session.list_tools()).tools}
            assert {"artifact_preview", "drawing_render", "drawing_review", "job_submit"} <= tools.keys()
            for tool in tools.values():
                assert "path" not in tool.input_schema.get("properties", {})
            source = await upload(session, source_pdf_bytes())
            text = await call(session, "pdf_read_text", source_id=source["source_id"])
            assert "60 x 30 x 10" in text["pages"][0]["text"]
            description, spec = drawing_fixture()
            description["evidence"][0]["source"].update(source_id=source["source_id"], source_sha256=source["sha256"])
            spec["description_sha256"] = description_digest(description)
            await call(session, "part_create", run_id="remote_delivery", description=description,
                       sources=[{"source_id": source["source_id"], "sha256": source["sha256"], "role": "construction"}])
            rendered = await call(session, "drawing_render", run_id="remote_delivery", expected_revision=1, drawing_spec=spec)
            assert rendered["status"] == "pass", rendered
            drawing = rendered["drawing"]
            await check_drawing_downloads(session, drawing, 60)
            arguments = {"run_id": "remote_delivery", "expected_revision": 1}
            job = await call(session, "job_submit", operation="build_from_description", arguments=arguments,
                             idempotency_key="build-revision-1")
        # A client disconnect must not cancel a durable build job.
        async with delivery_session(url) as session:
            finished = await wait_job(session, job["job_id"])
            assert_fresh_validation(finished["result"], 60)
            repeated = await call(session, "job_submit", operation="build_from_description", arguments=arguments,
                                  idempotency_key="build-revision-1")
            assert repeated["job_id"] == job["job_id"]
            assert repeated["state"] == "succeeded"
            review = {"run_id": "remote_delivery", "expected_revision": 1,
                      "drawing_sha256": drawing["drawing_sha256"], "reviewer": "Synthetic integration test",
                      "reason": "Compare the synthetic views, native dimensions, and validated candidate.",
                      "source_hashes": [source["sha256"]], "decision": "accepted"}
            accepted = await call(session, "drawing_review", **review)
            assert accepted["drawing"]["review"]["candidate_sha256"] == finished["result"]["build"]["candidate_sha256"]
            released = await call(session, "export_step", **arguments, coverage=coverage(source))
            assert released["status"] == "pass", released
            step = await download(session, released["release"]["artifact"])
            assert step.startswith(b"ISO-10303-21;")
            assert hashlib.sha256(step).hexdigest() == finished["result"]["build"]["candidate_sha256"]
            reports = await call(session, "part_export_review", **arguments)
            artifacts = {item["filename"]: item for item in reports["artifacts"]}
            assert json.loads(await download(session, artifacts["part.json"])) == description
            manifest = json.loads(await download(session, artifacts["manifest.json"]))
            assert_public(manifest)
            assert manifest["run"]["release"]["artifact"]["artifact_id"] == released["release"]["artifact"]["artifact_id"]

            updated = deepcopy(description)
            updated["parameters"][0]["value"] = 70
            updated["measurements"][0]["expected"] = [70, 30, 10]
            changed = await call(session, "part_update", **arguments, description=updated)
            assert changed["revision"] == 2
            state = await call(session, "part_read", run_id="remote_delivery")
            assert state["part"]["release"] is None
            assert state["drawing"] is None
            await expect_error(session, "drawing_review", "DRAWING_REVIEW_CONFLICT", **{**review, "expected_revision": 2})
            await expect_error(session, "export_step", "VALIDATED_BUILD_REQUIRED", run_id="remote_delivery",
                               expected_revision=2, coverage=coverage(source))
            stale_response = await session.call_tool("drawing_validate", {
                "run_id": "remote_delivery", "expected_revision": 2, "drawing_spec": spec})
            assert stale_response.is_error
            stale = stale_response.structured_content
            assert_public(stale)
            assert stale["status"] == "fail"
            assert "stale_binding" in {row["code"] for row in stale["defects"]}

            # Build first on the second revision to test both supported orders.
            rebuilt = await call(session, "build_from_description", run_id="remote_delivery", expected_revision=2)
            assert_fresh_validation(rebuilt, 70)
            spec.update(part_revision=2, description_sha256=description_digest(updated))
            rerendered = await call(session, "drawing_render", run_id="remote_delivery", expected_revision=2, drawing_spec=spec)
            assert rerendered["status"] == "pass", rerendered
            await check_drawing_downloads(session, rerendered["drawing"], 70)
            await call(session, "drawing_review", **{**review, "expected_revision": 2,
                       "drawing_sha256": rerendered["drawing"]["drawing_sha256"]})
            second = await call(session, "export_step", run_id="remote_delivery", expected_revision=2, coverage=coverage(source))
            assert second["release"]["description_revision"] == 2
            assert second["release"]["artifact"]["artifact_id"] != released["release"]["artifact"]["artifact_id"]
            assert hashlib.sha256(await download(session, second["release"]["artifact"])).hexdigest() == rebuilt["build"]["candidate_sha256"]
