"""Remote MCP clients exchange bytes and IDs without server paths."""

import base64
import hashlib
import json

import pytest
from mcp.types import CallToolRequestParams

from drawing2cad_mcp.config import DomainSettings, HTTPSettings, PdfSettings, Settings
from drawing2cad_mcp.server import Application
from test_http import TEST_TOKEN, TOKEN_ENV, mcp_session, running_server
from test_pdf import make_pdf
from test_part_schema import sample_description


def remote_app(tmp_path):
    return Application(Settings(
        pdf=PdfSettings(allowed_roots=[tmp_path / "private"], output_root=tmp_path / "private"),
        domain=DomainSettings(enabled=True, root=tmp_path / "store"),
        http=HTTPSettings(token_env=TOKEN_ENV),
    ))


async def call(session, name, **arguments):
    result = await session.call_tool(name, arguments)
    assert not result.is_error, result
    return result.structured_content


async def upload(session, data):
    digest = hashlib.sha256(data).hexdigest()
    started = await call(session, "upload_begin", filename="synthetic.pdf", size_bytes=len(data), sha256=digest)
    upload_id = started["upload_id"]
    for offset in range(0, len(data), 512):
        await call(session, "upload_chunk", upload_id=upload_id, offset=offset,
                   data_base64=base64.b64encode(data[offset:offset + 512]).decode())
    return await call(session, "upload_complete", upload_id=upload_id)


async def test_remote_upload_pdf_and_notes_survive_server_restart(tmp_path, monkeypatch):
    monkeypatch.setenv(TOKEN_ENV, TEST_TOKEN)
    source = make_pdf(tmp_path / "client-only.pdf").read_bytes()
    app = remote_app(tmp_path)
    async with running_server(app) as url:
        async with mcp_session(url) as session:
            tools = {tool.name: tool for tool in (await session.list_tools()).tools}
            assert {"upload_chunk", "artifact_read", "drawing_render", "job_submit"} <= tools.keys()
            assert "path" not in tools["pdf_info"].input_schema["properties"]
            status = await call(session, "drawing2cad_status")
            assert status["profile"] == "remote"
            assert "allowed_roots" not in status["pdf"]
            uploaded = await upload(session, source)
            source_id = uploaded["source_id"]
            info = await call(session, "pdf_info", source_id=source_id)
            assert info["page_count"] == 2
            assert info["source"]["sha256"] == hashlib.sha256(source).hexdigest()
            assert "path" not in info["source"]
            bad = await session.call_tool("pdf_info", {"path": str(tmp_path / "client-only.pdf")})
            assert bad.is_error
            description = sample_description()
            for evidence in description["evidence"]:
                evidence["source"].update(source_id=source_id, source_sha256=uploaded["sha256"])
            await call(session, "part_create", run_id="remote_fixture", description=description,
                       sources=[{"source_id": source_id, "sha256": uploaded["sha256"], "role": "construction"}])
            note = await call(session, "notes_update", run_id="remote_fixture", expected_revision=0, text="Review pending.")
            assert note["revision"] == 1
            state = await call(session, "part_read", run_id="remote_fixture")
            assert str(tmp_path) not in json.dumps(state)
    restarted = remote_app(tmp_path)
    async with running_server(restarted) as url:
        async with mcp_session(url) as session:
            assert (await call(session, "source_get", source_id=source_id))["sha256"] == uploaded["sha256"]
            assert (await call(session, "notes_read", run_id="remote_fixture"))["text"] == "Review pending."
            conflict = await session.call_tool("notes_update", {
                "run_id": "remote_fixture", "expected_revision": 0, "text": "Stale update."})
            assert conflict.is_error
            assert conflict.structured_content["error"]["code"] == "REVISION_CONFLICT"


async def test_remote_errors_do_not_disclose_internal_exceptions(tmp_path, monkeypatch):
    app = remote_app(tmp_path)
    def fail(*args):
        raise RuntimeError("secret internal path /private/credential")
    monkeypatch.setattr(app.domain, "call", fail)
    result = await app.on_call_tool(None, CallToolRequestParams(name="source_list", arguments={}))
    assert result.is_error
    assert "private" not in json.dumps(result.structured_content)
    assert result.structured_content["error"]["code"] == "TOOL_FAILED"


def test_domain_paths_resolve_against_config_file(tmp_path):
    config = tmp_path / "service.toml"
    config.write_text('[pdf]\nallowed_roots=["private"]\noutput_root="out"\n'
                      '[domain]\nenabled=true\nroot="storage"\n', encoding="utf8")
    assert Settings.load(config).domain.root == tmp_path / "storage"


@pytest.mark.parametrize("field,value", [("max_source_bytes", 20971521), ("max_chunk_bytes", 524289)])
def test_remote_transfer_limits_match_transport_budget(field, value):
    with pytest.raises(ValueError):
        DomainSettings(**{field: value})
