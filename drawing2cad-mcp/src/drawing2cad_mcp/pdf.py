"""Bounded PDF inspection and raster preparation, without OCR or CAD mutation.

Page numbers are one-based. Crops use normalized coordinates in the displayed,
rotated PDF CropBox clipped to its MediaBox: [left, top, right, bottom], with the
origin at the top left. Metadata reports both original boxes and their effective
intersection; physical page dimensions refer to that displayed intersection.
"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from io import BytesIO
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from typing import Any
from uuid import uuid4

from PIL import Image, UnidentifiedImageError
from pypdf import PdfReader

from .vector.export import SCHEMA_VERSION
from .vector.model import Kind


class PdfError(ValueError):
    """An invalid PDF request or a failed PDF preparation operation."""


@dataclass(frozen=True)
class _Source:
    path: Path
    data: bytes
    reader: PdfReader

    @property
    def metadata(self) -> dict[str, Any]:
        return {
            "path": str(self.path),
            "sha256": sha256(self.data).hexdigest(),
            "size_bytes": len(self.data),
        }


class PdfService:
    """Synchronous backend; MCP callers should run methods in a worker thread."""

    def __init__(
        self,
        allowed_roots: tuple[Path, ...],
        output_root: Path,
        pdftoppm: str | None,
        timeout_seconds: float = 60,
        max_pdf_bytes: int = 104_857_600,
        max_pixels: int = 40_000_000,
    ) -> None:
        if not allowed_roots:
            raise PdfError("At least one allowed PDF root is required.")
        if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
            raise PdfError("timeout_seconds must be finite and positive.")
        if max_pdf_bytes <= 0 or max_pixels <= 0:
            raise PdfError("PDF byte and pixel limits must be positive.")
        self.allowed_roots = tuple(Path(p).expanduser().resolve() for p in allowed_roots)
        self.output_root = Path(output_root).expanduser().resolve()
        self.pdftoppm = pdftoppm
        self.timeout_seconds = timeout_seconds
        self.max_pdf_bytes = max_pdf_bytes
        self.max_pixels = max_pixels

    def _load(self, path: str | Path) -> _Source:
        source = Path(path).expanduser().resolve()
        if not any(source.is_relative_to(root) for root in self.allowed_roots):
            raise PdfError("PDF path is outside the configured allowed roots.")
        if source.suffix.lower() != ".pdf":
            raise PdfError("Source must have a .pdf extension.")
        if not source.is_file():
            raise PdfError("PDF source is not a regular file.")
        if source.stat().st_size > self.max_pdf_bytes:
            raise PdfError("PDF source exceeds the configured byte limit.")
        # A bounded snapshot ensures extraction, rendering and source SHA agree.
        with source.open("rb") as handle:
            data = handle.read(self.max_pdf_bytes + 1)
        if len(data) > self.max_pdf_bytes:
            raise PdfError("PDF source exceeds the configured byte limit.")
        try:
            reader = PdfReader(BytesIO(data))
            if reader.is_encrypted:
                raise PdfError("Encrypted PDFs are unsupported; provide an unencrypted PDF.")
            if not reader.pages:
                raise PdfError("PDF contains no pages.")
        except PdfError:
            raise
        except Exception as exc:
            raise PdfError(f"Cannot read PDF: {type(exc).__name__}.") from exc
        return _Source(source, data, reader)

    @staticmethod
    def _page_number(source: _Source, page: int) -> int:
        if isinstance(page, bool) or not isinstance(page, int):
            raise PdfError("Page must be a one-based integer.")
        if not 1 <= page <= len(source.reader.pages):
            raise PdfError(f"Page must be between 1 and {len(source.reader.pages)}.")
        return page

    @staticmethod
    def _dpi(dpi: int) -> int:
        if isinstance(dpi, bool) or not isinstance(dpi, int) or not 36 <= dpi <= 600:
            raise PdfError("DPI must be an integer between 36 and 600.")
        return dpi

    @staticmethod
    def _geometry(source: _Source, page: int) -> dict[str, Any]:
        obj = source.reader.pages[page - 1]
        coordinates = [float(v) for v in obj.cropbox]
        media_coordinates = [float(v) for v in obj.mediabox]
        unit = float(obj.user_unit)
        rotation = int(obj.rotation) % 360
        if (
            not all(math.isfinite(v) for v in coordinates + media_coordinates)
            or not math.isfinite(unit)
            or unit <= 0
            or rotation not in (0, 90, 180, 270)
        ):
            raise PdfError("PDF page has unsupported or invalid dimensions/rotation.")
        # Viewers, including pdftoppm -cropbox, clip the requested CropBox to
        # the physical MediaBox. Scaling the unbounded request would stretch
        # the visible page and invalidate normalized crop coordinates.
        effective = [max(coordinates[0], media_coordinates[0]),
                     max(coordinates[1], media_coordinates[1]),
                     min(coordinates[2], media_coordinates[2]),
                     min(coordinates[3], media_coordinates[3])]
        width = (effective[2] - effective[0]) * unit
        height = (effective[3] - effective[1]) * unit
        if not math.isfinite(width) or not math.isfinite(height) or width <= 0 or height <= 0:
            raise PdfError("PDF page has invalid dimensions.")
        if rotation in (90, 270):
            width, height = height, width
        return {
            "page": page,
            "width_points": width,
            "height_points": height,
            "rotation_degrees": rotation,
            "cropbox_points": coordinates,
            "mediabox_points": media_coordinates,
            "effective_cropbox_points": effective,
            "cropbox_clipped_to_mediabox": effective != coordinates,
            "user_unit": unit,
        }

    def info(self, path: str | Path) -> dict[str, Any]:
        source = self._load(path)
        return {
            "source": source.metadata,
            "page_count": len(source.reader.pages),
            "encrypted": False,
            "metadata": {str(k): str(v) for k, v in (source.reader.metadata or {}).items()},
            "pages": [self._geometry(source, p) for p in range(1, len(source.reader.pages) + 1)],
        }

    def read_text(
        self, path: str | Path, pages: list[int] | None = None, max_chars: int = 50_000
    ) -> dict[str, Any]:
        if isinstance(max_chars, bool) or not isinstance(max_chars, int) or not 1 <= max_chars <= 1_000_000:
            raise PdfError("max_chars must be an integer between 1 and 1000000.")
        source = self._load(path)
        selected = list(range(1, len(source.reader.pages) + 1)) if pages is None else pages
        if not isinstance(selected, list) or not selected:
            raise PdfError("pages must be a nonempty list of one-based page numbers.")
        for page in selected:
            self._page_number(source, page)
        if len(set(selected)) != len(selected):
            raise PdfError("Duplicate page numbers are unsupported.")
        records = []
        remaining = max_chars
        for page in selected:
            try:
                text = source.reader.pages[page - 1].extract_text() or ""
            except Exception as exc:
                raise PdfError(f"Native text extraction failed on page {page}: {type(exc).__name__}.") from exc
            returned = text[:remaining]
            remaining -= len(returned)
            records.append({
                "page": page,
                "text": returned,
                "status": "native_text_available" if text.strip() else "native_text_missing",
                "extracted_characters": len(text),
                "truncated": len(returned) < len(text),
            })
        found = sum(row["status"] == "native_text_available" for row in records)
        return {
            "source": source.metadata,
            "page_count": len(source.reader.pages),
            "pages": records,
            "status": "native_text_missing" if not found else (
                "native_text_available" if found == len(records) else "mixed_native_text"
            ),
            "ocr_performed": False,
            "max_chars": max_chars,
            "returned_characters": max_chars - remaining,
            "truncated": any(row["truncated"] for row in records),
        }

    def _output_directory(self) -> Path:
        self.output_root.mkdir(parents=True, exist_ok=True)
        # Do not follow a replaced output directory into another destination.
        if self.output_root.resolve() != self.output_root:
            raise PdfError("Configured output directory changed its resolved location.")
        return self.output_root

    def _render(self, source: _Source, page: int, dpi: int) -> tuple[Image.Image, dict[str, Any]]:
        self._page_number(source, page)
        self._dpi(dpi)
        geometry = self._geometry(source, page)
        raw_width = geometry["width_points"] / 72 * dpi
        raw_height = geometry["height_points"] / 72 * dpi
        if not math.isfinite(raw_width) or not math.isfinite(raw_height):
            raise PdfError("Rendered page would exceed the configured pixel limit.")
        width = math.ceil(raw_width)
        height = math.ceil(raw_height)
        if width * height > self.max_pixels:
            raise PdfError(f"Rendered page would exceed the {self.max_pixels} pixel limit.")
        executable = shutil.which(self.pdftoppm or "pdftoppm")
        if not executable:
            raise PdfError("Poppler pdftoppm was not found; configure its executable path.")
        with tempfile.TemporaryDirectory(prefix=".pdf-render-", dir=self._output_directory()) as temp:
            folder = Path(temp)
            snapshot = folder / "source.pdf"
            snapshot.write_bytes(source.data)
            prefix = folder / "page"
            # Explicit physical dimensions also handle PDF /UserUnit, which
            # pdftoppm versions can ignore when only -r is supplied. Poppler's
            # rotation flag makes these targets describe the displayed image.
            args = [executable, "-f", str(page), "-l", str(page), "-singlefile", "-cropbox",
                    "-r", str(dpi), "-scale-to-x", str(width), "-scale-to-y", str(height),
                    "-scale-dimension-before-rotation",
                    "-png", str(snapshot), str(prefix)]
            try:
                result = subprocess.run(
                    args, shell=False, capture_output=True, timeout=self.timeout_seconds,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0,
                )
            except subprocess.TimeoutExpired as exc:
                raise PdfError(f"PDF rendering exceeded {self.timeout_seconds:g} seconds.") from exc
            except OSError as exc:
                raise PdfError(f"Cannot start pdftoppm: {type(exc).__name__}.") from exc
            if result.returncode:
                diagnostic = result.stderr.decode("utf-8", errors="replace")[-1500:]
                raise PdfError(f"pdftoppm failed (exit {result.returncode}): {diagnostic}")
            try:
                with Image.open(prefix.with_suffix(".png")) as rendered:
                    if rendered.width * rendered.height > self.max_pixels:
                        raise PdfError("Rendered image exceeds the configured pixel limit.")
                    if rendered.size != (width, height):
                        raise PdfError(
                            f"Renderer dimensions {rendered.size} differ from expected CropBox {(width, height)}."
                        )
                    # Load before the temporary file is removed and preserve color.
                    image = rendered.convert("RGB")
            except PdfError:
                raise
            except (OSError, UnidentifiedImageError, Image.DecompressionBombError) as exc:
                raise PdfError(f"pdftoppm did not produce a readable PNG: {type(exc).__name__}.") from exc
        return image, geometry

    def _artifact(self, image: Image.Image, prefix: str) -> dict[str, Any]:
        output = self._output_directory()
        final = output / f"{prefix}-{uuid4().hex}.png"
        fd, temporary = tempfile.mkstemp(prefix=".png-", suffix=".tmp", dir=output)
        try:
            with os.fdopen(fd, "wb") as handle:
                image.save(handle, format="PNG")
                handle.flush()
                os.fsync(handle.fileno())
            digest = sha256(Path(temporary).read_bytes()).hexdigest()
            os.replace(temporary, final)
        finally:
            Path(temporary).unlink(missing_ok=True)
        return {
            "path": str(final), "sha256": digest, "mime_type": "image/png",
            "width_pixels": image.width, "height_pixels": image.height,
            "size_bytes": final.stat().st_size,
        }

    def render_page(self, path: str | Path, page: int = 1, dpi: int = 150) -> dict[str, Any]:
        source = self._load(path)
        image, geometry = self._render(source, page, dpi)
        try:
            return {
                "source": source.metadata,
                "artifact": self._artifact(image, f"page-{page}"),
                "provenance": {
                    **geometry, "dpi": dpi, "bbox": [0.0, 0.0, 1.0, 1.0],
                    "coordinate_system": "normalized_displayed_cropbox_top_left",
                    "renderer": "poppler.pdftoppm",
                },
            }
        finally:
            image.close()

    def crop_region(
        self, path: str | Path, page: int, bbox: list[float], dpi: int = 300
    ) -> dict[str, Any]:
        if not isinstance(bbox, (list, tuple)) or len(bbox) != 4:
            raise PdfError("bbox must contain [left, top, right, bottom].")
        if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in bbox):
            raise PdfError("bbox coordinates must be finite numbers.")
        left, top, right, bottom = (float(v) for v in bbox)
        if not (0 <= left < right <= 1 and 0 <= top < bottom <= 1):
            raise PdfError("bbox must satisfy 0 <= left < right <= 1 and 0 <= top < bottom <= 1.")
        source = self._load(path)
        image, geometry = self._render(source, page, dpi)
        try:
            pixels = [math.floor(left * image.width), math.floor(top * image.height),
                      math.ceil(right * image.width), math.ceil(bottom * image.height)]
            cropped = image.crop(tuple(pixels))
            try:
                artifact = self._artifact(cropped, f"crop-{page}")
            finally:
                cropped.close()
            return {
                "source": source.metadata, "artifact": artifact,
                "provenance": {
                    **geometry, "dpi": dpi, "bbox": [left, top, right, bottom],
                    "pixel_bbox": pixels,
                    "full_page_pixels": [image.width, image.height],
                    "coordinate_system": "normalized_displayed_cropbox_top_left",
                    "pixel_rounding": "floor_left_top_ceil_right_bottom",
                    "renderer": "poppler.pdftoppm",
                },
            }
        finally:
            image.close()

    def extract_drawing(
        self, path: str | Path, include_strokes: bool = False, stroke_kinds: list[str] | None = None
    ) -> dict[str, Any]:
        if not isinstance(include_strokes, bool):
            raise PdfError("include_strokes must be a boolean.")
        if stroke_kinds is not None:
            if (not include_strokes or not isinstance(stroke_kinds, list) or not stroke_kinds
                    or any(not isinstance(kind, str) or kind not in {item.value for item in Kind} for kind in stroke_kinds)
                    or len(set(stroke_kinds)) != len(stroke_kinds)):
                raise PdfError("stroke_kinds requires include_strokes=true and a nonempty list of distinct supported classes.")
        source = self._load(path)
        geometry = self._geometry(source, 1)
        if (geometry["rotation_degrees"] != 0 or geometry["user_unit"] != 1
                or geometry["cropbox_points"] != geometry["mediabox_points"]
                or geometry["mediabox_points"][:2] != [0.0, 0.0]):
            raise PdfError("Vector analysis requires an unrotated page with UserUnit=1 and a full, zero-origin MediaBox. Use PDF rendering for other page layouts.")
        # PyMuPDF does not support multithreaded execution. Each analysis uses
        # a separate process, the permitted snapshot, and the configured timeout.
        with tempfile.TemporaryDirectory(prefix=".pdf-extract-", dir=self._output_directory()) as temp:
            snapshot = Path(temp) / "source.pdf"
            result_path = Path(temp) / "result.json"
            snapshot.write_bytes(source.data)
            try:
                completed = subprocess.run(
                    [sys.executable, "-X", "utf8", "-m", "drawing2cad_mcp.vector_worker", str(snapshot), str(result_path)],
                    stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                    timeout=self.timeout_seconds, check=False,
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
                )
            except subprocess.TimeoutExpired as exc:
                raise PdfError(f"Vector analysis exceeded the {self.timeout_seconds:g} second timeout.") from exc
            except OSError as exc:
                raise PdfError(f"Cannot start vector analysis: {type(exc).__name__}.") from exc
            if completed.returncode:
                detail = completed.stderr.decode("utf-8", errors="replace").strip()[-1000:]
                raise PdfError(f"Vector analysis failed: {detail or 'worker exited without a result'}")
            if not result_path.is_file() or result_path.stat().st_size > 64 * 1024 * 1024:
                raise PdfError("Vector analysis produced no result or exceeded the 64 MiB result limit.")
            try:
                data = json.loads(result_path.read_text(encoding="utf-8"))
                valid_kinds = {kind.value for kind in Kind}
                if (not isinstance(data, dict) or data.get("schema_version") != SCHEMA_VERSION
                        or not isinstance(data.get("strokes"), list) or not isinstance(data.get("views"), list)
                        or any(not isinstance(stroke, dict) or stroke.get("kind") not in valid_kinds for stroke in data["strokes"])
                        or any(not isinstance(view, dict) or not isinstance(view.get("stroke_ids"), list) for view in data["views"])):
                    raise ValueError("invalid vector result")
            except (OSError, ValueError, TypeError) as exc:
                raise PdfError("Vector analysis produced an invalid result.") from exc
        strokes = data.pop("strokes")
        if include_strokes:
            data["strokes"] = [s for s in strokes if stroke_kinds is None or s["kind"] in stroke_kinds]
        else:  # Stroke ids are most of the payload and refer to nothing without the strokes.
            for view in data["views"]:
                view["stroke_count"] = len(view.pop("stroke_ids"))
        return {
            **data, "source": source.metadata,
            "provenance": {
                **geometry, "profile": "bct_nx_a3", "coordinate_system": "sheet_mm_top_left_y_down",
                "scale_applied": False, "ocr_performed": False, "engine": "drawing2cad_mcp.vector",
                "limitations": [
                    "Only page 1 is analyzed; the drawing-area profile is calibrated for BCT/NX A3 sheets.",
                    "Glyph recognition can return '?' or an incorrect known character; verify dimensions in source images.",
                    "Sheet coordinates and stroke classes do not define part dimensions or CAD operations.",
                ],
            },
        }
