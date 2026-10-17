"""Published fixtures and actual storage responses use the same record types."""

import base64
import hashlib
import json
from pathlib import Path

from drawing2cad_mcp.domain_contracts import RECORD_MODELS, domain_schema
from drawing2cad_mcp.domain_store import AccessContext, DomainStore
from drawing2cad_mcp.domain_jobs import JobService


def test_published_synthetic_records_follow_schema():
    fixture = Path(__file__).resolve().parents[2] / "docs/contracts/fixtures/m2-records.json"
    data = json.loads(fixture.read_text(encoding="utf8"))
    assert data["synthetic"] is True
    assert data["schema_version"] == domain_schema()["schema_version"]
    assert set(data["records"]) == set(RECORD_MODELS)
    for name, record in data["records"].items():
        RECORD_MODELS[name].model_validate(record)


def test_real_storage_records_follow_published_schema(tmp_path):
    store = DomainStore(tmp_path)
    ctx = AccessContext("fixture-user")
    data = b"%PDF-1.4\nSynthetic storage fixture\n%%EOF\n"
    upload = store.upload_begin(ctx, "synthetic.pdf", len(data), hashlib.sha256(data).hexdigest())
    RECORD_MODELS["UploadRecord"].model_validate(upload)
    store.upload_chunk(ctx, upload["upload_id"], 0, base64.b64encode(data).decode())
    source = store.upload_complete(ctx, upload["upload_id"])
    RECORD_MODELS["SourceRecord"].model_validate(source)
    artifact = store.artifact_register(ctx, store.source_path(ctx, source["source_id"]),
                                       "fixture", "synthetic_plate", 1, "application/pdf", "drawing.pdf")
    RECORD_MODELS["ArtifactRecord"].model_validate(artifact)
    RECORD_MODELS["ArtifactChunk"].model_validate(store.artifact_read(ctx, artifact["artifact_id"]))
    RECORD_MODELS["RunNote"].model_validate(store.notes_update(ctx, "synthetic_plate", 0, "Pending review."))
    jobs = JobService(tmp_path / "jobs", lambda *args: {})
    job = jobs.submit(ctx, "build_from_description", {"run_id": "synthetic_plate", "expected_revision": 1}, "fixture")
    RECORD_MODELS["JobRecord"].model_validate(job)
