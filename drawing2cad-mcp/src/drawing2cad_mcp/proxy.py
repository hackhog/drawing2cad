"""A serialized, lazy MCP-to-MCP bridge to the configured FreeCAD server.

The transport and client session always belong to the same worker task. This
matters because their AnyIO task-group contexts cannot be entered in one MCP
request handler and exited in another. PDF tools need neither this process nor
a running FreeCAD GUI.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from contextlib import AsyncExitStack
from datetime import datetime, timezone
import math
from typing import Any, Literal

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client
from mcp.types import CallToolResult, PaginatedRequestParams, Tool


class ProxyUnavailable(RuntimeError):
    """The upstream transport or protocol request failed."""


class ProxyTimeout(ProxyUnavailable):
    """A request timed out; a mutating request may already have taken effect."""


@dataclass
class _Request:
    operation: Literal["list", "call"]
    future: asyncio.Future[Any]
    name: str | None = None
    arguments: dict[str, Any] | None = None


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _error_text(error: BaseException) -> str:
    if isinstance(error, BaseExceptionGroup):
        return "; ".join(_error_text(item) for item in error.exceptions)
    return str(error) or type(error).__name__


class FreeCADProxy:
    """Expose discovered upstream tools as ``freecad_<original_name>``.

    ``start`` is deliberately connection-free. The first request connects, and
    the worker keeps that connection until failure or ``close``. A failed call
    is never retried; only a subsequent explicit request may reconnect. The
    queue serializes every upstream request because FreeCAD shares one GUI.

    This bridge forwards tool schemas/results, not sampling, elicitation, or
    upstream resources/prompts. The current FreeCAD upstream exposes tools.
    """

    prefix = "freecad_"

    def __init__(
        self,
        command: str,
        args: list[str] | None = None,
        env: dict[str, str] | None = None,
        cwd: str | None = None,
        timeout_seconds: float = 120,
        startup_timeout_seconds: float = 10,
    ) -> None:
        if not command or not isinstance(command, str):
            raise ValueError("FreeCAD upstream command must be a non-empty string")
        for label, value in (("timeout_seconds", timeout_seconds),
                             ("startup_timeout_seconds", startup_timeout_seconds)):
            if not math.isfinite(value) or value <= 0:
                raise ValueError(f"{label} must be finite and greater than zero")
        self.parameters = StdioServerParameters(
            command=command, args=list(args or []), env=dict(env) if env else None, cwd=cwd
        )
        self.timeout_seconds = timeout_seconds
        self.startup_timeout_seconds = startup_timeout_seconds
        self._queue: asyncio.Queue[_Request] = asyncio.Queue()
        self._worker: asyncio.Task[None] | None = None
        self._closed = False
        self._connected = False
        self._catalog: list[Tool] = []
        self._catalog_stale = True
        self._last_error: str | None = None
        self._last_connected_at: str | None = None
        self._last_catalog_at: str | None = None

    async def __aenter__(self) -> FreeCADProxy:
        return await self.start()

    async def __aexit__(self, *_: object) -> None:
        await self.close()

    async def start(self) -> FreeCADProxy:
        if self._closed:
            raise ProxyUnavailable("FreeCAD proxy has been closed")
        if self._worker is None or self._worker.done():
            # A transport can also disappear while idle. Only a new explicit
            # downstream request may start a replacement worker; never replay
            # a request whose outcome was not observed.
            if self._worker is not None and not self._worker.cancelled():
                self._worker.exception()  # consume an unexpected task error
            self._worker = asyncio.create_task(self._run(), name="drawing2cad-freecad-proxy")
        return self

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._worker is not None:
            self._worker.cancel()
            try:
                await self._worker
            except asyncio.CancelledError:
                pass
        self._connected = False
        self._catalog_stale = True
        self._fail_queued(ProxyUnavailable("FreeCAD proxy has been closed"))

    @property
    def cached_tools(self) -> list[Tool]:
        """Last real discovery, for callers that explicitly label stale catalogs."""
        return [tool.model_copy(deep=True) for tool in self._catalog]

    def status(self) -> dict[str, Any]:
        return {
            "started": self._worker is not None,
            "connected": self._connected,
            "closed": self._closed,
            "tool_count": len(self._catalog),
            "catalog_stale": self._catalog_stale,
            "last_error": self._last_error,
            "last_connected_at": self._last_connected_at,
            "last_catalog_at": self._last_catalog_at,
            "timeout_seconds": self.timeout_seconds,
            "startup_timeout_seconds": self.startup_timeout_seconds,
        }

    async def list_tools(self) -> list[Tool]:
        """Refresh the complete catalog, including all upstream pages."""
        return await self._submit("list")

    async def call_tool(
        self, name: str, arguments: dict[str, Any] | None = None
    ) -> CallToolResult:
        if not name.startswith(self.prefix) or name == self.prefix:
            raise ValueError("FreeCAD tool names must start with freecad_ and include a tool name")
        return await self._submit("call", name[len(self.prefix):], arguments)

    async def _submit(
        self, operation: Literal["list", "call"], name: str | None = None,
        arguments: dict[str, Any] | None = None,
    ) -> Any:
        await self.start()
        future = asyncio.get_running_loop().create_future()
        self._queue.put_nowait(_Request(operation, future, name, arguments))
        # If the caller is cancelled, its future is cancelled. Queued requests
        # are skipped; an already dispatched request is allowed to settle and
        # is never replayed. Cancellation cannot undo a FreeCAD operation.
        if operation == "list":
            # Discovery cannot sit behind a long-running CAD operation and
            # block the downstream server's PDF tool catalog. Cancellation of
            # this future also skips it if it is still queued.
            try:
                return await asyncio.wait_for(future, self.startup_timeout_seconds)
            except TimeoutError as error:
                self._catalog_stale = True
                failure = ProxyTimeout("FreeCAD MCP tool discovery timed out; cached catalog is stale")
                self._last_error = str(failure)
                raise failure from error
        return await future

    @staticmethod
    def _fail(request: _Request | None, error: Exception) -> None:
        if request is not None and not request.future.done():
            request.future.set_exception(error)

    def _fail_queued(self, error: Exception) -> None:
        while not self._queue.empty():
            self._fail(self._queue.get_nowait(), error)

    async def _next_request(self) -> _Request:
        while True:
            request = await self._queue.get()
            if not request.future.done():
                return request

    async def _dispatch(self, session: ClientSession, request: _Request) -> Any:
        if request.operation == "call":
            # Do not reconstruct CallToolResult: image/resource blocks, result
            # metadata, structuredContent and isError must survive unchanged.
            return await session.call_tool(request.name or "", request.arguments)
        tools: list[Tool] = []
        seen_names: set[str] = set()
        seen_cursors: set[str] = set()
        cursor: str | None = None
        while True:
            result = await session.list_tools(
                params=PaginatedRequestParams(cursor=cursor) if cursor is not None else None
            )
            for tool in result.tools:
                if tool.name in seen_names:
                    raise ValueError(f"Duplicate upstream tool name: {tool.name}")
                seen_names.add(tool.name)
                tools.append(tool.model_copy(update={"name": self.prefix + tool.name}, deep=True))
            cursor = result.next_cursor
            if cursor is None:
                break
            if cursor in seen_cursors:
                raise ValueError("Upstream repeated a tools/list pagination cursor")
            seen_cursors.add(cursor)
        self._catalog = tools
        self._catalog_stale = False
        self._last_catalog_at = _utc_now()
        return self.cached_tools

    async def _run(self) -> None:
        active: _Request | None = None
        try:
            while True:
                active = await self._next_request()
                try:
                    # Both contexts are entered/exited in this task, even
                    # during cancellation, reconnect, or shutdown.
                    async with AsyncExitStack() as stack:
                        async with asyncio.timeout(self.startup_timeout_seconds):
                            streams = await stack.enter_async_context(stdio_client(self.parameters))
                            session = await stack.enter_async_context(ClientSession(
                                streams[0], streams[1], read_timeout_seconds=self.timeout_seconds
                            ))
                            await session.initialize()
                        self._connected = True
                        self._last_connected_at = _utc_now()
                        self._last_error = None
                        while True:
                            if not active.future.done():
                                timeout = (self.startup_timeout_seconds if active.operation == "list"
                                           else self.timeout_seconds)
                                async with asyncio.timeout(timeout):
                                    result = await self._dispatch(session, active)
                                if not active.future.done():
                                    active.future.set_result(result)
                            active = None
                            active = await self._next_request()
                except asyncio.CancelledError:
                    raise
                except Exception as error:
                    self._catalog_stale = True
                    error_message = _error_text(error)
                    # AnyIO may wrap the timeout while unwinding its groups.
                    def has_timeout(exc: BaseException) -> bool:
                        return isinstance(exc, TimeoutError) or (
                            isinstance(exc, BaseExceptionGroup) and
                            any(has_timeout(child) for child in exc.exceptions)
                        )
                    if has_timeout(error):
                        failure = ProxyTimeout(
                            "FreeCAD MCP request timed out; its outcome may be unknown. "
                            "The request was not retried."
                        )
                    else:
                        uncertain = (
                            " The operation's outcome may be unknown; the request was not retried."
                            if active is not None and active.operation == "call" else ""
                        )
                        failure = ProxyUnavailable(f"FreeCAD MCP unavailable: {error_message}{uncertain}")
                    self._last_error = str(failure)
                    self._fail(active, failure)
                    active = None
                finally:
                    self._connected = False
        finally:
            self._connected = False
            self._catalog_stale = True
            failure = ProxyUnavailable(
                "FreeCAD proxy stopped; an in-flight operation may have an unknown outcome"
            )
            self._fail(active, failure)
            self._fail_queued(failure)
