import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from drawing_demo.api import app

ROOT = Path(__file__).resolve().parents[2]
# Team-Repo: resources/Drawing2CAD, lokale Arbeitskopie: data/samples
SAMPLE_DIR = next((p for p in (ROOT / "resources" / "Drawing2CAD", ROOT / "data" / "samples") if p.is_dir()), ROOT / "data" / "samples")
SAMPLES = sorted(SAMPLE_DIR.glob("*/*_dwg.pdf"))
EXPECTED = ROOT / "extractor" / "out"
STEPS = sorted(SAMPLE_DIR.glob("*/*.stp"))
UI_BUILT = (Path(__file__).resolve().parents[1] / "src" / "drawing_demo" / "static" / "index.html").exists()

client = TestClient(app)


def test_health():
    assert client.get("/api/health").json()["status"] == "ok"


@pytest.mark.skipif(not UI_BUILT, reason="Oberfläche nicht gebaut (cd web && npm ci && npm run build)")
def test_ui_is_served():
    res = client.get("/")
    assert res.status_code == 200
    assert "Drawing2CAD" in res.text


def test_rejects_non_pdf():
    res = client.post("/api/extract", files={"file": ("x.pdf", b"hello", "application/pdf")})
    assert res.status_code == 415


def test_rejects_broken_pdf():
    res = client.post("/api/extract", files={"file": ("x.pdf", b"%PDF-1.7 kaputt", "application/pdf")})
    assert res.status_code == 422


@pytest.mark.skipif(not SAMPLES, reason="Beispielzeichnungen fehlen")
@pytest.mark.parametrize("pdf", SAMPLES, ids=lambda p: p.parent.name)
def test_sample_matches_extractor_cli(pdf):
    res = client.post("/api/extract", files={"file": (pdf.name, pdf.read_bytes(), "application/pdf")})
    assert res.status_code == 200
    body = res.json()
    assert body["drawing"]["source"] == pdf.name
    assert body["page_png"].startswith("data:image/png;base64,")

    expected_file = EXPECTED / f"{pdf.stem.removesuffix('_dwg')}.json"
    if expected_file.exists():
        expected = json.loads(expected_file.read_text(encoding="utf-8"))
        assert body["drawing"]["summary"] == expected["summary"]
        assert [t["text"] for t in body["drawing"]["text_blocks"]] == [t["text"] for t in expected["text_blocks"]]


def test_model_rejects_non_step():
    res = client.post("/api/model", files={"file": ("x.stp", b"hello", "application/step")})
    assert res.status_code == 415


def test_model_rejects_broken_step():
    res = client.post("/api/model", files={"file": ("x.stp", b"ISO-10303-21;\nkaputt", "application/step")})
    assert res.status_code == 422


# Die STEP-Dateien sind hier nur Testdaten für die Umwandlung, keine Eingabe der Pipeline
@pytest.mark.skipif(not STEPS, reason="Beispiel-STEP fehlen")
def test_model_converts_step_to_glb():
    step = STEPS[0]
    res = client.post("/api/model", files={"file": (step.name, step.read_bytes(), "application/step")})
    assert res.status_code == 200
    assert res.headers["content-type"] == "model/gltf-binary"
    assert res.content.startswith(b"glTF")
