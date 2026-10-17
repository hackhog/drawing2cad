"""Versioned public records for adapters and synthetic contract fixtures."""

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field


OpaqueId = Annotated[str, Field(pattern=r"^[a-z]+_[0-9a-f]{32}$")]
Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


class Record(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SourceRecord(Record):
    source_id: OpaqueId
    filename: str
    media_type: Literal["application/pdf"]
    size_bytes: int
    sha256: Digest
    created: float
    status: Literal["uploaded"]
    pdf_validation: Literal["not_tested"]


class ArtifactRecord(Record):
    artifact_id: OpaqueId
    filename: str
    size_bytes: int
    sha256: Digest
    role: str
    run_id: str
    revision: int
    media_type: str
    created: float


class UploadRecord(Record):
    upload_id: OpaqueId
    filename: str
    size_bytes: int
    sha256: Digest
    offset: int
    status: Literal["uploading", "complete", "aborted"]
    source_id: OpaqueId | None
    created: float


class ArtifactChunk(Record):
    artifact_id: OpaqueId
    offset: int
    length: int
    data_base64: str
    eof: bool
    sha256: Digest


class RunNote(Record):
    run_id: str
    revision: int
    text: str


class ServiceError(Record):
    code: str
    message: str
    target: str | None = None
    next_action: str | None = None


class JobRecord(Record):
    job_id: OpaqueId
    operation: str
    run_id: str
    expected_revision: int
    state: Literal["queued", "running", "cancel_requested", "succeeded", "failed", "cancelled", "interrupted"]
    created_at: str
    updated_at: str
    started_at: str | None
    finished_at: str | None
    cancellation_requested_at: str | None
    arguments: dict[str, Any]
    result: dict[str, Any] | None
    error: ServiceError | None


RECORD_MODELS = {model.__name__: model for model in
                 (SourceRecord, ArtifactRecord, UploadRecord, ArtifactChunk, RunNote, ServiceError, JobRecord)}


def domain_schema() -> dict:
    """Return transport-independent inputs and core public record schemas."""
    from .domain_tools import DOMAIN_SCHEMAS

    return {
        "schema_version": "drawing2cad.domain/1",
        "inputs": DOMAIN_SCHEMAS,
        "records": {name: model.model_json_schema() for name, model in RECORD_MODELS.items()},
        "part_contract": "part_schema",
        "drawing_contract": "drawing_schema",
        "identity": "The adapter supplies AccessContext from a verified server identity.",
    }
