"""Drawing2CAD web API on the shared domain service (ADR 0012, ADR 0018)."""

from __future__ import annotations

import os


def main() -> None:
    import uvicorn
    from drawing2cad_mcp.runtime_tools import require_if_configured

    # The backend image shares the runtime of the MCP image (ADR 0035). It refuses to start without its system tools.
    require_if_configured()

    uvicorn.run(
        "drawing_demo.api:create_app",
        factory=True,
        host=os.environ.get("HOST", "127.0.0.1"),
        port=int(os.environ.get("PORT", "8000")),
    )
