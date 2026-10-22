"""Synthetic PDF tests; no project construction drawings are used."""

from hashlib import sha256
import os
from pathlib import Path
import shutil
import subprocess

from PIL import Image
from pypdf import PdfWriter
from pypdf.generic import ArrayObject, DecodedStreamObject, DictionaryObject, NameObject, NumberObject
import pytest

from drawing2cad_mcp.pdf import PdfError, PdfProcessError, PdfService


def make_pdf(
    path: Path, *, rotation: int = 0,
    cropbox: bool | tuple[int, int, int, int] = False, encrypted=False,
) -> Path:
    writer = PdfWriter()
    font = writer._add_object(DictionaryObject({
        NameObject("/Type"): NameObject("/Font"),
        NameObject("/Subtype"): NameObject("/Type1"),
        NameObject("/BaseFont"): NameObject("/Helvetica"),
    }))
    for index in range(2):
        page = writer.add_blank_page(width=144, height=216)
        resources = DictionaryObject({NameObject("/Font"): DictionaryObject({NameObject("/F1"): font})})
        if index == 0:
            stream = DecodedStreamObject()
            stream.set_data(b"1 0 0 rg 0 0 72 72 re f\nBT /F1 12 Tf 20 120 Td (Dimension 42 mm) Tj ET")
        else:
            image = DecodedStreamObject()
            image.set_data(bytes([0, 0, 255]))
            image.update({NameObject("/Type"): NameObject("/XObject"),
                          NameObject("/Subtype"): NameObject("/Image"),
                          NameObject("/Width"): NumberObject(1),
                          NameObject("/Height"): NumberObject(1),
                          NameObject("/ColorSpace"): NameObject("/DeviceRGB"),
                          NameObject("/BitsPerComponent"): NumberObject(8)})
            resources[NameObject("/XObject")] = DictionaryObject({NameObject("/Im0"): writer._add_object(image)})
            stream = DecodedStreamObject()
            stream.set_data(b"q 144 0 0 216 0 0 cm /Im0 Do Q")
        page[NameObject("/Resources")] = resources
        page[NameObject("/Contents")] = writer._add_object(stream)
        if rotation:
            page.rotate(rotation)
        if cropbox:
            values = (18, 18, 126, 198) if cropbox is True else cropbox
            page[NameObject("/CropBox")] = ArrayObject([NumberObject(v) for v in values])
    if encrypted:
        writer.encrypt("test-password")
    with path.open("wb") as handle:
        writer.write(handle)
    return path


@pytest.fixture
def source(tmp_path):
    return make_pdf(tmp_path / "drawing.pdf")


@pytest.fixture
def poppler():
    configured = os.environ.get("DRAWING2CAD_PDFTOPPM")
    found = shutil.which(configured or "pdftoppm")
    if not found:
        pytest.skip("Poppler is required for rendering integration tests.")
    return found


@pytest.fixture
def service(tmp_path):
    return PdfService((tmp_path,), tmp_path / "artifacts", None)


def test_info_and_text_preserve_source_identity(service, source):
    info = service.info(source)
    assert info["page_count"] == 2
    assert info["source"]["sha256"] == sha256(source.read_bytes()).hexdigest()
    assert info["pages"][0]["width_points"] == 144
    result = service.read_text(source)
    assert result["status"] == "mixed_native_text"
    assert "Dimension 42 mm" in result["pages"][0]["text"]
    assert result["pages"][1]["status"] == "native_text_missing"
    assert result["ocr_performed"] is False
    assert result["source"] == info["source"]


def test_text_selection_and_global_limit(service, source):
    result = service.read_text(source, [1], max_chars=5)
    assert result["returned_characters"] == 5
    assert result["truncated"] is True
    assert result["pages"][0]["text"] == "Dimen"
    assert service.read_text(source, [2])["status"] == "native_text_missing"


def test_rotated_crop_uses_displayed_top_left(tmp_path, poppler):
    source = make_pdf(tmp_path / "rotated.pdf", rotation=90)
    service = PdfService((tmp_path,), tmp_path / "out", poppler)
    result = service.crop_region(source, 1, [0, 0, 1 / 3, 0.5], dpi=72)
    assert result["provenance"]["full_page_pixels"] == [216, 144]
    assert result["provenance"]["pixel_bbox"] == [0, 0, 72, 72]
    assert result["artifact"]["width_pixels"] == 72
    with Image.open(result["artifact"]["path"]) as image:
        assert image.getpixel((36, 36)) == (255, 0, 0)
    assert result["artifact"]["sha256"] == sha256(Path(result["artifact"]["path"]).read_bytes()).hexdigest()
    assert list((tmp_path / "out").glob(".pdf-render-*")) == []


def test_cropbox_offset_and_rotation(tmp_path, poppler):
    source = make_pdf(tmp_path / "cropped.pdf", rotation=90, cropbox=True)
    service = PdfService((tmp_path,), tmp_path / "out", poppler)
    result = service.render_page(source, page=1, dpi=72)
    assert result["artifact"]["width_pixels"] == 180
    assert result["artifact"]["height_pixels"] == 108
    with Image.open(result["artifact"]["path"]) as image:
        assert image.getpixel((25, 25)) == (255, 0, 0)
        assert image.getpixel((70, 70)) == (255, 255, 255)


def test_user_unit_is_respected_at_requested_dpi(tmp_path, poppler):
    writer = PdfWriter()
    page = writer.add_blank_page(width=144, height=216)
    page[NameObject("/UserUnit")] = NumberObject(2)
    source = tmp_path / "user-unit.pdf"
    writer.write(source)
    service = PdfService((tmp_path,), tmp_path / "out", poppler)
    result = service.render_page(source, dpi=72)
    assert result["artifact"]["width_pixels"] == 288
    assert result["artifact"]["height_pixels"] == 432
    assert result["provenance"]["user_unit"] == 2


@pytest.mark.parametrize("rotation", [0, 90])
def test_oversized_cropbox_is_clipped_without_distorting_pixels(tmp_path, poppler, rotation):
    source = make_pdf(tmp_path / "oversized-cropbox.pdf", rotation=rotation,
                      cropbox=(-18, -18, 162, 234))
    service = PdfService((tmp_path,), tmp_path / "out", poppler, max_pixels=32_000)
    geometry = service.info(source)["pages"][0]
    expected_size = (144, 216) if rotation == 0 else (216, 144)
    assert (geometry["width_points"], geometry["height_points"]) == expected_size
    assert geometry["cropbox_points"] == [-18, -18, 162, 234]
    assert geometry["mediabox_points"] == [0, 0, 144, 216]
    assert geometry["effective_cropbox_points"] == [0, 0, 144, 216]
    assert geometry["cropbox_clipped_to_mediabox"] is True
    rendered = service.render_page(source, dpi=72)
    assert rendered["provenance"]["effective_cropbox_points"] == [0, 0, 144, 216]
    with Image.open(rendered["artifact"]["path"]) as image:
        assert image.size == expected_size
        # The drawn 72 x 72 pt square remains square at 72 DPI, with no axis
        # stretch caused by the oversized, nonsquare requested page margin.
        origin_y = 0 if rotation == 90 else image.height - 72
        assert image.getpixel((36, origin_y + 36)) == (255, 0, 0)
        assert image.getpixel((73, origin_y + 36)) == (255, 255, 255)
        outside_y = 73 if rotation == 90 else image.height - 73
        assert image.getpixel((36, outside_y)) == (255, 255, 255)
    bbox = [0, 2 / 3, 0.5, 1] if rotation == 0 else [0, 0, 1 / 3, 0.5]
    crop = service.crop_region(source, 1, bbox, dpi=72)
    assert crop["artifact"]["width_pixels"] == 72
    assert crop["artifact"]["height_pixels"] == 72
    with Image.open(crop["artifact"]["path"]) as image:
        assert image.getpixel((36, 36)) == (255, 0, 0)


def test_multiple_pages_and_unique_atomic_artifacts(tmp_path, source, poppler):
    service = PdfService((tmp_path,), tmp_path / "out", poppler)
    first = service.render_page(source, page=2, dpi=72)
    second = service.render_page(source, page=2, dpi=72)
    assert first["artifact"]["path"] != second["artifact"]["path"]
    assert first["artifact"]["sha256"] == second["artifact"]["sha256"]
    assert first["provenance"]["page"] == 2
    with Image.open(first["artifact"]["path"]) as image:
        assert image.getpixel((72, 108)) == (0, 0, 255)
    assert len(list((tmp_path / "out").iterdir())) == 2


def test_path_escape_and_wrong_extension(tmp_path):
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    outside = make_pdf(tmp_path / "outside.pdf")
    service = PdfService((allowed,), tmp_path / "out", None)
    with pytest.raises(PdfError, match="outside"):
        service.info(outside)
    with pytest.raises(PdfError, match="outside"):
        service.info(allowed / ".." / "outside.pdf")
    text = allowed / "fake.txt"
    text.write_bytes(outside.read_bytes())
    with pytest.raises(PdfError, match="extension"):
        service.info(text)


def test_symlink_cannot_escape_allowed_root(tmp_path):
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    outside = make_pdf(tmp_path / "outside.pdf")
    link = allowed / "linked.pdf"
    try:
        link.symlink_to(outside)
    except OSError:
        pytest.skip("This OS account cannot create symlinks.")
    service = PdfService((allowed,), tmp_path / "out", None)
    with pytest.raises(PdfError, match="outside"):
        service.info(link)


@pytest.mark.skipif(os.name != "nt", reason="Windows junction behavior")
def test_windows_junction_cannot_escape_allowed_root(tmp_path):
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    make_pdf(outside / "drawing.pdf")
    link = allowed / "junction"
    created = subprocess.run(
        ["cmd.exe", "/d", "/c", "mklink", "/J", str(link), str(outside)],
        capture_output=True, timeout=10, shell=False, creationflags=subprocess.CREATE_NO_WINDOW,
    )
    if created.returncode:
        pytest.skip("Windows could not create the temporary directory junction.")
    try:
        service = PdfService((allowed,), tmp_path / "out", None)
        with pytest.raises(PdfError, match="outside"):
            service.info(link / "drawing.pdf")
    finally:
        # Remove only the junction itself; the test target belongs to tmp_path.
        link.rmdir()


@pytest.mark.parametrize("pages", [[0], [3], [True], [1.0], [], [1, 1], "1"])
def test_invalid_page_selection(service, source, pages):
    with pytest.raises(PdfError):
        service.read_text(source, pages=pages)


@pytest.mark.parametrize("dpi", [0, 35, 601, 150.5, True, float("nan")])
def test_invalid_dpi(service, source, dpi):
    with pytest.raises(PdfError, match="DPI"):
        service.render_page(source, dpi=dpi)


@pytest.mark.parametrize("bbox", [[0, 0, 0, 1], [-0.1, 0, 1, 1], [0, 0, 1, 2],
                                  [0, 0, float("nan"), 1], [0, 0, float("inf"), 1],
                                  [0, 0, True, 1], [0, 1], "0,0,1,1"])
def test_invalid_bbox(service, source, bbox):
    with pytest.raises(PdfError, match="bbox"):
        service.crop_region(source, 1, bbox)


def test_encrypted_and_oversized_pdf_rejected(tmp_path, source):
    service = PdfService((tmp_path,), tmp_path / "out", None)
    with pytest.raises(PdfError, match="Encrypted"):
        service.info(make_pdf(tmp_path / "encrypted.pdf", encrypted=True))
    tiny = PdfService((tmp_path,), tmp_path / "out", None, max_pdf_bytes=10)
    with pytest.raises(PdfError, match="byte limit"):
        tiny.info(source)


def test_malformed_pdf_is_reported_as_pdf_error(tmp_path, service):
    source = tmp_path / "invalid.pdf"
    source.write_text("not a PDF", encoding="utf-8")
    with pytest.raises(PdfError, match="Cannot read PDF"):
        service.info(source)


def test_pixel_limit_checked_before_start(tmp_path, source, monkeypatch):
    service = PdfService((tmp_path,), tmp_path / "out", None, max_pixels=100)
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: pytest.fail("Renderer must not start"))
    with pytest.raises(PdfError, match="pixel limit"):
        service.render_page(source)


def test_missing_poppler(tmp_path, source):
    service = PdfService((tmp_path,), tmp_path / "out", str(tmp_path / "absent.exe"))
    with pytest.raises(PdfError, match="not found"):
        service.render_page(source)


def test_timeout_cleanup(tmp_path, source, monkeypatch):
    monkeypatch.setattr(shutil, "which", lambda path: "pdftoppm")
    def timeout(args, **kwargs):
        assert isinstance(args, list)
        assert kwargs["shell"] is False
        assert kwargs["timeout"] == 0.01
        raise subprocess.TimeoutExpired(args, kwargs["timeout"])
    monkeypatch.setattr(subprocess, "run", timeout)
    service = PdfService((tmp_path,), tmp_path / "out", None, timeout_seconds=0.01)
    with pytest.raises(PdfError, match="exceeded"):
        service.render_page(source)
    assert list((tmp_path / "out").iterdir()) == []


def test_render_error_cleanup(tmp_path, source, monkeypatch):
    monkeypatch.setattr(shutil, "which", lambda path: "pdftoppm")
    monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 1, b"", b"bad PDF"))
    service = PdfService((tmp_path,), tmp_path / "out", None)
    with pytest.raises(PdfProcessError, match="bad PDF"):
        service.render_page(source)
    assert list((tmp_path / "out").iterdir()) == []


def test_vector_worker_output_is_a_process_error(tmp_path, source, monkeypatch):
    monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 1, b"", b"worker trace"))
    service = PdfService((tmp_path,), tmp_path / "out", None)
    with pytest.raises(PdfProcessError, match="worker trace"):
        service.extract_drawing(source)
