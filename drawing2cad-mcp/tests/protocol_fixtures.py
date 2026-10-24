"""Authenticated HTTP protocol fixtures for MCP client tests."""

import asyncio
from contextlib import asynccontextmanager, contextmanager
import socket
from types import SimpleNamespace

from mcp.server import Server
from mcp.types import CallToolResult, ListToolsResult, Tool
import uvicorn

from drawing2cad_mcp.http import BearerTokenMiddleware


TOKEN_ENV = "DRAWING2CAD_TEST_CLIENT_TOKEN"
TOKEN = "test-client-bearer-token-for-loopback"


class TestServer(uvicorn.Server):
    __test__ = False

    @contextmanager
    def capture_signals(self):
        yield


@asynccontextmanager
async def protocol_server(tool_name="echo", response_value=None):
    """Serve real MCP messages on a reserved loopback port without PDF or CAD work."""
    calls = []
    tool = Tool.model_validate({
        "name": tool_name, "title": "Echo title", "description": "Full tool metadata",
        "inputSchema": {"type": "object", "properties": {"value": {"type": "string"}}},
        "outputSchema": {"type": "object", "properties": {"value": {"type": "string"}}, "required": ["value"]},
        "annotations": {"readOnlyHint": True, "openWorldHint": False},
        "icons": [{"src": "data:image/png;base64,aA==", "mimeType": "image/png"}],
        "_meta": {"custom": {"preserve": 7}},
    })

    async def list_tools(context, params):
        return ListToolsResult(tools=[tool])

    async def call_tool(context, params):
        calls.append({"name": params.name, "arguments": params.arguments})
        value = response_value if response_value is not None else (params.arguments or {}).get("value", "same")
        return CallToolResult.model_validate({
            "content": [{"type": "text", "text": value},
                        {"type": "image", "data": "aGVsbG8=", "mimeType": "image/png"},
                        {"type": "resource", "resource": {"uri": "fixture://result", "text": "preserved"}}],
            "structuredContent": {"value": value}, "isError": False, "_meta": {"marker": 42},
        })

    app = Server("protocol-fixture", version="1.0", on_list_tools=list_tools, on_call_tool=call_tool).streamable_http_app(
        stateless_http=True)
    app.add_middleware(BearerTokenMiddleware, token=TOKEN)
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        listener.setblocking(False)
        port = listener.getsockname()[1]
        server = TestServer(uvicorn.Config(app, host="127.0.0.1", port=port, lifespan="on", log_config=None,
                                          access_log=False, timeout_graceful_shutdown=5))
        task = asyncio.create_task(server.serve(sockets=[listener]))
        try:
            async with asyncio.timeout(10):
                while not server.started:
                    if task.done():
                        await task
                        raise RuntimeError("HTTP fixture exited before startup.")
                    await asyncio.sleep(0.01)
            yield SimpleNamespace(server={"url": f"http://127.0.0.1:{port}/mcp", "token_env": TOKEN_ENV}, calls=calls)
        finally:
            server.should_exit = True
            try:
                await asyncio.wait_for(asyncio.shield(task), 10)
            finally:
                if not task.done():
                    task.cancel()
                    await asyncio.gather(task, return_exceptions=True)
