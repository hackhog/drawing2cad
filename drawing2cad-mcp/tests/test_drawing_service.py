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
from drawing2cad_mcp.vector.export import SCHEMA_VERSION
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


def test_cropped_pages_fail_explicitly(service, tmp_path):
    source = make_pdf(tmp_path / "transformed.pdf", cropbox=True)
    with pytest.raises(PdfError, match="full, zero-origin MediaBox"):
        service.extract_drawing(source)


@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
def test_rotated_page_coordinates_match_render_contract(service, tmp_path, rotation):
    original = make_vector_pdf(tmp_path / "original.pdf")
    baseline = service.extract_drawing(original, include_strokes=True)
    writer = PdfWriter(original)
    writer.pages[0].rotate(rotation)
    source = tmp_path / "rotated.pdf"
    writer.write(source)
    before = sha256(source.read_bytes()).hexdigest()
    result = service.extract_drawing(source, include_strokes=True)
    assert result["summary"] == baseline["summary"]
    assert result["source"]["sha256"] == before == sha256(source.read_bytes()).hexdigest()
    assert result["rotation_degrees"] == rotation
    width, height = baseline["sheet_size_mm"]
    expected_size = [height, width] if rotation in (90, 270) else [width, height]
    assert result["sheet_size_mm"] == expected_size
    for original_stroke, stroke in zip(baseline["strokes"], result["strokes"]):
        for key in ("p0", "p1"):
            x, y = original_stroke[key]
            expected = {0: (x, y), 90: (height - y, x), 180: (width - x, height - y),
                        270: (y, width - x)}[rotation]
            assert stroke[key] == pytest.approx(expected, abs=0.002)
    normalized = result["views"][0]["bbox_normalized"]
    box = result["views"][0]["bbox"]
    assert normalized == pytest.approx([box[0] / expected_size[0], box[1] / expected_size[1],
                                        box[2] / expected_size[0], box[3] / expected_size[1]], abs=1e-5)


def test_selected_page_is_analyzed(service, tmp_path):
    original = make_vector_pdf(tmp_path / "original.pdf")
    writer = PdfWriter()
    writer.add_blank_page(width=1190.55, height=841.89)
    writer.append(original)
    writer.pages[1].rotate(90)
    source = tmp_path / "two-pages.pdf"
    writer.write(source)
    assert service.extract_drawing(source)["summary"]["strokes"] == 0
    result = service.extract_drawing(source, page=2)
    assert result["summary"]["strokes"] == 4
    assert result["provenance"]["page"] == 2
    assert result["rotation_degrees"] == 90
    with pytest.raises(PdfError, match="between"):
        service.extract_drawing(source, page=3)


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


def test_worker_failure_is_a_pdf_error_and_cleans_snapshot(service, tmp_path, monkeypatch, caplog):
    source = make_vector_pdf(tmp_path / "failure.pdf")
    monkeypatch.setattr("drawing2cad_mcp.pdf.subprocess.run", lambda command, **kwargs:
                        subprocess.CompletedProcess(command, 1, stderr=b"ValueError: Cannot read /private/var/x/customer.pdf"))
    with pytest.raises(PdfError) as error:
        service.extract_drawing(source)
    assert str(error.value) == "Vector analysis failed: ValueError."  # stderr can name host paths
    assert "customer.pdf" in caplog.text
    assert not list(service.output_root.iterdir())


@pytest.mark.parametrize("payload", [
    None, "not JSON", {"schema_version": SCHEMA_VERSION, "strokes": [{}], "views": []},
    {"schema_version": SCHEMA_VERSION, "strokes": [], "views": [{}]},
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
