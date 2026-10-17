"""Drawing2CAD web API on the shared domain service (ADR 0012, ADR 0017)."""

from __future__ import annotations

import os


def main() -> None:
    import uvicorn

    uvicorn.run(
        "drawing_demo.api:create_app",
        factory=True,
        host=os.environ.get("HOST", "127.0.0.1"),
        port=int(os.environ.get("PORT", "8000")),
    )
