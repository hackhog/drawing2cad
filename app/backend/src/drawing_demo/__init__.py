"""Demo-App für Drawing2CAD (ADR 0006): Zeichnungs-PDF hochladen, Ergebnis des Extraktors ansehen."""

from __future__ import annotations

import os


def main() -> None:
    import uvicorn

    uvicorn.run(
        "drawing_demo.api:app",
        host=os.environ.get("HOST", "127.0.0.1"),
        port=int(os.environ.get("PORT", "8000")),
    )
