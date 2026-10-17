"""Web API: stored drawing sources, their analysis, agent runs, artifacts, and STEP display (ADR 0012, ADR 0016).

PDF analysis uses the shared MCP PDF service in process. CAD work runs only through the MCP server in agent runs.
"""

from __future__ import annotations

import base64
import io
from functools import lru_cache
from urllib.parse import quote
import os
from pathlib import Path
import tempfile
from typing import Any
import zipfile

import cascadio
from drawing2cad_mcp import __version__ as mcp_version
from drawing2cad_mcp.pdf import PdfError, PdfService
from fastapi import FastAPI, HTTPException, Response, UploadFile

from .agent.model import ModelSettings
from .agent.runner import AgentRunner
from .review import review_flags
from .store import NotFound, Store

MAX_PDF_BYTES = 20 * 1024 * 1024
MAX_STEP_BYTES = 50 * 1024 * 1024
# Mesh tolerances use model units (mm).
STEP_TOL_LINEAR = 0.05
STEP_TOL_ANGULAR = 0.3
PAGE_DPI = 102
PAGE_PX_PER_MM = PAGE_DPI / 25.4
CONTRACT_VERSION = "0.1.0-provisional"

app = FastAPI(title="Drawing2CAD", version="0.2.0")


def _skill_path() -> Path:
    """The drawing2cad skill: from the environment, else from the repository layout."""
    configured = os.environ.get("DRAWING2CAD_SKILL_PATH")
    if configured:
        return Path(configured)
    return Path.cwd().parents[1] / "skills" / "drawing2cad" / "SKILL.md"


@lru_cache(maxsize=1)
def services() -> tuple[Store, AgentRunner]:
    """One store and one runner for this process. Tests call `services.cache_clear()` after an environment change."""
    store = Store(Path(os.environ.get("DRAWING2CAD_DATA_DIR", ".data")))
    store.fail_interrupted_runs()
    return store, AgentRunner(store, ModelSettings.from_env(), _skill_path())


def _not_found(error: NotFound) -> HTTPException:
    return HTTPException(404, {"code": "NOT_FOUND", "message": f"Unbekannte Kennung: {error}", "field": None, "recovery": None})


@app.get("/api/health")
def health() -> dict[str, Any]:
    return {"status": "ok", "drawing2cad_mcp_version": mcp_version}


@app.get("/api/capabilities")
def capabilities() -> dict[str, Any]:
    _, runner = services()
    return {
        "contract_version": CONTRACT_VERSION, "simulated": False, "runs": runner.available, "parameter_edit": False,
        "notes": False, "downloads": True, "model_preview": True, "step_preview_upload": True, "max_pdf_bytes": MAX_PDF_BYTES,
    }


def analyze_pdf(pdf_bytes: bytes, filename: str) -> dict[str, Any]:
    """Drawing data, a page image, and review flags from the shared PDF service. Temporary files are removed."""
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

    # Temporary server paths must not escape.
    source = data["source"]
    data["source"] = filename
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


@app.post("/api/sources")
def upload_source(file: UploadFile) -> dict[str, Any]:
    """Store an uploaded PDF and its analysis. FastAPI runs this synchronous operation in its thread pool."""
    pdf_bytes = file.file.read(MAX_PDF_BYTES + 1)
    if len(pdf_bytes) > MAX_PDF_BYTES:
        raise HTTPException(413, f"PDF größer als {MAX_PDF_BYTES // (1024 * 1024)} MB")
    if not pdf_bytes.startswith(b"%PDF-"):
        raise HTTPException(415, "Keine PDF-Datei")
    filename = Path(file.filename or "upload.pdf").name
    analysis = analyze_pdf(pdf_bytes, filename)
    store, _ = services()
    return store.add_source(filename, pdf_bytes, analysis)


@app.get("/api/sources")
def list_sources() -> list[dict[str, Any]]:
    return services()[0].list_sources()


@app.get("/api/sources/{source_id}")
def get_source(source_id: str) -> dict[str, Any]:
    try:
        return services()[0].source(source_id)
    except NotFound as error:
        raise _not_found(error) from None


@app.delete("/api/sources/{source_id}", status_code=204)
def delete_source(source_id: str) -> Response:
    try:
        services()[0].delete_source(source_id)
    except NotFound as error:
        raise _not_found(error) from None
    except ValueError as error:
        raise HTTPException(409, {"code": "RUN_ACTIVE", "message": str(error), "field": None,
                                  "recovery": "Warten, bis der Lauf beendet ist."}) from None
    return Response(status_code=204)


@app.get("/api/sources/{source_id}/analysis")
def get_analysis(source_id: str) -> dict[str, Any]:
    try:
        return services()[0].analysis(source_id)
    except NotFound as error:
        raise _not_found(error) from None


@app.get("/api/sources/{source_id}/runs")
def list_runs(source_id: str) -> list[dict[str, Any]]:
    store, _ = services()
    try:
        store.source(source_id)
    except NotFound as error:
        raise _not_found(error) from None
    return store.list_runs(source_id)


@app.post("/api/sources/{source_id}/runs", status_code=201)
def create_run(source_id: str) -> dict[str, Any]:
    """Queue one agent run. The agent builds the model only through the MCP server (ADR 0016)."""
    store, runner = services()
    if not runner.available:
        raise HTTPException(503, {"code": "CAPABILITY_UNAVAILABLE", "field": None,
                                  "message": "Kein Modell-Endpunkt konfiguriert (DRAWING2CAD_AGENT_*).",
                                  "recovery": "Endpunkt in .env eintragen und das Backend neu starten."})
    try:
        run = store.add_run(source_id)
    except NotFound as error:
        raise _not_found(error) from None
    runner.submit(run["run_id"])
    return run


@app.get("/api/runs/{run_id}")
def get_run(run_id: str) -> dict[str, Any]:
    try:
        return services()[0].run(run_id)
    except NotFound as error:
        raise _not_found(error) from None


# Run files open in a browser tab, so text formats are served as text instead of a download.
TEXT_SUFFIXES = {".json", ".jsonl", ".log", ".toml", ".txt", ".md", ".lock"}


def _run_files(run_id: str) -> dict[str, Path]:
    try:
        return services()[0].run_files(run_id)
    except NotFound as error:
        raise _not_found(error) from None


@app.get("/api/runs/{run_id}/files")
def list_run_files(run_id: str) -> dict[str, Any]:
    """Trace, run record, and MCP part state of one run, for inspection of a run in the browser."""
    base = f"/api/runs/{quote(run_id)}/files"
    files = [{"path": name, "byte_count": path.stat().st_size, "url": f"{base}/{quote(name)}"}
             for name, path in _run_files(run_id).items()]
    return {"files": files, "archive_url": f"/api/runs/{quote(run_id)}/archive"}


@app.get("/api/runs/{run_id}/files/{name:path}")
def run_file(run_id: str, name: str) -> Response:
    # Only listed names are served, so a name can never select a path outside the run.
    path = _run_files(run_id).get(name)
    if path is None:
        raise _not_found(NotFound(name))
    media_type = "text/plain; charset=utf-8" if path.suffix in TEXT_SUFFIXES else "application/octet-stream"
    disposition = "inline" if path.suffix in TEXT_SUFFIXES else "attachment"
    return Response(path.read_bytes(), media_type=media_type,
                    headers={"Content-Disposition": f"{disposition}; filename*=UTF-8''{quote(path.name)}"})


@app.get("/api/runs/{run_id}/archive")
def run_archive(run_id: str) -> Response:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, path in _run_files(run_id).items():
            archive.write(path, f"{run_id}/{name}")
    return Response(buffer.getvalue(), media_type="application/zip",
                    headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(run_id)}.zip"})


@app.get("/api/artifacts/{artifact_id}/content")
def artifact_content(artifact_id: str) -> Response:
    try:
        artifact, path = services()[0].artifact(artifact_id)
    except NotFound as error:
        raise _not_found(error) from None
    return Response(path.read_bytes(), media_type=artifact["media_type"],
                    headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(artifact['filename'])}"})


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
