"""Streamable HTTP transport for the shared PDF and restricted CAD services."""

from __future__ import annotations

import hmac
import ipaddress
import os
import re
from typing import TYPE_CHECKING

from mcp.server.transport_security import TransportSecuritySettings
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

if TYPE_CHECKING:
    from .config import HTTPSettings
    from .server import Application


def _is_loopback(host: str) -> bool:
    if host.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _read_token(settings: HTTPSettings) -> str | None:
    token = os.environ.get(settings.token_env)
    if token is not None and re.fullmatch(r"[A-Za-z0-9._~+/-]+=*", token) is None:
        raise ValueError(f"{settings.token_env} must contain a nonempty ASCII bearer token")
    if token is None and not _is_loopback(settings.host):
        raise ValueError(f"Set {settings.token_env} before binding HTTP to a non-loopback host")
    return token


class BearerTokenMiddleware:
    """Authenticate service requests without buffering or altering MCP streams."""

    def __init__(self, app: ASGIApp, token: str) -> None:
        self.app = app
        self.token = token.encode("ascii")

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            headers = [value for key, value in scope["headers"] if key.lower() == b"authorization"]
            valid = False
            if len(headers) == 1:
                scheme, separator, credential = headers[0].partition(b" ")
                valid = bool(separator) and scheme.lower() == b"bearer" and hmac.compare_digest(credential, self.token)
            if not valid:
                response = JSONResponse(
                    {"error": "unauthorized"}, status_code=401,
                    headers={"WWW-Authenticate": "Bearer", "Cache-Control": "no-store"},
                )
                await response(scope, receive, send)
                return
        await self.app(scope, receive, send)


def create_http_app(application: Application) -> Starlette:
    """Create one ASGI app with one service lifecycle and no session store.

    The SDK enters Application.lifespan once, even with multiple clients. Part
    storage and execution limits remain shared; stateless describes transport
    sessions only. A fresh Application is required for a new server lifecycle.
    """
    settings = application.settings.http
    token = _read_token(settings)
    app = application.server.streamable_http_app(
        streamable_http_path="/mcp",
        stateless_http=True,
        json_response=False,
        max_request_body_size=4 * 1024 * 1024,
        transport_security=TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=settings.allowed_hosts,
            allowed_origins=settings.allowed_origins,
        ),
    )
    if token is not None:
        app.add_middleware(BearerTokenMiddleware, token=token)
    application.transport = "streamable-http"
    return app
