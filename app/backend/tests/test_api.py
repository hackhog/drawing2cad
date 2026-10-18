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

ROOT = Path(__file__).resolve().parents[3]
SAMPLE_DIR = next(
    (p for p in (ROOT / "resources" / "Drawing2CAD", ROOT / "data" / "samples") if p.is_dir()),
    ROOT / "data" / "samples",
)
SAMPLES = sorted(SAMPLE_DIR.glob("*/*_dwg.pdf"))
STEPS = sorted(SAMPLE_DIR.glob("*/*.stp"))
POPPLER = shutil.which(os.environ.get("DRAWING2CAD_PDFTOPPM", "pdftoppm"))


@pytest.fixture(autouse=True)
def client(tmp_path, monkeypatch):
    """Each test uses its own data directory and no model endpoint."""
    monkeypatch.setenv("DRAWING2CAD_DATA_DIR", str(tmp_path / "data"))
    for name in ("DRAWING2CAD_AGENT_BASE_URL", "DRAWING2CAD_AGENT_MODEL", "DRAWING2CAD_AGENT_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    with TestClient(api.create_app()) as test_client:
        yield test_client


def upload(client, name, content):
    """Store a PDF and return the response and, on success, its analysis."""
    res = client.post("/api/sources", files={"file": (name, content, "application/pdf")})
    if res.status_code != 200:
        return res, None
    return res, client.get(f"/api/sources/{res.json()['source_id']}/analysis").json()


def test_health(client):
    data = client.get("/api/health").json()
    assert data["status"] == "ok"
    assert data["drawing2cad_mcp_version"] == api.mcp_version


def test_api_does_not_serve_ui(client):
    # The frontend container serves the UI (ADR 0012).
    assert client.get("/").status_code == 404


def test_rejects_non_pdf(client):
    res, _ = upload(client, "x.pdf", b"hello")
    assert res.status_code == 415


def test_rejects_broken_pdf(client):
    res, _ = upload(client, "x.pdf", b"%PDF-1.7 broken")
    assert res.status_code == 422


@pytest.mark.skipif(not POPPLER, reason="Poppler pdftoppm is not available.")
def test_synthetic_pdf_uses_real_service(client, tmp_path):
    writer = PdfWriter()
    writer.add_blank_page(width=300, height=200)
    stream = BytesIO()
    writer.write(stream)
    content = stream.getvalue()
    res, body = upload(client, "blank.pdf", content)
    assert res.status_code == 200, res.text
    assert body["drawing"]["source"] == "blank.pdf"
    assert body["provenance"]["source_sha256"] == sha256(content).hexdigest()
    assert body["provenance"]["render"]["renderer"] == "poppler.pdftoppm"
    assert base64.b64decode(body["page_png"].split(",")[1]).startswith(b"\x89PNG\r\n\x1a\n")
    assert [flag["id"] for flag in body["review"]] == ["views"]
    # Records carry IDs and hashes, never a private server path.
    assert str(tmp_path) not in res.text and str(tmp_path) not in str(body)
    assert client.get("/api/sources").json() == [res.json()]


@pytest.mark.skipif(not SAMPLES or not POPPLER, reason="Sample drawings or Poppler are not available.")
@pytest.mark.parametrize("pdf", SAMPLES, ids=lambda p: p.parent.name)
def test_sample_analysis_and_render_agree(client, pdf):
    content = pdf.read_bytes()
    res, body = upload(client, pdf.name, content)
    assert res.status_code == 200, res.text
    drawing = body["drawing"]
    assert drawing["source"] == pdf.name
    assert drawing["summary"]["strokes"] == len(drawing["strokes"])
    assert drawing["summary"]["views"] == len(drawing["views"])
    assert drawing["summary"]["text_blocks"] == len(drawing["text_blocks"])
    assert body["provenance"]["source_sha256"] == sha256(content).hexdigest()
    assert body["page_png"].startswith("data:image/png;base64,")


@pytest.mark.skipif(not POPPLER, reason="Poppler pdftoppm is not available.")
def test_flag_decisions_reach_the_feedback_export(client):
    writer = PdfWriter()
    writer.add_blank_page(width=300, height=200)
    stream = BytesIO()
    writer.write(stream)
    res, _ = upload(client, "blank.pdf", stream.getvalue())
    source_id = res.json()["source_id"]
    flags = client.get(f"/api/sources/{source_id}/flags").json()["flags"]
    assert [(f["id"], f["message"], f["decision"]) for f in flags] == [("views", "Keine Ansicht erkannt", None)]

    decided = client.put(f"/api/sources/{source_id}/flags/views", json={"action": "ignore", "note": "Leeres Blatt"})
    assert decided.status_code == 200, decided.text
    assert decided.json()["flags"][0]["decision"]["note"] == "Leeres Blatt"
    wrong = client.put(f"/api/sources/{source_id}/flags/views", json={"action": "correct", "text": "R2"})
    assert wrong.status_code == 422

    feedback = client.get("/api/feedback")
    assert feedback.headers["content-disposition"].startswith('attachment; filename="drawing2cad-feedback-')
    assert [(d["filename"], d["flag_id"], d["note"]) for d in feedback.json()["decisions"]] == [
        ("blank.pdf", "views", "Leeres Blatt")]

    reopened = client.put(f"/api/sources/{source_id}/flags/views", json={"action": "reopen"})
    assert reopened.json()["flags"][0]["decision"] is None


def test_model_rejects_non_step(client):
    res = client.post("/api/model", files={"file": ("x.stp", b"hello", "application/step")})
    assert res.status_code == 415


def test_model_rejects_broken_step(client):
    res = client.post("/api/model", files={"file": ("x.stp", b"ISO-10303-21;\nbroken", "application/step")})
    assert res.status_code == 422


# STEP samples are viewer conversion fixtures, not inputs to CAD construction.
@pytest.mark.skipif(not STEPS, reason="Sample STEP files are not available.")
def test_model_converts_step_to_glb(client):
    step = STEPS[0]
    res = client.post("/api/model", files={"file": (step.name, step.read_bytes(), "application/step")})
    assert res.status_code == 200
    assert res.headers["content-type"] == "model/gltf-binary"
    assert res.content.startswith(b"glTF")
