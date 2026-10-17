"""Validate the integrated vector service at the permitted PDF boundary."""

from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
import json
from pathlib import Path
import subprocess

from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, NameObject, NumberObject
import pytest

from drawing2cad_mcp.pdf import PdfError, PdfService
from test_pdf import make_pdf


def make_vector_pdf(path):
    writer = PdfWriter()
    page = writer.add_blank_page(width=1190.55, height=841.89)
    content = DecodedStreamObject()
    content.set_data(b"0 0 0 RG 0.5 w 100 300 200 100 re S")
    page[NameObject("/Contents")] = writer._add_object(content)
    writer.write(path)
    return path


@pytest.fixture
def service(tmp_path):
    return PdfService((tmp_path,), tmp_path / "out", None)


def test_compact_and_filtered_results_share_source_and_leave_no_exports(service, tmp_path):
    source = make_vector_pdf(tmp_path / "vector.pdf")
    compact = service.extract_drawing(source)
    full = service.extract_drawing(source, include_strokes=True)
    filtered = service.extract_drawing(source, include_strokes=True, stroke_kinds=["contour"])
    assert compact["source"] == full["source"] == filtered["source"]
    assert compact["source"]["sha256"] == sha256(source.read_bytes()).hexdigest()
    assert full["summary"]["strokes"] == len(full["strokes"]) == 4
    assert len(full["views"]) == 1
    assert "strokes" not in compact
    assert compact["views"][0]["stroke_count"] == 4
    assert all(stroke["kind"] == "contour" for stroke in filtered["strokes"])
    assert compact["provenance"]["scale_applied"] is False
    assert not list(service.output_root.iterdir())


@pytest.mark.parametrize("options", [{"rotation": 90}, {"cropbox": True}])
def test_transformed_pages_fail_explicitly(service, tmp_path, options):
    source = make_pdf(tmp_path / "transformed.pdf", **options)
    with pytest.raises(PdfError, match="unrotated page"):
        service.extract_drawing(source)


def test_user_unit_is_rejected(service, tmp_path):
    writer = PdfWriter()
    page = writer.add_blank_page(width=300, height=300)
    page[NameObject("/UserUnit")] = NumberObject(2)
    source = tmp_path / "scaled.pdf"
    writer.write(source)
    with pytest.raises(PdfError, match="UserUnit"):
        service.extract_drawing(source)


def test_analysis_worker_timeout_cleans_snapshot(service, tmp_path, monkeypatch):
    source = make_vector_pdf(tmp_path / "timeout.pdf")

    def timeout(command, **kwargs):
        assert kwargs["timeout"] == service.timeout_seconds
        raise subprocess.TimeoutExpired(command, kwargs["timeout"])

    monkeypatch.setattr("drawing2cad_mcp.pdf.subprocess.run", timeout)
    with pytest.raises(PdfError, match="timeout"):
        service.extract_drawing(source)
    assert not list(service.output_root.iterdir())


def test_worker_failure_is_a_pdf_error_and_cleans_snapshot(service, tmp_path, monkeypatch):
    source = make_vector_pdf(tmp_path / "failure.pdf")
    monkeypatch.setattr("drawing2cad_mcp.pdf.subprocess.run", lambda command, **kwargs:
                        subprocess.CompletedProcess(command, 1, stderr=b"invalid glyph"))
    with pytest.raises(PdfError, match="invalid glyph"):
        service.extract_drawing(source)
    assert not list(service.output_root.iterdir())


@pytest.mark.parametrize("payload", [
    None, "not JSON", {"schema_version": 2, "strokes": [{}], "views": []},
    {"schema_version": 2, "strokes": [], "views": [{}]},
    {"schema_version": 999, "strokes": [], "views": []},
])
def test_invalid_worker_result_fails_at_service_boundary(service, tmp_path, monkeypatch, payload):
    source = make_vector_pdf(tmp_path / "invalid-result.pdf")

    def produce_result(command, **kwargs):
        if payload is not None:
            content = payload if isinstance(payload, str) else json.dumps(payload)
            Path(command[-1]).write_text(content, encoding="utf-8")
        return subprocess.CompletedProcess(command, 0, stderr=b"")

    monkeypatch.setattr("drawing2cad_mcp.pdf.subprocess.run", produce_result)
    with pytest.raises(PdfError, match="result"):
        service.extract_drawing(source)
    assert not list(service.output_root.iterdir())


def test_oversized_worker_result_is_rejected_before_loading(service, tmp_path, monkeypatch):
    source = make_vector_pdf(tmp_path / "oversized-result.pdf")

    def produce_result(command, **kwargs):
        with Path(command[-1]).open("wb") as result:
            result.truncate(64 * 1024 * 1024 + 1)
        return subprocess.CompletedProcess(command, 0, stderr=b"")

    monkeypatch.setattr("drawing2cad_mcp.pdf.subprocess.run", produce_result)
    with pytest.raises(PdfError, match="64 MiB"):
        service.extract_drawing(source)
    assert not list(service.output_root.iterdir())


def test_parallel_requests_use_independent_snapshots(service, tmp_path):
    sources = [make_vector_pdf(tmp_path / f"parallel-{index}.pdf") for index in range(2)]
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(service.extract_drawing, sources))
    assert results[0]["source"]["path"] != results[1]["source"]["path"]
    assert results[0]["summary"] == results[1]["summary"]
    assert not list(service.output_root.iterdir())


@pytest.mark.parametrize("options", [
    {"include_strokes": 1}, {"stroke_kinds": ["contour"]},
    {"include_strokes": True, "stroke_kinds": ["bad"]},
    {"include_strokes": True, "stroke_kinds": ["contour", "contour"]},
])
def test_service_rejects_invalid_filter_arguments(service, tmp_path, options):
    with pytest.raises(PdfError):
        service.extract_drawing(tmp_path / "unused.pdf", **options)
