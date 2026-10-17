"""The one shared domain service of the web backend and its MCP endpoint (ADR 0018).

Web routes and agent runs use the same `drawing2cad_mcp` application: routes call the domain service directly,
and agents use the Streamable HTTP endpoint that this backend mounts at `/mcp`. Storage and release rules stay
in the domain service.
"""

from __future__ import annotations

import base64
from hashlib import sha256
import os
from pathlib import Path
import re
from typing import Any

from drawing2cad_mcp.config import CadSettings, DomainSettings, PdfSettings, ServerSettings, Settings
from drawing2cad_mcp.domain_store import DomainError
from drawing2cad_mcp.http import create_http_app
from drawing2cad_mcp.server import Application

ID_PATTERN = re.compile(r"^[a-z]+_[0-9a-f]{32}$")
# Domain error codes that are a client error with a specific HTTP status. Other codes are 422.
HTTP_STATUS = {"NOT_FOUND": 404, "JOB_NOT_FOUND": 404, "REVISION_CONFLICT": 409, "LIMIT_EXCEEDED": 413,
               "DOMAIN_OPERATION_FAILED": 500}


def settings_from_env() -> Settings:
    """Domain profile below `DRAWING2CAD_DATA_DIR`. The MCP endpoint accepts loopback hosts only."""
    data = Path(os.environ.get("DRAWING2CAD_DATA_DIR", ".data")).resolve()
    return Settings(
        pdf=PdfSettings(allowed_roots=[data], output_root=data / "output", pdftoppm=os.environ.get("DRAWING2CAD_PDFTOPPM"),
                        timeout_seconds=90),
        server=ServerSettings(transport="streamable-http"),
        cad=CadSettings(enabled=os.environ.get("DRAWING2CAD_CAD_ENABLED", "1") == "1"),
        domain=DomainSettings(enabled=True, root=data / "domain"),
    )


class ServiceError(Exception):
    """A domain error for the web API, with the HTTP status of its code."""

    def __init__(self, status: int, code: str, message: str, field: str | None = None, recovery: str | None = None):
        super().__init__(message)
        self.status = status
        self.detail = {"code": code, "message": message, "field": field, "recovery": recovery}


def not_found(identifier: str) -> ServiceError:
    return ServiceError(404, "NOT_FOUND", f"Unbekannte Kennung: {identifier}")


def checked_id(identifier: str, prefix: str) -> str:
    """Reject a malformed ID before it reaches the domain service, so that it is not found instead of invalid."""
    if not ID_PATTERN.match(identifier) or not identifier.startswith(prefix + "_"):
        raise not_found(identifier)
    return identifier


class DomainBackend:
    """One `Application` for this process, with the trusted context that it configures for its principal."""

    def __init__(self, settings: Settings):
        self.application = Application(settings)
        self.mcp_app = create_http_app(self.application)
        self.context = self.application.access_context
        self.max_source_bytes = settings.domain.max_source_bytes
        self.chunk_bytes = settings.domain.max_chunk_bytes

    def call(self, operation: str, **arguments: Any) -> dict[str, Any]:
        """Call one domain operation. A domain error becomes a `ServiceError` with its code and next action."""
        assert self.application.domain is not None
        try:
            return self.application.domain.call(self.context, operation, arguments)
        except DomainError as error:
            raise ServiceError(HTTP_STATUS.get(error.code, 422), error.code, error.message, error.target,
                               error.next_action) from None

    def upload(self, filename: str, data: bytes) -> dict[str, Any]:
        """Transfer PDF bytes in bounded chunks and return the immutable source record."""
        started = self.call("upload_begin", filename=filename, size_bytes=len(data), sha256=sha256(data).hexdigest())
        for offset in range(0, len(data), self.chunk_bytes):
            self.call("upload_chunk", upload_id=started["upload_id"], offset=offset,
                      data_base64=base64.b64encode(data[offset:offset + self.chunk_bytes]).decode("ascii"))
        return self.call("upload_complete", upload_id=started["upload_id"])

    def artifact_bytes(self, artifact_id: str) -> tuple[dict[str, Any], bytes]:
        """Metadata and complete content of an artifact. The assembled content must have the recorded SHA-256."""
        metadata = self.call("artifact_get", artifact_id=artifact_id)
        chunks, offset = [], 0
        while True:
            chunk = self.call("artifact_read", artifact_id=artifact_id, offset=offset, length=self.chunk_bytes)
            chunks.append(base64.b64decode(chunk["data_base64"]))
            offset += chunk["length"]
            if chunk["eof"]:
                break
        data = b"".join(chunks)
        if sha256(data).hexdigest() != metadata["sha256"]:
            raise ServiceError(502, "ARTIFACT_HASH_MISMATCH", "Der Inhalt passt nicht zum gespeicherten Hash.",
                               recovery="Erneut laden. Bleibt der Fehler, den Lauf wiederholen.")
        return metadata, data
