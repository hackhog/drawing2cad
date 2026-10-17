"""Exercise managed tool dispatch and the optional development boundary."""

from hashlib import sha256
from unittest.mock import AsyncMock, Mock

import pytest
from mcp.types import CallToolRequestParams

from drawing2cad_mcp.config import PdfSettings, ServerSettings, Settings
from drawing2cad_mcp.server import Application
from test_pdf import make_pdf


async def call(app, name, **arguments):
    return await app.on_call_tool(None, CallToolRequestParams(name=name, arguments=arguments))


@pytest.fixture
def app(tmp_path):
    return Application(Settings(pdf=PdfSettings(allowed_roots=[tmp_path], output_root=tmp_path / "out")))


async def test_hidden_proxy_never_starts_discovers_or_dispatches(app):
    proxy = Mock(start=AsyncMock(), close=AsyncMock(), list_tools=AsyncMock(),
                 call_tool=AsyncMock(), cached_tools=[], status=Mock(return_value={"connected": False}))
    app.proxy = proxy
    async with app.lifespan(app.server):
        names = {tool.name for tool in (await app.on_list_tools(None)).tools}
        assert "part_create" in names and "step_inspect" in names
        assert "workflow_create_run" not in names
        assert not any(name.startswith("freecad_") for name in names)
        await app.status(refresh=True)
        result = await call(app, "freecad_execute_code", code="raise AssertionError()")
        assert result.is_error
        assert result.structured_content["error"]["code"] == "RAW_PROXY_DISABLED"
        assert app.get_schema("freecad_execute_code") is None
    proxy.start.assert_not_awaited()
    proxy.list_tools.assert_not_awaited()
    proxy.call_tool.assert_not_awaited()


async def test_capabilities_distinguish_state_checks_from_cad(app, tmp_path):
    result = await call(app, "cad_capabilities")
    capabilities = result.structured_content
    assert not result.is_error
    assert capabilities["workflow"]["enforcement_scope"] == "managed_evidence_transitions_only"
    assert not capabilities["workflow"]["cad_execution_validation"]
    assert all(not data["available"] for data in capabilities["domain_services"].values())
    assert not (tmp_path / "out" / "workflow").exists()


async def test_step_failure_preserves_structured_next_action(app, tmp_path):
    step = tmp_path / "changed.step"
    step.write_text("not STEP", encoding="utf8")
    result = await call(app, "step_inspect", path=str(step), expected_sha256="0" * 64)
    assert result.is_error
    error = result.structured_content["error"]
    assert error["code"] == "SOURCE_HASH_MISMATCH"
    assert error["target"] == "expected_sha256" and error["next_action"]


async def test_workflow_roundtrip_errors_and_no_forged_success(app, tmp_path):
    app.settings.server.expose_legacy_workflow = True
    source = make_pdf(tmp_path / "drawing.pdf")
    source_hash = sha256(source.read_bytes()).hexdigest()
    result = await call(app, "workflow_create_run", run_id="server-test", mode="new_drawing", units="mm",
                        sources=[{"path": str(source), "sha256": source_hash, "role": "construction_source"}])
    assert not result.is_error
    assert result.structured_content["run"]["state_revision"] == 0
    rejected = await call(app, "workflow_check_readiness", run_id="server-test", phase="build", passed=True)
    assert rejected.structured_content["error"]["code"] == "INVALID_ARGUMENTS"
    readiness = await call(app, "workflow_check_readiness", run_id="server-test", phase="build")
    assert not readiness.structured_content["ready"]
    assert "CAD_VALIDATION_UNAVAILABLE" in {item["code"] for item in readiness.structured_content["defects"]}
    reread = await call(app, "workflow_read_run", run_id="server-test")
    assert reread.structured_content["run"]["state_revision"] == 0


async def test_legacy_workflow_requires_explicit_configuration(app):
    result = await call(app, "workflow_create_run")
    assert result.structured_content["error"]["code"] == "LEGACY_WORKFLOW_DISABLED"
    assert app.get_schema("workflow_create_run") is None
    assert not (await call(app, "part_schema")).is_error
