"""Wire-level tests using a harmless real stdio MCP subprocess."""

import asyncio
import json
from pathlib import Path
import sys
import tempfile
import time
import unittest

from drawing2cad_mcp.proxy import FreeCADProxy, ProxyTimeout, ProxyUnavailable


# A protocol fixture, not a FreeCAD/CAD script. Running over real subprocess
# streams checks framing, handshake, response fidelity and SDK teardown.
UPSTREAM = r'''
import json, os, sys, time
counter = sys.argv[1] if len(sys.argv) > 1 else None
tool = {
    "name": "echo", "title": "Echo title", "description": "Full tool metadata",
    "inputSchema": {"type": "object", "properties": {"value": {"type": "string"}}},
    "outputSchema": {"type": "object", "properties": {"value": {"type": "string"}}, "required": ["value"]},
    "annotations": {"readOnlyHint": True, "openWorldHint": False},
    "icons": [{"src": "data:image/png;base64,aA==", "mimeType": "image/png"}],
    "_meta": {"custom": {"preserve": 7}}
}
for line in sys.stdin:
    request = json.loads(line)
    if "id" not in request:
        continue
    method = request["method"]
    params = request.get("params", {})
    if method == "initialize":
        result = {"protocolVersion": "2025-11-25", "capabilities": {"tools": {}},
                  "serverInfo": {"name": "proxy-fixture", "version": "1.0"}}
    elif method == "tools/list":
        if params.get("cursor") is None:
            result = {"tools": [tool], "nextCursor": "page2"}
        else:
            result = {"tools": [{"name": name, "inputSchema": {"type": "object"}}
                               for name in ["error", "slow", "die", "record"]]}
    elif method == "tools/call":
        name = params["name"]
        if name == "die":
            os._exit(2)
        if name in ("record", "slow"):
            if name == "record":
                with open(counter, "a", encoding="utf8") as handle:
                    handle.write("one call\n")
            time.sleep(0.5)
        if name == "error":
            result = {"content": [{"type": "text", "text": "Tool rejected request"}],
                      "isError": True, "_meta": {"marker": 42}}
        else:
            value = params.get("arguments", {}).get("value", "same")
            result = {
                "content": [{"type": "text", "text": value},
                            {"type": "image", "data": "aGVsbG8=", "mimeType": "image/png"},
                            {"type": "resource", "resource": {"uri": "fixture://result", "text": "preserved"}}],
                "structuredContent": {"value": value}, "isError": False,
                "_meta": {"marker": 42}
            }
    else:
        result = {}
    print(json.dumps({"jsonrpc": "2.0", "id": request["id"], "result": result}), flush=True)
'''


class ProxyTests(unittest.IsolatedAsyncioTestCase):
    def proxy(self, **kwargs):
        return FreeCADProxy(sys.executable, ["-u", "-c", UPSTREAM], **kwargs)

    async def test_lazy_start_offline_catalog_and_closed_state(self):
        proxy = FreeCADProxy("drawing2cad-definitely-missing-upstream")
        await proxy.start()
        self.assertFalse(proxy.status()["connected"])
        self.assertEqual(proxy.cached_tools, [])
        with self.assertRaises(ProxyUnavailable):
            await proxy.list_tools()
        self.assertTrue(proxy.status()["catalog_stale"])
        self.assertIsNotNone(proxy.status()["last_error"])
        await proxy.close()
        with self.assertRaises(ProxyUnavailable):
            await proxy.list_tools()

    async def test_pagination_and_metadata_preserved(self):
        async with self.proxy() as proxy:
            tools = await proxy.list_tools()
            self.assertEqual([tool.name for tool in tools],
                             ["freecad_echo", "freecad_error", "freecad_slow", "freecad_die", "freecad_record"])
            data = tools[0].model_dump(by_alias=True, exclude_none=True)
            self.assertEqual(data["title"], "Echo title")
            self.assertTrue(data["annotations"]["readOnlyHint"])
            self.assertEqual(data["_meta"], {"custom": {"preserve": 7}})
            self.assertIn("required", data["outputSchema"])
            self.assertEqual(data["icons"][0]["mimeType"], "image/png")
            tools[0].name = "changed-by-downstream"
            self.assertEqual(proxy.cached_tools[0].name, "freecad_echo")
            self.assertFalse(proxy.status()["catalog_stale"])

    async def test_call_preserves_text_images_resources_structured_and_errors(self):
        async with self.proxy() as proxy:
            await proxy.list_tools()
            result = await proxy.call_tool("freecad_echo", {"value": "unchanged"})
            value = result.model_dump(by_alias=True, exclude_none=True)
            self.assertEqual(value["content"][0]["text"], "unchanged")
            self.assertEqual(value["content"][1], {"type": "image", "data": "aGVsbG8=", "mimeType": "image/png"})
            self.assertEqual(value["content"][2]["resource"]["text"], "preserved")
            self.assertEqual(value["structuredContent"], {"value": "unchanged"})
            self.assertFalse(value["isError"])
            self.assertEqual(value["_meta"], {"marker": 42})
            failed = await proxy.call_tool("freecad_error", {})
            self.assertTrue(failed.is_error)
            self.assertEqual(failed.meta, {"marker": 42})
            self.assertTrue(proxy.status()["connected"])

    async def test_cross_task_requests_and_close_share_worker_owner(self):
        proxy = self.proxy()
        # Start, invoke and close from distinct tasks: SDK cancellation scopes
        # remain owned by proxy's worker, not by these request handlers.
        await asyncio.create_task(proxy.start())
        first, second = await asyncio.gather(
            proxy.call_tool("freecad_slow", {"value": "first"}),
            proxy.call_tool("freecad_echo", {"value": "second"}),
        )
        self.assertEqual(first.structured_content, {"value": "first"})
        self.assertEqual(second.structured_content, {"value": "second"})
        await asyncio.create_task(proxy.close())
        self.assertTrue(proxy.status()["closed"])

    async def test_timeout_never_retries_and_next_call_reconnects(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "calls.txt"
            proxy = FreeCADProxy(sys.executable, ["-u", "-c", UPSTREAM, str(path)], timeout_seconds=0.2)
            async with proxy:
                with self.assertRaises(ProxyTimeout):
                    await proxy.call_tool("freecad_record", {})
                self.assertEqual(path.read_text(encoding="utf8").splitlines(), ["one call"])
                self.assertFalse(proxy.status()["connected"])
                # Recovery is a new explicit request, not a replay.
                result = await proxy.call_tool("freecad_echo", {})
                self.assertFalse(result.is_error)
                self.assertEqual(path.read_text(encoding="utf8").splitlines(), ["one call"])

    async def test_crash_does_not_erase_cached_catalog(self):
        async with self.proxy(timeout_seconds=2) as proxy:
            await proxy.list_tools()
            with self.assertRaises(ProxyUnavailable):
                await proxy.call_tool("freecad_die", {})
            self.assertTrue(proxy.status()["catalog_stale"])
            self.assertEqual(len(proxy.cached_tools), 5)
            self.assertEqual(len(await proxy.list_tools()), 5)
            self.assertFalse(proxy.status()["catalog_stale"])

    async def test_cancelled_queued_request_is_not_dispatched(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "calls.txt"
            async with FreeCADProxy(sys.executable, ["-u", "-c", UPSTREAM, str(path)]) as proxy:
                first = asyncio.create_task(proxy.call_tool("freecad_slow", {}))
                await asyncio.sleep(0.1)
                queued = asyncio.create_task(proxy.call_tool("freecad_record", {}))
                await asyncio.sleep(0)
                queued.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await queued
                await first
                await proxy.call_tool("freecad_echo", {})
                self.assertFalse(path.exists())

    async def test_catalog_deadline_includes_queue_behind_long_cad_call(self):
        async with self.proxy(startup_timeout_seconds=5) as proxy:
            await proxy.list_tools()
            proxy.startup_timeout_seconds = 0.1
            active = asyncio.create_task(proxy.call_tool("freecad_slow", {}))
            await asyncio.sleep(0.02)
            started = time.monotonic()
            with self.assertRaises(ProxyTimeout):
                await proxy.list_tools()
            self.assertLess(time.monotonic() - started, 0.4)
            self.assertTrue(proxy.status()["catalog_stale"])
            await active
            proxy.startup_timeout_seconds = 5
            self.assertEqual(len(await proxy.list_tools()), 5)

    async def test_close_settles_pending_call_without_replay(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "calls.txt"
            proxy = FreeCADProxy(sys.executable, ["-u", "-c", UPSTREAM, str(path)])
            await proxy.list_tools()
            active = asyncio.create_task(proxy.call_tool("freecad_record", {}))
            for _ in range(100):
                if path.exists():
                    break
                await asyncio.sleep(0.01)
            self.assertTrue(path.exists())
            await proxy.close()
            with self.assertRaises(ProxyUnavailable):
                await active
            self.assertEqual(path.read_text(encoding="utf8").splitlines(), ["one call"])

    async def test_next_request_recovers_a_worker_that_ended_while_idle(self):
        async with self.proxy() as proxy:
            await proxy.list_tools()
            worker = proxy._worker
            self.assertIsNotNone(worker)
            worker.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await worker
            self.assertFalse(proxy.status()["connected"])
            self.assertTrue(proxy.status()["catalog_stale"])
            self.assertEqual(len(await proxy.list_tools()), 5)
            self.assertIsNot(worker, proxy._worker)

    async def test_invalid_prefix_does_not_start_upstream(self):
        proxy = self.proxy()
        with self.assertRaises(ValueError):
            await proxy.call_tool("execute_code", {})
        self.assertFalse(proxy.status()["started"])
        await proxy.close()

    def test_invalid_timeouts_rejected(self):
        for value in (0, -1, float("inf"), float("nan")):
            with self.assertRaises(ValueError):
                self.proxy(timeout_seconds=value)


if __name__ == "__main__":
    unittest.main()
