"""Web API: drawing sources, their analysis, agent runs, artifacts, and STEP display (ADR 0012, ADR 0018).

Every route uses the one shared domain service of this process. The backend also mounts the MCP endpoint of that
service at `/mcp`, for its agent runs. The web adapter adds no storage or release rule.
"""

from __future__ import annotations

import base64
from collections import OrderedDict
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime, timezone
import io
import os
from pathlib import Path
import struct
import threading
from typing import Any
from urllib.parse import quote
import zipfile

import cascadio
from drawing2cad_mcp import __version__ as mcp_version
from drawing2cad_mcp.part_schema import part_validate
from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request, Response, UploadFile
from fastapi.responses import JSONResponse

from .agent.mapping import artifact_view, part_view, review_view
from .agent.model import ModelSettings
from .agent.runner import AgentRunner
from .jobs import JobStore
from .review import review_flags
from .service import DomainBackend, ServiceError, checked_id, not_found, settings_from_env

MAX_STEP_BYTES = 50 * 1024 * 1024
# Mesh tolerances use model units (mm).
STEP_TOL_LINEAR = 0.05
STEP_TOL_ANGULAR = 0.3
PAGE_DPI = 102
PAGE_PX_PER_MM = PAGE_DPI / 25.4
CONTRACT_VERSION = "0.1.0-provisional"
# Analyses are derived from immutable sources. The cache prevents a new page render for each request.
ANALYSIS_CACHE_SIZE = 32
# Each part_read is a recorded CAD call that counts against the step budget of its part run.
# The UI polls runs, so the details of a finished run are read once and kept in memory.
RESULT_CACHE_SIZE = 64
# Run files open in a browser tab, so text formats are served as text instead of a download.
TEXT_SUFFIXES = {".json", ".jsonl", ".log", ".txt", ".md"}


def _skill_path() -> Path:
    """The drawing2cad skill: from the environment, else from the repository layout."""
    configured = os.environ.get("DRAWING2CAD_SKILL_PATH")
    if configured:
        return Path(configured)
    return Path.cwd().parents[1] / "skills" / "drawing2cad" / "SKILL.md"


class Services:
    """The domain backend, the web run records, and the agent runner of one application."""

    def __init__(self) -> None:
        settings = settings_from_env()
        self.backend = DomainBackend(settings)
        self.jobs = JobStore(Path(os.environ.get("DRAWING2CAD_DATA_DIR", ".data")) / "web-runs")
        mcp_url = os.environ.get("DRAWING2CAD_MCP_URL", f"http://127.0.0.1:{os.environ.get('PORT', '8000')}/mcp")
        self.runner = AgentRunner(self.backend, self.jobs, ModelSettings.from_env(), _skill_path(), mcp_url,
                                  os.environ.get(settings.http.token_env))
        self._analyses: OrderedDict[str, dict[str, Any]] = OrderedDict()
        self._results: OrderedDict[str, dict[str, Any]] = OrderedDict()
        self._lock = threading.Lock()

    def result(self, record: dict[str, Any]) -> dict[str, Any]:
        """Part, review, artifacts, and report of a finished run, read once from the domain service."""
        with self._lock:
            if record["run_id"] in self._results:
                return self._results[record["run_id"]]
        result = part_result(self, record)
        with self._lock:
            self._results[record["run_id"]] = result
            while len(self._results) > RESULT_CACHE_SIZE:
                self._results.popitem(last=False)
        return result

    def analysis(self, source: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            if source["source_id"] in self._analyses:
                self._analyses.move_to_end(source["source_id"])
                return self._analyses[source["source_id"]]
        result = analyze(self.backend, source)
        with self._lock:
            self._analyses[source["source_id"]] = result
            while len(self._analyses) > ANALYSIS_CACHE_SIZE:
                self._analyses.popitem(last=False)
        return result


def analyze(backend: DomainBackend, source: dict[str, Any]) -> dict[str, Any]:
    """Drawing data, a page image, and review flags of the first page, from the shared domain service."""
    data = backend.call("drawing_extract", source_id=source["source_id"], include_strokes=True)
    rendered = backend.call("pdf_render_page", source_id=source["source_id"], page=1, dpi=PAGE_DPI, include_image=False)
    if data["source"]["sha256"] != rendered["source"]["sha256"]:
        raise ServiceError(422, "SOURCE_HASH_MISMATCH", "Analyse und Seitenbild stammen aus verschiedenen Dateien.")
    artifact, page_png = backend.artifact_bytes(rendered["artifact"]["artifact_id"])
    width, height = struct.unpack(">II", page_png[16:24])  # The PNG IHDR chunk follows the signature.
    data["source"] = source["filename"]
    return {
        "drawing": data,
        "page_png": "data:image/png;base64," + base64.b64encode(page_png).decode("ascii"),
        "page_px_per_mm": PAGE_PX_PER_MM,
        "review": review_flags(data),
        "provenance": {
            "source_sha256": source["sha256"],
            "source_size_bytes": source["size_bytes"],
            "drawing2cad_mcp_version": mcp_version,
            "render": {**rendered.get("provenance", {}), "sha256": artifact["sha256"], "width_pixels": width,
                       "height_pixels": height},
        },
    }


def source_view(source: dict[str, Any]) -> dict[str, Any]:
    return {"source_id": source["source_id"], "filename": source["filename"], "media_type": source["media_type"],
            "byte_count": source["size_bytes"], "sha256": source["sha256"], "upload_state": "complete",
            "created_at": datetime.fromtimestamp(source["created"], timezone.utc).isoformat()}


def _all(backend: DomainBackend, operation: str, **arguments: Any) -> list[dict[str, Any]]:
    """All items of a paged domain listing."""
    items, cursor = [], None
    while True:
        page = backend.call(operation, limit=100, cursor=cursor, **arguments)
        items += page["items"]
        cursor = page["next_cursor"]
        if cursor is None:
            return items


def part_result(services: Services, record: dict[str, Any]) -> dict[str, Any]:
    """Part, review, artifacts, and agent report of the domain part run of a web run."""
    backend = services.backend
    part_run = record["part_run_id"]
    state = backend.call("part_read", run_id=part_run)["part"]
    source = backend.call("source_get", source_id=record["source_id"])
    sheet = tuple(services.analysis(source)["drawing"]["sheet_size_mm"])
    review_items = part_validate(state["description"]).get("review_items", [])
    # The domain lists artifacts by ID. Creation order lets the UI select the latest drawing of a revision.
    listed = sorted(_all(backend, "artifact_list", run_id=part_run), key=lambda artifact: artifact["created"])
    artifacts = (artifact_view(a, source["sha256"]) for a in listed)
    return {"part": part_view(state), "review": review_view(state, review_items, sheet, released=bool(state.get("release"))),
            "artifacts": [a for a in artifacts if a is not None],
            "agent_report": backend.call("notes_read", run_id=part_run)["text"] or None}


def run_view(services: Services, record: dict[str, Any]) -> dict[str, Any]:
    """A web run record with the part, review, artifacts, and agent report of its domain part run.

    An active run shows only its job state: a part_read during the run would use the agent's step budget.
    """
    view = {key: record[key] for key in ("run_id", "source_id", "phase", "job", "error")}
    view["failed_phase"] = record.get("failed_phase")  # Records from before this field have none.
    view["agent"] = record.get("agent")
    view.update(part=None, review=None, artifacts=[], simulated=False)
    if record["part_run_id"] is None or record["job"]["status"] in ("queued", "running"):
        return view
    return {**view, **services.result(record)}


def services(request: Request) -> Services:
    return request.app.state.services


router = APIRouter(prefix="/api")


@router.get("/health")
def health() -> dict[str, Any]:
    return {"status": "ok", "drawing2cad_mcp_version": mcp_version}


@router.get("/capabilities")
def capabilities(s: Services = Depends(services)) -> dict[str, Any]:
    return {
        "contract_version": CONTRACT_VERSION, "simulated": False, "runs": s.runner.available, "parameter_edit": False,
        "notes": False, "downloads": True, "model_preview": True, "step_preview_upload": True,
        "max_pdf_bytes": s.backend.max_source_bytes,
    }


@router.post("/sources")
def upload_source(file: UploadFile, s: Services = Depends(services)) -> dict[str, Any]:
    """Transfer an uploaded PDF to the domain service. FastAPI runs this synchronous operation in its thread pool."""
    limit = s.backend.max_source_bytes
    pdf_bytes = file.file.read(limit + 1)
    if len(pdf_bytes) > limit:
        raise HTTPException(413, f"PDF größer als {limit // (1024 * 1024)} MB")
    if not pdf_bytes.startswith(b"%PDF-"):
        raise HTTPException(415, "Keine PDF-Datei")
    return source_view(s.backend.upload(Path(file.filename or "upload.pdf").name, pdf_bytes))


@router.get("/sources")
def list_sources(s: Services = Depends(services)) -> list[dict[str, Any]]:
    return [source_view(source) for source in _all(s.backend, "source_list")]


def _source(s: Services, source_id: str) -> dict[str, Any]:
    return s.backend.call("source_get", source_id=checked_id(source_id, "src"))


@router.get("/sources/{source_id}")
def get_source(source_id: str, s: Services = Depends(services)) -> dict[str, Any]:
    return source_view(_source(s, source_id))


@router.get("/sources/{source_id}/analysis")
def get_analysis(source_id: str, s: Services = Depends(services)) -> dict[str, Any]:
    return s.analysis(_source(s, source_id))


@router.get("/sources/{source_id}/runs")
def list_runs(source_id: str, s: Services = Depends(services)) -> list[dict[str, Any]]:
    _source(s, source_id)
    return [run_view(s, record) for record in s.jobs.list(source_id)]


@router.post("/sources/{source_id}/runs", status_code=201)
def create_run(source_id: str, s: Services = Depends(services)) -> dict[str, Any]:
    """Queue one agent run. The agent builds the model only through the MCP endpoint (ADR 0018)."""
    if not s.runner.available:
        raise ServiceError(503, "CAPABILITY_UNAVAILABLE", "Kein Modell-Endpunkt konfiguriert (DRAWING2CAD_AGENT_*).",
                           recovery="Endpunkt in .env eintragen und das Backend neu starten.")
    assert s.runner.settings is not None
    record = s.jobs.add(_source(s, source_id)["source_id"],
                        agent={"model": s.runner.settings.model, "mcp_version": mcp_version})
    s.runner.submit(record["run_id"])
    return run_view(s, record)


@router.get("/runs/{run_id}")
def get_run(run_id: str, s: Services = Depends(services)) -> dict[str, Any]:
    return run_view(s, s.jobs.get(run_id))


@router.get("/runs/{run_id}/files")
def list_run_files(run_id: str, s: Services = Depends(services)) -> dict[str, Any]:
    """The run record and agent trace of one run, for inspection of a run in the browser."""
    base = f"/api/runs/{quote(run_id)}/files"
    files = [{"path": name, "byte_count": path.stat().st_size, "url": f"{base}/{quote(name)}"}
             for name, path in s.jobs.files(run_id).items()]
    return {"files": files, "archive_url": f"/api/runs/{quote(run_id)}/archive"}


@router.get("/runs/{run_id}/files/{name:path}")
def run_file(run_id: str, name: str, s: Services = Depends(services)) -> Response:
    # Only listed names are served, so a name can never select a path outside the run.
    path = s.jobs.files(run_id).get(name)
    if path is None:
        raise not_found(name)
    text = path.suffix in TEXT_SUFFIXES
    return Response(path.read_bytes(), media_type="text/plain; charset=utf-8" if text else "application/octet-stream",
                    headers={"Content-Disposition": f"{'inline' if text else 'attachment'}; filename*=UTF-8''{quote(path.name)}"})


@router.get("/runs/{run_id}/archive")
def run_archive(run_id: str, s: Services = Depends(services)) -> Response:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, path in s.jobs.files(run_id).items():
            archive.write(path, f"{run_id}/{name}")
    return Response(buffer.getvalue(), media_type="application/zip",
                    headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(run_id)}.zip"})


@router.get("/artifacts/{artifact_id}/content")
def artifact_content(artifact_id: str, s: Services = Depends(services)) -> Response:
    artifact, data = s.backend.artifact_bytes(checked_id(artifact_id, "art"))
    return Response(data, media_type=artifact["media_type"],
                    headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(artifact['filename'])}"})


@router.post("/model")
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


def create_app() -> FastAPI:
    """One application with one domain service. Its lifespan also starts and stops the mounted MCP endpoint."""
    state = Services()

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        state.jobs.fail_interrupted()
        # FastAPI does not run the lifespan of a mounted app. This one starts the domain service.
        async with state.backend.mcp_app.router.lifespan_context(state.backend.mcp_app):
            yield
        state.runner.close()

    app = FastAPI(title="Drawing2CAD", version="0.3.0", lifespan=lifespan)
    app.state.services = state

    @app.exception_handler(ServiceError)
    async def service_error(_: Request, error: ServiceError) -> JSONResponse:
        return JSONResponse({"detail": error.detail}, status_code=error.status)

    app.include_router(router)
    # The MCP app serves only /mcp. Mount it last, so that it does not hide an API route.
    app.mount("/", state.backend.mcp_app)
    return app
