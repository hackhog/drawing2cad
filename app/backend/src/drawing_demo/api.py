"""HTTP-API. Die Oberfläche liefert der Frontend-Container aus (ADR 0012).

Hochgeladene PDFs werden nur in einem temporären Ordner verarbeitet und danach gelöscht
(hochgeladen werden Kundenzeichnungen). Es gibt keinen Zustand zwischen Anfragen.
"""

from __future__ import annotations

import base64
import tempfile
from pathlib import Path
from typing import Any

import cascadio
import pymupdf
from drawing_extractor import extract
from drawing_extractor.export import SCHEMA_VERSION, to_dict
from fastapi import FastAPI, HTTPException, Response, UploadFile

from .review import review_flags

MAX_PDF_BYTES = 20 * 1024 * 1024
MAX_STEP_BYTES = 50 * 1024 * 1024
# Vernetzungs-Toleranzen in Modell-Einheiten (mm): fein genug für Bohrungen, Antwort bleibt unter 1 MB
STEP_TOL_LINEAR = 0.05
STEP_TOL_ANGULAR = 0.3
PAGE_PX_PER_MM = 4.0

app = FastAPI(title="Drawing2CAD Demo", version="0.1.0")


@app.get("/api/health")
def health() -> dict[str, Any]:
    return {"status": "ok", "extractor_schema": SCHEMA_VERSION}


@app.post("/api/extract")
def extract_drawing(file: UploadFile) -> dict[str, Any]:
    """PDF → Extraktor-JSON, blasses Seitenbild als Hintergrund und Review-Flags.

    Bewusst `def` statt `async def`: FastAPI führt den rechenintensiven Extraktor dann im Threadpool aus.
    """
    pdf_bytes = file.file.read(MAX_PDF_BYTES + 1)
    if len(pdf_bytes) > MAX_PDF_BYTES:
        raise HTTPException(413, f"PDF größer als {MAX_PDF_BYTES // (1024 * 1024)} MB")
    if not pdf_bytes.startswith(b"%PDF-"):
        raise HTTPException(415, "Keine PDF-Datei")

    with tempfile.TemporaryDirectory(prefix="drawing-demo-") as tmp:
        pdf = Path(tmp) / "upload.pdf"
        pdf.write_bytes(pdf_bytes)
        try:
            drawing = extract(pdf)
            page_png = _render_page(pdf)
        except Exception as exc:  # Extraktor ist auf die BCT-Vorlage zugeschnitten, fremde PDFs scheitern
            raise HTTPException(422, f"Zeichnung konnte nicht gelesen werden: {exc}") from exc

    data = to_dict(drawing)
    data["source"] = Path(file.filename or "upload.pdf").name
    return {
        "drawing": data,
        "page_png": "data:image/png;base64," + base64.b64encode(page_png).decode("ascii"),
        "page_px_per_mm": PAGE_PX_PER_MM,
        "review": review_flags(data),
    }


@app.post("/api/model")
def step_to_glb(file: UploadFile) -> Response:
    """STEP aus der Pipeline → GLB für den 3D-Viewer (Reiter 4). Nur Umwandlung, keine Ablage."""
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


def _render_page(pdf: Path) -> bytes:
    zoom = PAGE_PX_PER_MM * 25.4 / 72.0
    with pymupdf.open(pdf) as doc:
        pix = doc[0].get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), colorspace=pymupdf.csGRAY)
        return pix.tobytes("png")

