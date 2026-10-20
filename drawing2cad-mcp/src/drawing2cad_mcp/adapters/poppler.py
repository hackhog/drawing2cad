"""Replace a restricted worker with Poppler pdftoppm. The raster is independent of the drawing generator."""

import os
from pathlib import Path

BINARY = Path("/usr/bin/pdftoppm")
# Fixed resolution of the verification raster. The verifier converts sheet mm to pixels with it.
DPI = 300
MAX_PAGES = 8


def capabilities() -> dict:
    return {"available": BINARY.is_file() and os.access(BINARY, os.X_OK), "renderer": "Poppler pdftoppm", "dpi": DPI,
            "max_pages": MAX_PAGES}


def exec_pdftoppm(directory: Path, scope: dict) -> None:
    """Keep Landlock, seccomp, and resource limits across execve. pdftoppm writes page-N.png into the work directory."""
    if scope.get("profile") != "linux-landlock-seccomp-v1":
        raise ValueError("The PDF renderer requires the restricted worker profile.")
    if not capabilities()["available"]:
        raise ValueError("Poppler pdftoppm is not installed.")
    source = directory / "input.pdf"
    if not source.is_file():
        raise ValueError("The PDF input is missing.")
    # Gray PNG pages at a fixed resolution; at most MAX_PAGES pages. The verifier rejects a PDF with more pages.
    os.execv(str(BINARY), [str(BINARY), "-r", str(DPI), "-gray", "-png", "-l", str(MAX_PAGES), str(source), str(directory / "page")])
