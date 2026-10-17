"""Real Streamable HTTP requests with synthetic inputs and a protocol fixture."""

import asyncio
import base64
from contextlib import asynccontextmanager, contextmanager
from hashlib import sha256
from io import BytesIO
import os
import shutil
import socket
import sys
from unittest.mock import AsyncMock

import httpx2
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from PIL import Image
import pytest
import uvicorn

from drawing2cad_mcp.config import HTTPSettings, PdfSettings, ServerSettings, Settings
from drawing2cad_mcp.http import create_http_app
from drawing2cad_mcp import pdf as pdf_module
from drawing2cad_mcp.proxy import FreeCADProxy
from drawing2cad_mcp.server import Application
from test_pdf import make_pdf
from test_proxy import UPSTREAM


TOKEN_ENV = "DRAWING2CAD_TEST_HTTP_TOKEN"
TEST_TOKEN = "test-token-for-loopback-only"


class TrackedApplication(Application):
    def __init__(self, *args, **kwargs):
        self.lifespan_starts = 0
        self.lifespan_closes = 0
        self.tool_calls = 0
        super().__init__(*args, **kwargs)

    @asynccontextmanager
    async def lifespan(self, server):
        self.lifespan_starts += 1
        try:
            async with super().lifespan(server) as state:
                yield state
        finally:
            self.lifespan_closes += 1

    async def on_call_tool(self, context, params):
        self.tool_calls += 1
        return await super().on_call_tool(context, params)


class TestServer(uvicorn.Server):
    __test__ = False

    @contextmanager
    def capture_signals(self):
        # Do not replace the test runner's signal handlers.
        yield


@pytest.fixture
def http_application(tmp_path, monkeypatch):
    monkeypatch.delenv(TOKEN_ENV, raising=False)
    return TrackedApplication(Settings(
        pdf=PdfSettings(allowed_roots=[tmp_path], output_root=tmp_path / "out",
                        pdftoppm=os.environ.get("DRAWING2CAD_PDFTOPPM")),
        server=ServerSettings(transport="streamable-http", preview_max_pixels=1000),
        http=HTTPSettings(token_env=TOKEN_ENV),
    ))


@asynccontextmanager
async def running_server(application):
    """Keep an ephemeral socket reserved from allocation through server startup."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        listener.setblocking(False)
        port = listener.getsockname()[1]
        server = TestServer(uvicorn.Config(
            create_http_app(application), host="127.0.0.1", port=port,
            lifespan="on", log_config=None, access_log=False,
            timeout_graceful_shutdown=5,
        ))
        task = asyncio.create_task(server.serve(sockets=[listener]))
        try:
            async with asyncio.timeout(10):
                while not server.started:
                    if task.done():
                        await task
                        pytest.fail("HTTP server exited before startup")
                    await asyncio.sleep(0.01)
            yield f"http://127.0.0.1:{port}/mcp"
        finally:
            server.should_exit = True
            try:
                await asyncio.wait_for(asyncio.shield(task), 10)
            finally:
                if not task.done():
                    task.cancel()
                    await asyncio.gather(task, return_exceptions=True)


@asynccontextmanager
async def mcp_session(url, *, token=None):
    headers = {"Authorization": f"Bearer {token}"} if token is not None else {}
    async with httpx2.AsyncClient(headers=headers, timeout=10, trust_env=False) as client:
        async with streamable_http_client(url, http_client=client) as streams:
            async with ClientSession(*streams, read_timeout_seconds=10) as session:
                initialized = await session.initialize()
                assert initialized.server_info.name == "drawing2cad-mcp"
                yield session


async def test_http_status_and_pdf_text_use_real_mcp(http_application, tmp_path):
    source = make_pdf(tmp_path / "synthetic.pdf")
    async with running_server(http_application) as url:
        async with mcp_session(url) as session:
            tools = (await session.list_tools()).tools
            assert len(tools) == 6
            assert "drawing_extract" in {tool.name for tool in tools}
            status = await session.call_tool("drawing2cad_status", {})
            assert status.structured_content["freecad"]["configured"] is False
            assert not status.is_error
            info = await session.call_tool("pdf_info", {"path": str(source)})
            text = await session.call_tool("pdf_read_text", {"path": str(source)})
            assert not info.is_error and not text.is_error
            assert info.structured_content["page_count"] == 2
            assert info.structured_content["source"]["sha256"] == sha256(source.read_bytes()).hexdigest()
            assert text.structured_content["source"] == info.structured_content["source"]
            assert "Dimension 42 mm" in text.structured_content["pages"][0]["text"]
            assert text.structured_content["pages"][1]["status"] == "native_text_missing"
    assert http_application.lifespan_starts == http_application.lifespan_closes == 1


async def test_http_drawing_extract_reports_missing_optional_package(http_application, tmp_path, monkeypatch):
    monkeypatch.setattr(pdf_module, "drawing_extractor", None)
    source = make_pdf(tmp_path / "synthetic.pdf")
    async with running_server(http_application) as url:
        async with mcp_session(url) as session:
            result = await session.call_tool("drawing_extract", {"path": str(source)})
            assert result.is_error
            assert result.structured_content["error"]["code"] == "EXTRACTOR_UNAVAILABLE"
            assert "not installed" in result.structured_content["error"]["message"]
            info = await session.call_tool("pdf_info", {"path": str(source)})
            assert not info.is_error
            assert info.structured_content["source"]["sha256"] == sha256(source.read_bytes()).hexdigest()


async def test_http_pdf_render_returns_image_and_artifact(http_application, tmp_path):
    if not shutil.which(http_application.settings.pdf.pdftoppm or "pdftoppm"):
        pytest.skip("Poppler is required for the HTTP rendering integration test")
    source = make_pdf(tmp_path / "synthetic.pdf")
    async with running_server(http_application) as url:
        async with mcp_session(url) as session:
            result = await session.call_tool("pdf_render_page", {
                "path": str(source), "page": 1, "dpi": 72,
            })
            assert not result.is_error, result
            metadata = result.structured_content
            assert metadata["source"]["sha256"] == sha256(source.read_bytes()).hexdigest()
            with Image.open(metadata["artifact"]["path"]) as artifact:
                assert artifact.size == (144, 216)
            assert result.content[1].type == "image"
            with Image.open(BytesIO(base64.b64decode(result.content[1].data))) as preview:
                assert preview.width * preview.height <= 1000
                assert metadata["preview"]["resized"]


async def test_http_clients_share_proxy_until_server_shutdown(http_application):
    proxy = FreeCADProxy(sys.executable, ["-u", "-c", UPSTREAM])
    proxy.close = AsyncMock(wraps=proxy.close)
    http_application.proxy = proxy
    async with running_server(http_application) as url:
        async with mcp_session(url) as remaining:
            async with mcp_session(url) as first:
                first_tools, remaining_tools = await asyncio.gather(
                    first.list_tools(), remaining.list_tools(),
                )
                assert len(first_tools.tools) == len(remaining_tools.tools) == 11
                tool = next(item for item in first_tools.tools if item.name == "freecad_echo")
                assert tool.output_schema["required"] == ["value"]
                assert tool.meta["custom"]["preserve"] == 7
                result = await first.call_tool("freecad_echo", {"value": "HTTP round trip"})
                assert result.structured_content == {"value": "HTTP round trip"}
                assert not result.is_error
                assert result.content[1].type == "image"
                assert result.content[1].data == "aGVsbG8="
                assert result.content[2].resource.text == "preserved"
                assert result.meta == {"marker": 42}
                failed = await first.call_tool("freecad_error", {})
                assert failed.is_error and failed.meta == {"marker": 42}
            assert proxy.close.await_count == 0
            assert http_application.lifespan_starts == 1
            assert http_application.lifespan_closes == 0
            later = await remaining.call_tool("freecad_echo", {"value": "still connected"})
            assert later.structured_content == {"value": "still connected"}
        assert proxy.close.await_count == 0
    assert http_application.lifespan_closes == 1
    proxy.close.assert_awaited_once()
    assert proxy.status()["closed"]


async def test_http_bearer_rejects_before_tool_dispatch(http_application, monkeypatch):
    monkeypatch.setenv(TOKEN_ENV, TEST_TOKEN)
    body = {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
            "params": {"name": "drawing2cad_status", "arguments": {}}}
    async with running_server(http_application) as url:
        async with httpx2.AsyncClient(timeout=10, trust_env=False) as client:
            for headers in ({}, {"Authorization": "Bearer wrong-token"},
                            {"Authorization": f"Basic {TEST_TOKEN}"},
                            {"Authorization": "Bearer"},
                            [("Authorization", f"Bearer {TEST_TOKEN}"),
                             ("Authorization", f"Bearer {TEST_TOKEN}")]):
                response = await client.post(url, headers=headers, json=body)
                assert response.status_code == 401
                assert "Bearer" in response.headers["www-authenticate"]
                assert http_application.tool_calls == 0
            assert (await client.get(url)).status_code == 401
        async with mcp_session(url, token=TEST_TOKEN) as session:
            assert not (await session.call_tool("drawing2cad_status", {})).is_error
            assert http_application.tool_calls == 1


async def test_http_rejects_unlisted_host_and_origin(http_application):
    body = {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
            "params": {"name": "drawing2cad_status", "arguments": {}}}
    async with running_server(http_application) as url:
        async with httpx2.AsyncClient(timeout=10, trust_env=False) as client:
            host = await client.post(url, headers={"Host": "untrusted.example"}, json=body)
            origin = await client.post(url, headers={"Origin": "https://untrusted.example"}, json=body)
            assert host.status_code == 421
            assert origin.status_code == 403
            assert http_application.tool_calls == 0
        async with mcp_session(url) as session:
            assert not (await session.call_tool("drawing2cad_status", {})).is_error


def test_non_loopback_http_requires_token(http_application, monkeypatch):
    http_application.settings.http.host = "0.0.0.0"
    with pytest.raises(ValueError, match="(?i)token"):
        create_http_app(http_application)
    monkeypatch.setenv(TOKEN_ENV, TEST_TOKEN)
    assert create_http_app(http_application) is not None


@pytest.mark.parametrize("token", ["", " ", "token\nvalue"])
def test_invalid_configured_token_fails_closed(http_application, monkeypatch, token):
    monkeypatch.setenv(TOKEN_ENV, token)
    with pytest.raises(ValueError):
        create_http_app(http_application)
