"""Verify durable uploads, immutable downloads, and principal isolation."""

import base64
from concurrent.futures import ThreadPoolExecutor
import hashlib
import io
import os
from pathlib import Path

from pypdf import PdfWriter
import pytest

from drawing2cad_mcp.domain_store import AccessContext, DomainError, DomainStore


ALICE = AccessContext("test:alice")
BOB = AccessContext("test:bob")


@pytest.fixture
def pdf_bytes():
    stream = io.BytesIO()
    writer = PdfWriter()
    writer.add_blank_page(100, 100)
    writer.write(stream)
    return stream.getvalue()


@pytest.fixture
def store(tmp_path):
    return DomainStore(tmp_path / "store", max_chunk_bytes=256)


def begin(store, data, ctx=ALICE):
    return store.upload_begin(ctx, "source.pdf", len(data), hashlib.sha256(data).hexdigest())["upload_id"]


def send(store, upload_id, data, start=0, ctx=ALICE):
    for offset in range(start, len(data), store.max_chunk_bytes):
        store.upload_chunk(ctx, upload_id, offset,
                           base64.b64encode(data[offset:offset + store.max_chunk_bytes]).decode())


def complete(store, data, ctx=ALICE):
    upload_id = begin(store, data, ctx)
    send(store, upload_id, data, ctx=ctx)
    return store.upload_complete(ctx, upload_id)


def expect_code(code, function, *args, **kwargs):
    with pytest.raises(DomainError) as caught:
        function(*args, **kwargs)
    assert caught.value.code == code


def test_upload_restart_and_exact_retry(store, pdf_bytes):
    upload_id = begin(store, pdf_bytes)
    chunk = base64.b64encode(pdf_bytes[:256]).decode()
    assert store.upload_chunk(ALICE, upload_id, 0, chunk)["offset"] == 256
    restarted = DomainStore(store.root, max_chunk_bytes=256)
    assert restarted.upload_get(ALICE, upload_id)["offset"] == 256
    assert restarted.upload_chunk(ALICE, upload_id, 0, chunk)["offset"] == 256
    expect_code("REVISION_CONFLICT", restarted.upload_chunk, ALICE, upload_id, 0,
                base64.b64encode(pdf_bytes[:128]).decode())
    expect_code("REVISION_CONFLICT", restarted.upload_chunk, ALICE, upload_id, 0,
                base64.b64encode(b"x" * 256).decode())
    send(restarted, upload_id, pdf_bytes, start=256)
    result = restarted.upload_complete(ALICE, upload_id)
    assert restarted.upload_complete(ALICE, upload_id) == result
    assert result["status"] == "uploaded"
    assert result["pdf_validation"] == "not_tested"
    assert restarted.source_path(ALICE, result["source_id"]).read_bytes() == pdf_bytes
    assert restarted.source_path(ALICE, result["source_id"]).suffix == ".pdf"
    assert str(store.root) not in repr(result)
    assert "subject" not in result


def test_uncommitted_extra_bytes_are_removed(store, pdf_bytes):
    upload_id = begin(store, pdf_bytes)
    store.upload_chunk(ALICE, upload_id, 0, base64.b64encode(pdf_bytes[:256]).decode())
    path = store.namespace_root(ALICE) / "uploads" / upload_id
    with path.open("ab") as stream:
        stream.write(b"interrupted write")
    send(store, upload_id, pdf_bytes, start=256)
    result = store.upload_complete(ALICE, upload_id)
    assert store.source_path(ALICE, result["source_id"]).read_bytes() == pdf_bytes


def test_finalize_recovers_rename_before_database_commit(store, pdf_bytes):
    upload_id = begin(store, pdf_bytes)
    send(store, upload_id, pdf_bytes)
    pending = store.namespace_root(ALICE) / "uploads" / upload_id
    sources = store.namespace_root(ALICE) / "sources"
    sources.mkdir()
    pending.rename(sources / ("src_" + upload_id[4:] + ".pdf"))
    recovered = DomainStore(store.root).upload_complete(ALICE, upload_id)
    assert recovered["sha256"] == hashlib.sha256(pdf_bytes).hexdigest()


def test_upload_checks_owner_before_mutation(store, pdf_bytes):
    upload_id = begin(store, pdf_bytes)
    for function, args in (
        (store.upload_get, (BOB, upload_id)),
        (store.upload_chunk, (BOB, upload_id, 0, "YQ==")),
        (store.upload_complete, (BOB, upload_id)),
        (store.upload_abort, (BOB, upload_id)),
    ):
        expect_code("NOT_FOUND", function, *args)
    assert store.upload_get(ALICE, upload_id)["offset"] == 0


def test_source_access_is_scoped(store, pdf_bytes):
    source = complete(store, pdf_bytes)
    for method in (store.source_get, store.source_path):
        expect_code("NOT_FOUND", method, BOB, source["source_id"])
    assert store.source_list(BOB)["items"] == []
    assert store.source_list(ALICE)["items"] == [source]


def test_source_delete_removes_bytes_and_is_scoped(store, pdf_bytes):
    source = complete(store, pdf_bytes)
    path = store.source_path(ALICE, source["source_id"])
    expect_code("NOT_FOUND", store.source_delete, BOB, source["source_id"])
    assert store.source_delete(ALICE, source["source_id"]) == source
    assert not path.exists()
    assert store.source_list(ALICE)["items"] == []
    expect_code("NOT_FOUND", store.source_get, ALICE, source["source_id"])
    expect_code("NOT_FOUND", store.source_delete, ALICE, source["source_id"])


def test_hash_and_size_checked_before_source_publication(store, pdf_bytes):
    upload_id = store.upload_begin(ALICE, "source.pdf", len(pdf_bytes), "0" * 64)["upload_id"]
    send(store, upload_id, pdf_bytes)
    expect_code("INTEGRITY_ERROR", store.upload_complete, ALICE, upload_id)
    assert store.source_list(ALICE)["items"] == []
    other = begin(store, pdf_bytes)
    expect_code("INVALID_STATE", store.upload_complete, ALICE, other)
    expect_code("LIMIT_EXCEEDED", store.upload_chunk, ALICE, other, len(pdf_bytes), "YQ==")


@pytest.mark.parametrize("data", [b"not a pdf", b"%PDF-1.7\nmissing trailer", b"%%EOF"])
def test_pdf_envelope_rejected(store, data):
    upload_id = begin(store, data)
    send(store, upload_id, data)
    expect_code("INVALID_PDF", store.upload_complete, ALICE, upload_id)


def test_envelope_check_does_not_claim_structural_validation(store):
    result = complete(store, b"%PDF-1.7\ninvalid structure\n%%EOF")
    assert result["pdf_validation"] == "not_tested"


def test_tampered_source_detected(store, pdf_bytes):
    result = complete(store, pdf_bytes)
    path = store.source_path(ALICE, result["source_id"])
    path.write_bytes(b"x" * len(pdf_bytes))
    expect_code("INTEGRITY_ERROR", store.source_path, ALICE, result["source_id"])


def test_abort_is_idempotent_and_persistent(store, pdf_bytes):
    upload_id = begin(store, pdf_bytes)
    assert store.upload_abort(ALICE, upload_id)["status"] == "aborted"
    assert DomainStore(store.root).upload_abort(ALICE, upload_id)["status"] == "aborted"
    expect_code("INVALID_STATE", store.upload_chunk, ALICE, upload_id, 0, "YQ==")
    expect_code("INVALID_STATE", store.upload_complete, ALICE, upload_id)


@pytest.mark.parametrize("filename", ["../a.pdf", "C:\\a.pdf", "a/b.pdf", ".", "", "bad\x00.pdf", "\ud800.pdf"])
def test_filename_cannot_supply_path(store, filename):
    expect_code("INVALID_ARGUMENT", store.upload_begin, ALICE, filename, 12, "0" * 64)


def test_chunk_limits_offsets_and_encoding(store, pdf_bytes):
    upload_id = begin(store, pdf_bytes)
    expect_code("LIMIT_EXCEEDED", store.upload_chunk, ALICE, upload_id, 0, "A" * 1000)
    expect_code("INVALID_ARGUMENT", store.upload_chunk, ALICE, upload_id, 0, "?")
    expect_code("INVALID_ARGUMENT", store.upload_chunk, ALICE, upload_id, -1, "YQ==")
    expect_code("INVALID_ARGUMENT", store.upload_chunk, ALICE, upload_id, True, "YQ==")
    expect_code("REVISION_CONFLICT", store.upload_chunk, ALICE, upload_id, 20, "YQ==")


def test_artifact_snapshot_download_and_isolation(store):
    path = store.namespace_root(ALICE) / "result.step"
    data = b"STEP result" * 80
    path.write_bytes(data)
    result = store.artifact_register(ALICE, path, "step", "run_1", 3,
                                     "model/step", "result.step")
    path.write_bytes(b"changed build output")
    downloaded = b""
    while True:
        chunk = store.artifact_read(ALICE, result["artifact_id"], len(downloaded), 64)
        downloaded += base64.b64decode(chunk["data_base64"])
        if chunk["eof"]:
            break
    assert downloaded == data
    assert result["sha256"] == hashlib.sha256(data).hexdigest()
    for method in (store.artifact_get, store.artifact_read):
        expect_code("NOT_FOUND", method, BOB, result["artifact_id"])
    assert store.artifact_list(BOB)["items"] == []
    assert store.artifact_list(ALICE, run_id="different")["items"] == []
    assert store.artifact_list(ALICE, run_id="run_1")["items"] == [result]
    assert str(store.root) not in repr(result)
    expect_code("INVALID_ARGUMENT", store.artifact_read, ALICE, result["artifact_id"], len(data) + 1)
    expect_code("INVALID_ARGUMENT", store.artifact_read, ALICE, result["artifact_id"], 0, 257)


def test_artifact_tampering_is_detected(store):
    path = store.namespace_root(ALICE) / "result.svg"
    path.write_bytes(b"<svg/>")
    item = store.artifact_register(ALICE, path, "drawing", "run_1", 1, "image/svg+xml", "result.svg")
    (store.namespace_root(ALICE) / "artifacts" / item["artifact_id"]).write_bytes(b"xxxxxx")
    expect_code("INTEGRITY_ERROR", store.artifact_read, ALICE, item["artifact_id"])


def test_cross_namespace_registration_is_blocked(store, tmp_path):
    for path in (tmp_path / "outside.step", store.namespace_root(BOB) / "other.step"):
        path.write_bytes(b"data")
        expect_code("UNSAFE_PATH", store.artifact_register, ALICE, path,
                    "step", "run_1", 1, "model/step", "result.step")


def test_links_are_blocked(store, tmp_path):
    outside = tmp_path / "outside"
    outside.write_bytes(b"secret")
    linked = store.namespace_root(ALICE) / "linked.step"
    try:
        linked.symlink_to(outside)
    except OSError:
        pytest.skip("The host does not permit symbolic links.")
    expect_code("UNSAFE_PATH", store.artifact_register, ALICE, linked,
                "step", "run_1", 1, "model/step", "result.step")


def test_hard_links_are_blocked(store, tmp_path):
    outside = tmp_path / "outside"
    outside.write_bytes(b"secret")
    linked = store.namespace_root(ALICE) / "linked.step"
    os.link(outside, linked)
    expect_code("UNSAFE_PATH", store.artifact_register, ALICE, linked,
                "step", "run_1", 1, "model/step", "result.step")


def test_bounded_pagination_survives_restart(store, pdf_bytes):
    for _ in range(4):
        complete(store, pdf_bytes)
    first = store.source_list(ALICE, limit=2)
    second = DomainStore(store.root).source_list(ALICE, limit=2, cursor=first["next_cursor"])
    assert len(first["items"]) == len(second["items"]) == 2
    assert second["next_cursor"] is None
    assert len({r["source_id"] for r in first["items"] + second["items"]}) == 4
    expect_code("INVALID_ARGUMENT", store.source_list, ALICE, limit=101)
    expect_code("INVALID_ARGUMENT", store.source_list, ALICE, cursor="../../metadata.sqlite3")


def test_notes_have_independent_revision_and_ownership(store):
    first = store.notes_update(ALICE, "run_1", 0, "Initial note")
    assert first["revision"] == 1
    expect_code("NOT_FOUND", store.notes_read, BOB, "run_1")
    expect_code("REVISION_CONFLICT", store.notes_update, ALICE, "run_1", 0, "Stale edit")
    next_note = DomainStore(store.root).notes_update(ALICE, "run_1", 1, "Updated note")
    assert next_note["revision"] == 2
    assert store.notes_read(ALICE, "run_1") == next_note
    expect_code("LIMIT_EXCEEDED", store.notes_update, ALICE, "run_1", 2, "x" * 65537)


def test_concurrent_note_updates_cannot_lose_revision(store):
    store.notes_update(ALICE, "run_1", 0, "Initial")
    def update(value):
        try:
            return DomainStore(store.root).notes_update(ALICE, "run_1", 1, value)["revision"]
        except DomainError as error:
            return error.code
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(update, ["first", "second"]))
    assert sorted(results, key=str) == [2, "REVISION_CONFLICT"]


@pytest.mark.parametrize("subject", ["", " ", "a\x00b", "x" * 257, None, "\ud800"])
def test_access_context_rejects_invalid_subject(subject):
    expect_code("INVALID_IDENTITY", AccessContext, subject)


def test_invalid_unicode_note_does_not_change_revision(store):
    store.notes_update(ALICE, "run_1", 0, "Initial note")
    expect_code("INVALID_ARGUMENT", store.notes_update, ALICE, "run_1", 1, "\ud800")
    assert store.notes_read(ALICE, "run_1")["revision"] == 1


@pytest.mark.parametrize("filename", ["metadata.sqlite3", "metadata.sqlite3-journal"])
def test_metadata_links_are_rejected_before_sqlite_access(tmp_path, filename):
    root = tmp_path / "store"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.write_bytes(b"must remain unchanged")
    os.link(outside, root / filename)
    expect_code("UNSAFE_PATH", DomainStore, root)
    assert outside.read_bytes() == b"must remain unchanged"
