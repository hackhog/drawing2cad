import base64
from hashlib import sha256
from io import BytesIO
import os
from pathlib import Path
import shutil

import pytest
from fastapi.testclient import TestClient
from pypdf import PdfWriter

from drawing_demo import api
from drawing_demo.api import app

ROOT = Path(__file__).resolve().parents[3]
SAMPLE_DIR = next(
    (p for p in (ROOT / "resources" / "Drawing2CAD", ROOT / "data" / "samples") if p.is_dir()),
    ROOT / "data" / "samples",
)
SAMPLES = sorted(SAMPLE_DIR.glob("*/*_dwg.pdf"))
STEPS = sorted(SAMPLE_DIR.glob("*/*.stp"))
POPPLER = shutil.which(os.environ.get("DRAWING2CAD_PDFTOPPM", "pdftoppm"))

client = TestClient(app)


def test_health():
    data = client.get("/api/health").json()
    assert data["status"] == "ok"
    assert data["drawing2cad_mcp_version"] == api.mcp_version


def test_api_does_not_serve_ui():
    # The frontend container serves the UI (ADR 0012).
    assert client.get("/").status_code == 404


def test_rejects_non_pdf():
    res = client.post("/api/extract", files={"file": ("x.pdf", b"hello", "application/pdf")})
    assert res.status_code == 415


def test_rejects_broken_pdf():
    res = client.post("/api/extract", files={"file": ("x.pdf", b"%PDF-1.7 broken", "application/pdf")})
    assert res.status_code == 422


@pytest.fixture
def service_probe(monkeypatch):
    observed = {"paths": [], "mismatch": False, "render_error": False}

    class ProbeService:
        def __init__(self, allowed_roots, output_root, pdftoppm, max_pdf_bytes):
            observed["roots"] = allowed_roots
            observed["output_root"] = output_root
            observed["max_pdf_bytes"] = max_pdf_bytes

        def extract_drawing(self, path, include_strokes=False):
            assert include_strokes is True
            assert path.parent in observed["roots"]
            observed["paths"].append(path)
            observed["source"] = {"path": str(path), "sha256": sha256(path.read_bytes()).hexdigest(), "size_bytes": path.stat().st_size}
            return {
                "schema_version": 2,
                "source": dict(observed["source"]),
                "sheet_size_mm": [100, 80],
                "summary": {"strokes": 1, "by_kind": {"unclear": 1}, "views": 0, "text_blocks": 0},
                "views": [],
                "text_blocks": [],
                "strokes": [{"id": 7, "kind": "unclear", "type": "circle", "center": [10, 20], "radius": 2}],
            }

        def render_page(self, path, page=1, dpi=150):
            assert path == observed["paths"][0]
            assert page == 1
            assert dpi == api.PAGE_DPI
            output = observed["output_root"] / "page.png"
            output.parent.mkdir(parents=True)
            output.write_bytes(b"test image")
            observed["paths"].append(output)
            if observed["render_error"]:
                raise api.PdfError("render failed")
            source = dict(observed["source"])
            if observed["mismatch"]:
                source["sha256"] = "0" * 64
            return {
                "source": source,
                "artifact": {"path": str(output), "sha256": sha256(output.read_bytes()).hexdigest(), "width_pixels": 402, "height_pixels": 322},
                "provenance": {"renderer": "poppler.pdftoppm", "dpi": dpi, "page": page},
            }

    monkeypatch.setattr(api, "PdfService", ProbeService)
    return observed


def test_upload_uses_shared_service_and_removes_temporary_files(service_probe):
    content = b"%PDF-test-service-boundary"
    res = client.post("/api/extract", files={"file": ("sample.pdf", content, "application/pdf")})
    assert res.status_code == 200
    body = res.json()
    assert body["drawing"]["source"] == "sample.pdf"
    assert body["drawing"]["strokes"][0]["id"] == 7
    assert {flag["kind"] for flag in body["review"]} == {"no_views", "unclear_strokes"}
    assert body["provenance"]["source_sha256"] == sha256(content).hexdigest()
    assert body["page_px_per_mm"] == api.PAGE_DPI / 25.4
    assert base64.b64decode(body["page_png"].split(",")[1]) == b"test image"
    assert service_probe["max_pdf_bytes"] == api.MAX_PDF_BYTES
    for path in service_probe["paths"]:
        assert not path.exists()
        assert str(path) not in res.text


@pytest.mark.parametrize("failure", ["mismatch", "render_error"])
def test_upload_rejects_invalid_render_and_removes_temporary_files(service_probe, failure):
    service_probe[failure] = True
    res = client.post("/api/extract", files={"file": ("sample.pdf", b"%PDF-test", "application/pdf")})
    assert res.status_code == 422
    for path in service_probe["paths"]:
        assert not path.exists()


@pytest.mark.skipif(not POPPLER, reason="Poppler pdftoppm is not available.")
def test_synthetic_pdf_uses_real_service():
    writer = PdfWriter()
    writer.add_blank_page(width=300, height=200)
    stream = BytesIO()
    writer.write(stream)
    content = stream.getvalue()
    res = client.post("/api/extract", files={"file": ("blank.pdf", content, "application/pdf")})
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["drawing"]["source"] == "blank.pdf"
    assert body["provenance"]["source_sha256"] == sha256(content).hexdigest()
    assert body["provenance"]["render"]["renderer"] == "poppler.pdftoppm"
    assert base64.b64decode(body["page_png"].split(",")[1]).startswith(b"\x89PNG\r\n\x1a\n")
    assert any(flag["kind"] == "no_views" for flag in body["review"])


@pytest.mark.skipif(not SAMPLES or not POPPLER, reason="Sample drawings or Poppler are not available.")
@pytest.mark.parametrize("pdf", SAMPLES, ids=lambda p: p.parent.name)
def test_sample_analysis_and_render_agree(pdf):
    content = pdf.read_bytes()
    res = client.post("/api/extract", files={"file": (pdf.name, content, "application/pdf")})
    assert res.status_code == 200, res.text
    body = res.json()
    drawing = body["drawing"]
    assert drawing["source"] == pdf.name
    assert drawing["summary"]["strokes"] == len(drawing["strokes"])
    assert drawing["summary"]["views"] == len(drawing["views"])
    assert drawing["summary"]["text_blocks"] == len(drawing["text_blocks"])
    assert body["provenance"]["source_sha256"] == sha256(content).hexdigest()
    assert body["page_png"].startswith("data:image/png;base64,")


def test_model_rejects_non_step():
    res = client.post("/api/model", files={"file": ("x.stp", b"hello", "application/step")})
    assert res.status_code == 415


def test_model_rejects_broken_step():
    res = client.post("/api/model", files={"file": ("x.stp", b"ISO-10303-21;\nbroken", "application/step")})
    assert res.status_code == 422


# STEP samples are viewer conversion fixtures, not inputs to CAD construction.
@pytest.mark.skipif(not STEPS, reason="Sample STEP files are not available.")
def test_model_converts_step_to_glb():
    step = STEPS[0]
    res = client.post("/api/model", files={"file": (step.name, step.read_bytes(), "application/step")})
    assert res.status_code == 200
    assert res.headers["content-type"] == "model/gltf-binary"
    assert res.content.startswith(b"glTF")
