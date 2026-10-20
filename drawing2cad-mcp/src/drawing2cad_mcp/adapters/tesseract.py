"""Bounded OCR with the Tesseract C API through ctypes.

The restricted worker cannot create processes, so it calls libtesseract in its own process. The language data comes from
the Debian packages tesseract-ocr-eng and tesseract-ocr-deu.
"""

from __future__ import annotations

import ctypes
import ctypes.util
from pathlib import Path

LIBRARY_NAMES = ("libtesseract.so.5", "tesseract")
TESSDATA = (Path("/usr/share/tesseract-ocr/5/tessdata"), Path("/usr/share/tesseract-ocr/4.00/tessdata"))
LANGUAGES = "eng+deu"
# Page segmentation mode 11: sparse text. Dimension crops contain leader and extension lines.
PSM_SPARSE_TEXT = 11
PSM_SINGLE_LINE = 7
MAX_PIXELS = 4_000_000


def _library():
    for name in LIBRARY_NAMES:
        path = name if name.endswith(".5") else ctypes.util.find_library(name)
        if not path:
            continue
        try:
            return ctypes.CDLL(path)
        except OSError:
            continue
    return None


def _tessdata() -> Path | None:
    for path in TESSDATA:
        if all((path / f"{language}.traineddata").is_file() for language in LANGUAGES.split("+")):
            return path
    return None


def capabilities() -> dict:
    library = _library()
    version = None
    if library is not None:
        library.TessVersion.restype = ctypes.c_char_p
        version = library.TessVersion().decode("ascii", errors="replace")
    data = _tessdata()
    return {"available": library is not None and data is not None, "engine": "Tesseract", "version": version,
            "languages": LANGUAGES, "tessdata": str(data) if data else None}


class Ocr:
    """One Tesseract instance. Each call reads one gray image region."""

    def __init__(self):
        library = _library()
        data = _tessdata()
        if library is None or data is None:
            raise ValueError("Tesseract or its eng and deu language data is not installed.")
        self.lib = library
        self.lib.TessBaseAPICreate.restype = ctypes.c_void_p
        self.lib.TessBaseAPIInit3.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_char_p]
        self.lib.TessBaseAPISetPageSegMode.argtypes = [ctypes.c_void_p, ctypes.c_int]
        self.lib.TessBaseAPISetImage.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int]
        self.lib.TessBaseAPISetSourceResolution.argtypes = [ctypes.c_void_p, ctypes.c_int]
        self.lib.TessBaseAPIGetUTF8Text.argtypes = [ctypes.c_void_p]
        self.lib.TessBaseAPIGetUTF8Text.restype = ctypes.c_void_p
        self.lib.TessBaseAPIMeanTextConf.argtypes = [ctypes.c_void_p]
        self.lib.TessDeleteText.argtypes = [ctypes.c_void_p]
        self.lib.TessBaseAPIEnd.argtypes = [ctypes.c_void_p]
        self.lib.TessBaseAPIDelete.argtypes = [ctypes.c_void_p]
        self.lib.TessVersion.restype = ctypes.c_char_p
        self.version = self.lib.TessVersion().decode("ascii", errors="replace")
        self.handle = self.lib.TessBaseAPICreate()
        if not self.handle or self.lib.TessBaseAPIInit3(self.handle, str(data).encode(), LANGUAGES.encode()) != 0:
            raise ValueError("Tesseract cannot load its language data.")
        self.calls = 0

    def read(self, image, mode: int = PSM_SPARSE_TEXT, dpi: int = 300) -> tuple[str, int]:
        """Text and mean confidence (0..100) of a PIL image in mode L."""
        if image.mode != "L":
            image = image.convert("L")
        width, height = image.size
        if width * height > MAX_PIXELS or width < 4 or height < 4:
            raise ValueError("The OCR region is outside its size limits.")
        self.calls += 1
        data = image.tobytes()
        self.lib.TessBaseAPISetPageSegMode(self.handle, mode)
        self.lib.TessBaseAPISetImage(self.handle, data, width, height, 1, width)
        self.lib.TessBaseAPISetSourceResolution(self.handle, dpi)
        pointer = self.lib.TessBaseAPIGetUTF8Text(self.handle)
        if not pointer:
            return "", 0
        try:
            text = ctypes.string_at(pointer).decode("utf-8", errors="replace")
        finally:
            self.lib.TessDeleteText(pointer)
        return text.strip(), int(self.lib.TessBaseAPIMeanTextConf(self.handle))

    def close(self):
        if self.handle:
            self.lib.TessBaseAPIEnd(self.handle)
            self.lib.TessBaseAPIDelete(self.handle)
            self.handle = None
