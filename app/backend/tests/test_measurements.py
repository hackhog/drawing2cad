"""Review measurements through the web API: stored per source, listed for all sources, deleted with the source."""

import io

import pytest
from fastapi.testclient import TestClient
from pypdf import PdfWriter

from drawing_demo import api


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DRAWING2CAD_DATA_DIR", str(tmp_path / "data"))
    for name in ("BASE_URL", "MODEL", "API_KEY"):
        monkeypatch.delenv("DRAWING2CAD_AGENT_" + name, raising=False)
    with TestClient(api.create_app()) as test_client:
        yield test_client


def upload(client):
    writer = PdfWriter()
    writer.add_blank_page(width=300, height=200)
    stream = io.BytesIO()
    writer.write(stream)
    res = client.post("/api/sources", files={"file": ("Plate_dwg.pdf", stream.getvalue(), "application/pdf")})
    assert res.status_code == 200, res.text
    return res.json()["source_id"]


def test_measurements_are_listed_for_all_sources_in_recording_order(client):
    first, second = upload(client), upload(client)
    assert client.get("/api/measurements").json() == []
    res = client.post(f"/api/sources/{first}/measurements",
                      json={"review_seconds": 95.5, "manual_hours": 2, "estimator": "drafter"})
    assert res.status_code == 201
    stored = res.json()
    assert stored["measurement_id"].startswith("msr_") and stored["source_id"] == first
    assert stored["review_seconds"] == 95.5 and stored["manual_hours"] == 2 and stored["estimator"] == "drafter"
    # The estimate is optional: a review without an estimate still records its time.
    client.post(f"/api/sources/{second}/measurements", json={"review_seconds": 40})
    listed = client.get("/api/measurements").json()
    assert [(m["source_id"], m["manual_hours"], m["estimator"]) for m in listed] == [(first, 2, "drafter"), (second, None, None)]


@pytest.mark.parametrize("body", [{}, {"review_seconds": 0}, {"review_seconds": 90000}, {"review_seconds": 10, "manual_hours": -1},
                                  {"review_seconds": 10, "estimator": "boss"}])
def test_invalid_measurements_are_rejected(client, body):
    assert client.post(f"/api/sources/{upload(client)}/measurements", json=body).status_code == 422
    assert client.get("/api/measurements").json() == []


def test_a_measurement_needs_a_known_source(client):
    for source_id in ("src_" + "0" * 32, "src_..%2F..%2Fx"):
        assert client.post(f"/api/sources/{source_id}/measurements", json={"review_seconds": 10}).status_code == 404


def test_deleting_a_source_deletes_its_measurements(client):
    gone, kept = upload(client), upload(client)
    for source_id in (gone, kept):
        client.post(f"/api/sources/{source_id}/measurements", json={"review_seconds": 10})
    assert client.delete(f"/api/sources/{gone}").status_code == 204
    assert [m["source_id"] for m in client.get("/api/measurements").json()] == [kept]
