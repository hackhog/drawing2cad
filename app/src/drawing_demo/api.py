"""Serve the demo UI and process uploaded PDFs through the MCP PDF service.

Temporary input files and render artifacts are removed after each request.
"""

from __future__ import annotations

import base64
import os
import tempfile
from pathlib import Path
from typing import Any

import cascadio
from drawing2cad_mcp import __version__ as mcp_version
from drawing2cad_mcp.pdf import PdfError, PdfService
from fastapi import FastAPI, HTTPException, Response, UploadFile
from fastapi.staticfiles import StaticFiles

from .review import review_flags

MAX_PDF_BYTES = 20 * 1024 * 1024
MAX_STEP_BYTES = 50 * 1024 * 1024
# Mesh tolerances use model units (mm).
STEP_TOL_LINEAR = 0.05
STEP_TOL_ANGULAR = 0.3
PAGE_DPI = 102
PAGE_PX_PER_MM = PAGE_DPI / 25.4
STATIC_DIR = Path(__file__).parent / "static"

app = FastAPI(title="Drawing2CAD Demo", version="0.1.0")


@app.get("/api/health")
def health() -> dict[str, Any]:
    return {"status": "ok", "drawing2cad_mcp_version": mcp_version}


@app.post("/api/extract")
def extract_drawing(file: UploadFile) -> dict[str, Any]:
    """Return drawing data, a page image, and review flags from the shared service.

    FastAPI runs this synchronous operation in its thread pool.
    """
    pdf_bytes = file.file.read(MAX_PDF_BYTES + 1)
    if len(pdf_bytes) > MAX_PDF_BYTES:
        raise HTTPException(413, f"PDF größer als {MAX_PDF_BYTES // (1024 * 1024)} MB")
    if not pdf_bytes.startswith(b"%PDF-"):
        raise HTTPException(415, "Keine PDF-Datei")

    with tempfile.TemporaryDirectory(prefix="drawing-demo-") as tmp:
        pdf = Path(tmp) / "upload.pdf"
        pdf.write_bytes(pdf_bytes)
        service = PdfService(
            allowed_roots=(Path(tmp),),
            output_root=Path(tmp) / "artifacts",
            pdftoppm=os.environ.get("DRAWING2CAD_PDFTOPPM"),
            max_pdf_bytes=MAX_PDF_BYTES,
        )
        try:
            data = service.extract_drawing(pdf, include_strokes=True)
            rendered = service.render_page(pdf, page=1, dpi=PAGE_DPI)
            if data["source"]["sha256"] != rendered["source"]["sha256"]:
                raise PdfError("The PDF changed between analysis and rendering.")
            page_png = Path(rendered["artifact"]["path"]).read_bytes()
        except Exception as exc:
            raise HTTPException(422, f"Zeichnung konnte nicht gelesen werden: {exc}") from exc

    # Preserve the browser payload. Temporary server paths must not escape.
    source = data["source"]
    data["source"] = Path(file.filename or "upload.pdf").name
    return {
        "drawing": data,
        "page_png": "data:image/png;base64," + base64.b64encode(page_png).decode("ascii"),
        "page_px_per_mm": PAGE_PX_PER_MM,
        "review": review_flags(data),
        "provenance": {
            "source_sha256": source["sha256"],
            "source_size_bytes": source["size_bytes"],
            "drawing2cad_mcp_version": mcp_version,
            "render": {
                **rendered["provenance"],
                "sha256": rendered["artifact"]["sha256"],
                "width_pixels": rendered["artifact"]["width_pixels"],
                "height_pixels": rendered["artifact"]["height_pixels"],
            },
        },
    }


@app.post("/api/model")
def step_to_glb(file: UploadFile) -> Response:
    """Convert STEP bytes to GLB for the viewer without persistent storage."""
    step_bytes = file.file.read(MAX_STEP_BYTES + 1)
    if len(step_bytes) > MAX_STEP_BYTES:
        raise HTTPException(413, f"STEP größer als {MAX_STEP_BYTES // (1024 * 1024)} MB")
    if not step_bytes.lstrip().startswith(b"ISO-10303-21"):
        raise HTTPException(415, "Keine STEP-Datei")
    try:
        glb = cascadio.load(step_bytes, tol_linear=STEP_TOL_LINEAR, tol_angular=STEP_TOL_ANGULAR)
    except Exception as exc:
        raise HTTPException(422, f"STEP konnte nicht gelesen werden: {exc}") from exc
    if not glb.startswith(b"glTF"):
        raise HTTPException(422, "STEP enthält keine Körper")
    return Response(glb, media_type="model/gltf-binary")


# Register static files last to preserve /api/* routes. The API also works without a UI build.
app.mount("/", StaticFiles(directory=STATIC_DIR, html=True, check_dir=False), name="ui")
