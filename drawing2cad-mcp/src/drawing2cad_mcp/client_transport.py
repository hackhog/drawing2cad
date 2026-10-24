"""Authenticated Streamable HTTP connections for the evaluation clients."""

from __future__ import annotations

from contextlib import asynccontextmanager
import json
import os
import re
from urllib.parse import unquote, urlsplit

import httpx2
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client


_CREDENTIAL_FIELDS = frozenset({"token", "bearertoken", "accesstoken", "authorization", "password", "apikey", "secret", "headers"})


def _reject_credentials(value):
    if isinstance(value, dict):
        for key, item in value.items():
            if key.lower().replace("_", "").replace("-", "") in _CREDENTIAL_FIELDS:
                raise ValueError("Plan credentials must come from the token environment variable.")
            _reject_credentials(item)
    elif isinstance(value, list):
        for item in value:
            _reject_credentials(item)


def validate_server(plan):
    """Validate connection data without repeating rejected values."""
    if not isinstance(plan, dict) or not isinstance(plan.get("server"), dict):
        raise ValueError("The plan must include a Streamable HTTP server.")
    server = plan["server"]
    if set(server) != {"url", "token_env"}:
        raise ValueError("The server must contain only url and token_env; process commands and credentials are not permitted.")
    url = server["url"]
    if not isinstance(url, str) or not url or any(character.isspace() or ord(character) < 32 for character in url):
        raise ValueError("Use an HTTP or HTTPS MCP URL without credentials, query, or fragment.")
    try:
        parsed = urlsplit(url)
        valid = (parsed.scheme in {"http", "https"} and parsed.hostname and parsed.username is None
                 and parsed.password is None and not parsed.query and not parsed.fragment
                 and "?" not in url and "#" not in url and "\\" not in url)
        parsed.port
    except ValueError:
        valid = False
    if not valid:
        raise ValueError("Use an HTTP or HTTPS MCP URL without credentials, query, or fragment.")
    if not isinstance(server["token_env"], str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,127}", server["token_env"]):
        raise ValueError("The server token_env must name one environment variable.")
    _reject_credentials(plan)


def reject_token(value, token):
    """Reject a credential before input data can enter a trace."""
    if token in json.dumps(value, ensure_ascii=False):
        raise ValueError("The bearer token must not occur in plan or input data.")


def read_token(plan):
    """Read the credential only from the declared environment variable."""
    validate_server(plan)
    token = os.environ.get(plan["server"]["token_env"])
    if token is None or re.fullmatch(r"[A-Za-z0-9._~+/-]+=*", token) is None:
        raise ValueError("Set the declared token environment variable to a nonempty ASCII bearer token.")
    reject_token(plan, token)
    reject_token(unquote(plan["server"]["url"]), token)
    return token


def redact(value, token):
    """Remove the credential from retained messages and responses."""
    if isinstance(value, str):
        return value.replace(token, "[REDACTED]") if token else value
    if isinstance(value, dict):
        return {redact(key, token): redact(item, token) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact(item, token) for item in value]
    return value


@asynccontextmanager
async def connect(server, token, timeout):
    """Open an authenticated session without proxy or credential environment defaults."""
    async with httpx2.AsyncClient(headers={"Authorization": f"Bearer {token}"}, timeout=timeout, trust_env=False) as client:
        async with streamable_http_client(server["url"], http_client=client) as streams:
            async with ClientSession(*streams, read_timeout_seconds=timeout) as session:
                yield session
