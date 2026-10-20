"""Verify the final drawing PDF bytes in a restricted worker.

The verifier reads the stored PDF, the Poppler raster of its pages, and optionally the bound STEP candidate.
It does not read the DXF or the entity list of the generator. The expectations come from the bound drawing specification,
and the model projections are derived again from the STEP candidate.
"""

from __future__ import annotations

import difflib
import hashlib
import json
import math
import re
from pathlib import Path
from typing import Any

VERIFIER = "drawing2cad-pdf-verifier"
# Rules that a complete-service drawing must pass. STYLE-01 is reported but is not part of the acceptance.
# REVIEW-01 is the identified review, which drawing_review records.
MANDATORY_RULES = (
    "PDF-INTEGRITY-01", "PDF-STRUCT-01", "PDF-STRUCT-02", "PDF-STRUCT-03", "PDF-STRUCT-04", "PDF-BIND-01",
    "RENDER-01", "RENDER-02", "RENDER-03", "RENDER-04", "VIEW-REQ-01", "VIEW-REQ-02", "ISO-01",
    "MODEL-01", "MODEL-02", "MODEL-03", "MODEL-04", "MODEL-05", "DIM-01", "DIM-02", "DIM-03", "DIM-04", "DIM-05",
    "UNITS-01", "REV-01", "REV-02", "TEXT-01", "TEXT-02", "TEXT-03", "TEXT-04", "TEXT-05", "TEXT-LIMIT", "SEC-01",
    "GPS-01", "GPS-02", "GPS-03", "GPS-04", "GPS-05", "GPS-06", "GPS-07", "GPS-08", "GPS-09",
)
# A mandatory rule without a finding is not applicable only for these reasons. Any other missing rule is not tested.
ABSENT_REASONS = {
    "MODEL-02": "The drawing does not draw hidden edges.",
    "DIM-04": "The drawing has no radius or diameter dimension in a true-size view.",
    "REV-01": "A current validated build exists.",
    "TEXT-01": "The title block has no other field with a value.",
    "TEXT-03": "The drawing has no notes.",
    "TEXT-04": "The drawing has no uncertainty markers.",
    "TEXT-05": "The drawing has no other labels.",
    "TEXT-LIMIT": "The verifier read each text region of the drawing.",
    "GPS-01": "The drawing has no tolerance frames.",
    "GPS-02": "The drawing has no tolerance frames.",
    "GPS-03": "No tolerance frame is outside the supported profile.",
    "GPS-04": "The drawing has no unsupported GPS requirements.",
    "GPS-05": "The drawing has no tolerance frames.",
    "GPS-06": "No tolerance frame has a datum reference.",
    "GPS-07": "No tolerance frame has a modifier.",
    "GPS-08": "The drawing has no datum symbols.",
    "GPS-09": "The drawing has no datum symbols.",
}
VERIFIER_VERSION = "1.0.0"
REPORT_SCHEMA = "1.0"
THRESHOLDS = {
    "ink_level": 160,                 # Gray value below which a raster pixel is ink.
    "edge_radius_mm": 0.35,           # A model edge point is covered by ink within this radius.
    "visible_coverage": 0.95,         # Fraction of visible model edge points that must be covered.
    "hidden_coverage": 0.60,          # Hidden edges are dashed, so a lower fraction is necessary.
    "geometry_on_model_mm": 0.20,     # A drawn primitive point must be this close to a model edge.
    "geometry_on_model": 0.95,
    "anchor_mm": 0.05,                # A dimension anchor must be this close to a model edge.
    "radius_mm": 0.01,
    "blank_ink_fraction": 0.002,
    "page_edge_mm": 0.5,
    "page_box_points": 1.5,
    "raster_pixels": 3,
    "text_similarity": 0.80,
    "max_ocr_regions": 250,
    "extra_extent_mm": 3.0,           # Extent of a connected ink region in a view that nothing explains.
}
EXTRA_TOLERANCE_MM = 0.8
# Hatch lines are at exact positions. A narrow tolerance keeps extra content between them visible.
HATCH_TOLERANCE_MM = 0.35
SAMPLE_MM = 0.5
PSM_SPARSE_TEXT = 11
PSM_SINGLE_CHARACTER = 10


class Report:
    def __init__(self):
        self.findings: list[dict] = []

    def add(self, rule, status, severity, message, *, region=None, page=1, feature=None, expected=None, observed=None, evidence=None):
        self.findings.append({"rule_id": rule, "status": status, "severity": severity, "message": message, "page": page,
                              "region_mm": [round(v, 3) for v in region] if region else None, "feature": feature,
                              "expected": expected, "observed": observed, "evidence": evidence})

    def status(self) -> str:
        statuses = {item["status"] for item in self.findings}
        return "fail" if "fail" in statuses else "needs_review" if "needs_review" in statuses else "pass"


# ---------------------------------------------------------------------------------------------------------------
# Raster


class Raster:
    def __init__(self, path: Path, sheet_width: float, sheet_height: float, dpi: int):
        import numpy
        from PIL import Image

        Image.MAX_IMAGE_PIXELS = 60_000_000
        self.image = Image.open(path).convert("L")
        self.numpy = numpy
        self.pixels = numpy.asarray(self.image)
        self.dpi = dpi
        self.width_mm, self.height_mm = sheet_width, sheet_height
        self.ink = self.pixels < THRESHOLDS["ink_level"]
        self.near = self._dilate(self.ink, max(1, round(THRESHOLDS["edge_radius_mm"] * dpi / 25.4)))

    def _dilate(self, mask, radius):
        numpy = self.numpy
        out = mask.copy()
        for axis in (0, 1):
            grown = out.copy()
            for shift in range(1, radius + 1):
                grown[tuple(slice(shift, None) if a == axis else slice(None) for a in (0, 1))] |= \
                    out[tuple(slice(None, -shift) if a == axis else slice(None) for a in (0, 1))]
                grown[tuple(slice(None, -shift) if a == axis else slice(None) for a in (0, 1))] |= \
                    out[tuple(slice(shift, None) if a == axis else slice(None) for a in (0, 1))]
            out = grown
        return out

    def pixel(self, point):
        return (point[0] * self.dpi / 25.4, (self.height_mm - point[1]) * self.dpi / 25.4)

    def covered(self, points) -> list[bool]:
        height, width = self.near.shape
        result = []
        for point in points:
            x, y = self.pixel(point)
            column, row = int(round(x)), int(round(y))
            result.append(0 <= row < height and 0 <= column < width and bool(self.near[row, column]))
        return result

    def unexplained(self, box, items, tolerance_mm) -> float:
        """Area in mm² of ink in a box that is farther than tolerance from the given sheet primitives."""
        from PIL import Image, ImageDraw

        mask = Image.new("1", self.image.size, 0)
        draw = ImageDraw.Draw(mask)
        width = max(1, round(2 * tolerance_mm * self.dpi / 25.4))
        for item in items:
            points = [self.pixel(p) for p in sample(item, 0.2)]
            if len(points) > 1:
                draw.line(points, fill=1, width=width, joint="curve")
        explained = self.numpy.asarray(mask, dtype=bool)
        x0, y1 = self.pixel([box[0], box[1]])
        x1, y0 = self.pixel([box[2], box[3]])
        rows, columns = slice(max(0, int(y0)), max(0, int(y1))), slice(max(0, int(x0)), max(0, int(x1)))
        stray = self.ink[rows, columns] & ~explained[rows, columns]
        return float(stray.sum()) * (25.4 / self.dpi) ** 2

    def ink_fraction(self, box=None) -> float:
        if box is None:
            return float(self.ink.mean())
        x0, y1 = self.pixel([box[0], box[1]])
        x1, y0 = self.pixel([box[2], box[3]])
        part = self.ink[max(0, int(y0)):max(0, int(y1)), max(0, int(x0)):max(0, int(x1))]
        return float(part.mean()) if part.size else 0.0

    def crop(self, center, width_mm, height_mm, angle):
        """A horizontal image of a text region. angle is the text direction in degrees, counterclockwise on the sheet."""
        side = math.hypot(width_mm, height_mm) * 1.15
        cx, cy = self.pixel(center)
        half = side * self.dpi / 25.4 / 2
        region = self.image.crop((int(cx - half), int(cy - half), int(cx + half), int(cy + half)))
        rotated = region.rotate(-angle, resample=3, fillcolor=255)
        w = width_mm * self.dpi / 25.4
        h = height_mm * self.dpi / 25.4
        mid = rotated.size[0] / 2
        return rotated.crop((int(mid - w / 2), int(mid - h / 2), int(mid + w / 2), int(mid + h / 2)))


# ---------------------------------------------------------------------------------------------------------------
# Geometry


def _sheet(view, point):
    return [view["origin"][i] + view["scale"] * point[i] for i in (0, 1)]


def sample(item: dict, step: float = SAMPLE_MM) -> list[list[float]]:
    """Local points along a primitive, about step apart."""
    kind = item["type"]
    if kind == "line":
        length = math.dist(item["start"], item["end"])
        count = max(1, math.ceil(length / step))
        return [[item["start"][i] + (item["end"][i] - item["start"][i]) * k / count for i in (0, 1)] for k in range(count + 1)]
    if kind in {"circle", "arc"}:
        start = 0.0 if kind == "circle" else item["start_angle"]
        sweep = 360.0 if kind == "circle" else ((item["end_angle"] - item["start_angle"]) % 360 or 360.0)
        count = max(8, math.ceil(math.radians(sweep) * item["radius"] / step))
        return [[item["center"][0] + item["radius"] * math.cos(math.radians(start + sweep * k / count)),
                 item["center"][1] + item["radius"] * math.sin(math.radians(start + sweep * k / count))] for k in range(count + 1)]
    major = item["major_axis"]
    minor = [-major[1] * item["ratio"], major[0] * item["ratio"]]
    start, end = item["start_parameter"], item["end_parameter"]
    count = max(8, math.ceil(math.radians(end - start) * math.hypot(*major) / step))
    return [[item["center"][i] + math.cos(math.radians(start + (end - start) * k / count)) * major[i]
             + math.sin(math.radians(start + (end - start) * k / count)) * minor[i] for i in (0, 1)] for k in range(count + 1)]


def _nearest(points, targets, numpy):
    """Distance of each point to the nearest target point."""
    if not len(targets):
        return [math.inf] * len(points)
    target = numpy.asarray(targets, dtype=float)
    result = []
    for start in range(0, len(points), 500):
        chunk = numpy.asarray(points[start:start + 500], dtype=float)
        distances = numpy.sqrt(((chunk[:, None, :] - target[None, :, :]) ** 2).sum(axis=2))
        result.extend(distances.min(axis=1).tolist())
    return result


# ---------------------------------------------------------------------------------------------------------------
# Text


def number_text(value: float) -> str:
    text = f"{value:.4f}".rstrip("0").rstrip(".")
    return text or "0"


def _numbers(text: str) -> list[str]:
    text = text.replace(",", ".")
    # Frequent OCR confusions between digits: O and o for 0, l and I for 1, S for 5.
    text = re.sub(r"(?<=\d)[Oo]|[Oo](?=\d)", "0", text)
    text = re.sub(r"(?<=\d)[lI|]|[lI|](?=\d)", "1", text)
    return re.findall(r"\d+(?:\.\d+)?", text)


def _normal(text: str) -> str:
    return re.sub(r"[^0-9a-z]", "", text.lower())


# Characters that Tesseract reads for the diameter sign. Only one such character directly before the value is accepted.
# A digit that can be a real leading digit (for example 2 or 1) is not accepted.
DIAMETER_CONFUSIONS = "8"


def _has_number(token: str, found: list[str], observed: str, diameter: bool) -> bool:
    """For a diameter, the sign must be present: either as Ø, or as one confusable character directly before the value."""
    if not diameter:
        return token in found
    if any(len(item) == len(token) + 1 and item.endswith(token) and item[0] in DIAMETER_CONFUSIONS for item in found):
        return True
    return token in found and re.search(r"[ØøΦφ⌀@]\s*" + re.escape(token) + r"(?![\d.])", observed) is not None


def _canonical(text: str) -> str:
    """The value characters of a text: digits, decimal point, ratio sign, and list separators. Leader dashes at the ends are removed."""
    text = re.sub(r"(?<=\d)[Oo]|[Oo](?=\d)", "0", text)
    text = re.sub(r"(?<=\d)[lI|]|[lI|](?=\d)", "1", text)
    return re.sub(r"[^0-9.:,±+]", "", text.replace(" ", "")).strip(".,")


def text_matches(expected: str, observed: str, critical: bool) -> bool:
    if critical:
        # The value must be exactly the expected value: no other digit, sign, or separator. 1:10 is not 1:1, 0.1±0.9 is not 0.1.
        value = _canonical(expected.replace("Ø", ""))
        letters = re.sub(r"[^A-Za-z]", "", expected.replace("Ø", "")).lower()
        found = _canonical(re.sub(r"^[^0-9A-Za-zØøΦφ⌀@]+|[^0-9A-Za-z]+$", "", observed.strip()))
        if value:
            if "Ø" in expected:
                if not (found == "8" + value or (found == value and re.search(r"[ØøΦφ⌀@]\s*" + re.escape(value), observed))):
                    return False
            elif found != value:
                return False
        if letters and re.sub(r"[^a-z]", "", observed.lower()) != letters:
            return False
        return bool(value or letters)
    a, b = _normal(expected), _normal(observed)
    if not a:
        return True
    if a in b:
        return True
    return difflib.SequenceMatcher(None, a, b).ratio() >= THRESHOLDS["text_similarity"]


def check_texts(report: Report, raster: Raster, texts: list[dict], ocr) -> dict:
    """Read each expected text from the raster. An unreadable critical value fails; it never passes for lack of text."""
    counts = {"read": 0, "failed": 0}
    for item in texts[:THRESHOLDS["max_ocr_regions"]]:
        height = item["height"]
        width = len(item["text"]) * height * 0.95 + 3.0
        box_height = height * 2.0 + 1.6
        observed = []
        matched = False
        for angle in item["angles"]:
            if item.get("box"):
                # A text in a field or a frame compartment: read only the inside, without the border lines.
                x0, y0, x1, y1 = item["box"]
                width, box_height = x1 - x0, y1 - y0
                image = raster.crop([(x0 + x1) / 2, (y0 + y1) / 2], width, box_height, 0.0)
            else:
                image = raster.crop(item["center"], width, box_height, angle)
            # Tesseract reads text best at about 30 px cap height.
            scale = max(1.0, 32 / max(1.0, height * raster.dpi / 25.4))
            if scale > 1.0:
                image = image.resize((int(image.size[0] * scale), int(image.size[1] * scale)))
            text, confidence = ocr.read(image, mode=PSM_SINGLE_CHARACTER if len(item["text"]) == 1 else PSM_SPARSE_TEXT)
            observed.append({"angle": angle, "text": text[:120], "confidence": confidence})
            if text_matches(item["text"], text, item["critical"]):
                matched = True
                break
        center = [(item["box"][0] + item["box"][2]) / 2, (item["box"][1] + item["box"][3]) / 2] if item.get("box") else item["center"]
        region = [center[0] - width / 2, center[1] - box_height / 2, center[0] + width / 2, center[1] + box_height / 2]
        if matched:
            counts["read"] += 1
            report.add(item["rule"], "pass", "info", f"{item['kind']} {item['id']} reads as expected.", region=region,
                       feature=item.get("feature"), expected=item["text"], observed=observed[-1]["text"], evidence=item.get("evidence"))
        else:
            counts["failed"] += 1
            report.add(item["rule"], "fail", "major" if item["critical"] else "minor",
                       f"{item['kind']} {item['id']} is missing, hidden, clipped, or unreadable in the rendered PDF.",
                       region=region, feature=item.get("feature"), expected=item["text"], observed=observed, evidence=item.get("evidence"))
    if len(texts) > THRESHOLDS["max_ocr_regions"]:
        report.add("TEXT-LIMIT", "fail", "major", "The drawing has more text regions than the verifier reads. Texts after the limit are not inspected.",
                   expected=THRESHOLDS["max_ocr_regions"], observed=len(texts))
    return counts


# ---------------------------------------------------------------------------------------------------------------
# Checks


def check_pdf(report: Report, path: Path, expected: dict, sheet: dict | None) -> dict:
    import pymupdf

    data = path.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    if expected.get("pdf_sha256") and digest != expected["pdf_sha256"]:
        report.add("PDF-INTEGRITY-01", "fail", "critical", "The PDF bytes differ from the expected hash.",
                   expected=expected["pdf_sha256"], observed=digest)
    else:
        report.add("PDF-INTEGRITY-01", "pass", "info", "The PDF bytes have the expected hash.", observed=digest)
    try:
        document = pymupdf.open(stream=data, filetype="pdf")
    except Exception as error:  # noqa: BLE001 - a malformed PDF is a finding, not a crash.
        report.add("PDF-STRUCT-01", "fail", "critical", "The PDF cannot be opened.", observed=type(error).__name__)
        return {"pages": 0, "page_size_mm": None}
    with document:
        if document.needs_pass or document.is_encrypted:
            report.add("PDF-STRUCT-01", "fail", "critical", "The PDF is encrypted. Its pages cannot be inspected.")
            return {"pages": 0, "page_size_mm": None}
        report.add("PDF-STRUCT-01", "pass", "info", "The PDF opens without a password.")
        count = document.page_count
        page = document[0] if count else None
        size = [page.rect.width * 25.4 / 72, page.rect.height * 25.4 / 72] if page else None
        if count != 1:
            report.add("PDF-STRUCT-02", "fail", "major", "A drawing sheet must have exactly one page.", expected=1, observed=count)
        else:
            report.add("PDF-STRUCT-02", "pass", "info", "The PDF has one page.", observed=count)
        if page is not None and page.rotation != 0:
            report.add("PDF-STRUCT-03", "fail", "major", "The page is rotated.", expected=0, observed=page.rotation)
        elif page is not None:
            report.add("PDF-STRUCT-03", "pass", "info", "The page is not rotated.")
        if sheet and page is not None:
            expected_points = [sheet["width"] / 25.4 * 72, sheet["height"] / 25.4 * 72]
            observed_points = [page.rect.width, page.rect.height]
            if any(abs(a - b) > THRESHOLDS["page_box_points"] for a, b in zip(expected_points, observed_points)):
                report.add("PDF-STRUCT-04", "fail", "major", "The page box differs from the sheet size.",
                           expected=[round(v, 2) for v in expected_points], observed=[round(v, 2) for v in observed_points])
            else:
                report.add("PDF-STRUCT-04", "pass", "info", "The page box agrees with the sheet size.")
        if expected.get("part_revision") is not None:
            keywords = (document.metadata or {}).get("keywords") or ""
            fields = dict(item.strip().split(":", 1) for item in keywords.split(";") if ":" in item)
            wanted = {"part_revision": str(expected["part_revision"]), "description_sha256": expected["description_sha256"]}
            if expected.get("dxf_sha256"):
                wanted["dxf_sha256"] = expected["dxf_sha256"]
            # Compare complete field values: part_revision:10 is not part_revision:1.
            missing = [f"{key}:{value}" for key, value in wanted.items() if fields.get(key, "").strip() != value]
            if missing:
                report.add("PDF-BIND-01", "fail", "critical", "The PDF metadata does not name the bound revision, description, or DXF.",
                           expected=wanted, observed=keywords[:300])
            else:
                report.add("PDF-BIND-01", "pass", "info", "The PDF metadata names the bound revision, description, and DXF.")
        return {"pages": count, "page_size_mm": size}


def check_raster(report: Report, raster: Raster, pages_rendered: int, pages: int, sheet: dict) -> None:
    expected = [round(raster.width_mm * raster.dpi / 25.4), round(raster.height_mm * raster.dpi / 25.4)]
    observed = list(raster.image.size)
    if pages_rendered != pages:
        report.add("RENDER-01", "fail", "critical", "The renderer did not write each page. The PDF was not inspected completely.",
                   expected=pages, observed=pages_rendered)
    elif any(abs(a - b) > THRESHOLDS["raster_pixels"] for a, b in zip(expected, observed)):
        report.add("RENDER-01", "fail", "critical", "The rendered page has an unexpected pixel size. The page was not rendered completely.",
                   expected=expected, observed=observed)
    else:
        report.add("RENDER-01", "pass", "info", "Poppler rendered each page completely at the fixed resolution.", observed=observed)
    ink = raster.ink_fraction()
    if ink < THRESHOLDS["blank_ink_fraction"]:
        report.add("RENDER-02", "fail", "critical", "The rendered page is blank.", expected=f">= {THRESHOLDS['blank_ink_fraction']}", observed=round(ink, 5))
    else:
        report.add("RENDER-02", "pass", "info", "The rendered page has content.", observed=round(ink, 5))
    # Ink at the page edge shows clipped content. The centering marks of the border reach the edge on purpose.
    edge = THRESHOLDS["page_edge_mm"]
    width, height = raster.width_mm, raster.height_mm
    strips = [[0, 0, width, edge], [0, height - edge, width, height], [0, 0, edge, height], [width - edge, 0, width, height]]
    clipped = []
    for strip in strips:
        for box in _without_marks(strip, width, height):
            if raster.ink_fraction(box) > 0.001:
                clipped.append([round(v, 2) for v in box])
    if clipped:
        report.add("RENDER-03", "fail", "major", "Content touches the page edge and can be clipped.", region=clipped[0], observed=clipped[:4])
    else:
        report.add("RENDER-03", "pass", "info", "No content touches the page edge.")


def _without_marks(strip, width, height):
    """Split an edge strip around the centering marks at the middle of each side."""
    x0, y0, x1, y1 = strip
    if x1 - x0 > y1 - y0:
        return [[x0, y0, width / 2 - 1.5, y1], [width / 2 + 1.5, y0, x1, y1]]
    return [[x0, y0, x1, height / 2 - 1.5], [x0, height / 2 + 1.5, x1, y1]]


def check_views(report: Report, views: list[dict], required: dict) -> None:
    from .drawing_contract_v2 import Projection, projection_defects

    kinds = {view["kind"] for view in views}
    for kind, rule, name in (("isometric", "VIEW-REQ-01", "an isometric view"), ("section", "VIEW-REQ-02", "a section view")):
        if not required.get(kind):
            continue
        if kind in kinds:
            report.add(rule, "pass", "info", f"The bound drawing declares {name}.")
        else:
            report.add(rule, "fail", "major", f"The drawing has no {name}, and the complete-service drawing needs one.",
                       expected=kind, observed=sorted(kinds))
    for view in views:
        if view["kind"] != "isometric":
            continue
        if not view.get("projection"):
            report.add("ISO-01", "fail", "major", "The isometric view has no projection.", region=view["frame"], feature=view["id"])
            continue
        defects = projection_defects("isometric", Projection(**view["projection"]))
        if defects:
            report.add("ISO-01", "fail", "major", " ".join(defects), region=view["frame"], feature=view["id"])
        else:
            report.add("ISO-01", "pass", "info", "The isometric projection has equal axis scales, 120-degree axes, a parallel projection, "
                       "and an isometric scale convention.", region=view["frame"], feature=view["id"])


def check_model(report: Report, raster: Raster, directory: Path, views: list[dict]) -> dict[str, dict]:
    """Derive the views again from the bound STEP and compare them with the raster and the declared geometry."""
    from .view_derivation import derive

    for view in views:
        if not view.get("derivation_request"):
            report.add("MODEL-01", "not_tested", "info", f"View {view['id']} has no projection, so the model cannot be compared with it.",
                       region=view["frame"], feature=view["id"])
    requests = [view["derivation_request"] for view in views if view.get("derivation_request")]
    if not requests:
        return {}
    result = derive(directory / "input.step", requests)
    if result.get("status") != "pass":
        for view in views:
            report.add("MODEL-01", "fail", "major", "The verifier cannot derive the view from the bound model: "
                       + result.get("error", {}).get("message", "unknown error"), region=view["frame"], feature=view["id"])
        return {}
    derived = {item["id"]: item for item in result["views"]}
    numpy = raster.numpy
    for view in views:
        model = derived.get(view["id"])
        if model is None:
            continue
        styles = {"visible": ("MODEL-01", THRESHOLDS["visible_coverage"]), "section": ("MODEL-03", THRESHOLDS["visible_coverage"])}
        if view.get("hidden_lines"):
            styles["hidden"] = ("MODEL-02", THRESHOLDS["hidden_coverage"])
        for style, (rule, threshold) in styles.items():
            items = [item for item in model["geometry"] if item["style"] == style]
            if not items:
                continue
            # Each model edge must be present. A small missing feature cannot hide in a large total coverage.
            missing_edges = []
            total = covered_count = 0
            for item in items:
                points = [_sheet(view, p) for p in sample(item, SAMPLE_MM / view["scale"])]
                covered = raster.covered(points)
                total += len(covered)
                covered_count += sum(covered)
                if sum(covered) / len(covered) < threshold:
                    missing_edges.append({"id": item["id"], "type": item["type"], "coverage": round(sum(covered) / len(covered), 3),
                                          "points": [p for p, ok in zip(points, covered) if not ok]})
            fraction = covered_count / total
            if not missing_edges:
                report.add(rule, "pass", "info", f"View {view['id']}: each {style} model edge is present in the rendered PDF.",
                           region=view["frame"], feature=view["id"], expected=f">= {threshold} for each edge", observed=round(fraction, 4))
            else:
                points = [p for edge in missing_edges for p in edge["points"]] or [view["frame"][:2], view["frame"][2:]]
                report.add(rule, "fail", "major",
                           f"View {view['id']}: {len(missing_edges)} {style} edges of the bound model are missing in the rendered PDF.",
                           region=_bounds(points), feature=view["id"], expected=f">= {threshold} for each edge",
                           observed=[{key: edge[key] for key in ("id", "type", "coverage")} for edge in missing_edges[:10]])
        # Each declared visible or section primitive must lie on an edge of the model.
        model_points = [p for item in model["geometry"] if item["style"] in {"visible", "section", "hidden"} for p in sample(item, 0.1)]
        drawn = [p for item in view["geometry"] if item.get("style", "visible") in {"visible", "section"} for p in sample(item, SAMPLE_MM)]
        if drawn:
            distances = _nearest(drawn, model_points, numpy)
            tolerance = THRESHOLDS["geometry_on_model_mm"]
            fraction = sum(d <= tolerance for d in distances) / len(distances)
            off = [_sheet(view, p) for p, d in zip(drawn, distances) if d > tolerance]
            if fraction >= THRESHOLDS["geometry_on_model"]:
                report.add("MODEL-04", "pass", "info", f"View {view['id']}: the drawn geometry agrees with the bound model.",
                           region=view["frame"], feature=view["id"], observed=round(fraction, 4))
            else:
                report.add("MODEL-04", "fail", "major", f"View {view['id']}: drawn geometry is not on an edge of the bound model.",
                           region=_bounds(off), feature=view["id"], expected=f">= {THRESHOLDS['geometry_on_model']}", observed=round(fraction, 4))
    return derived


def _bounds(points):
    return [min(p[0] for p in points), min(p[1] for p in points), max(p[0] for p in points), max(p[1] for p in points)]


def _distance_to(point, item) -> float:
    if item["type"] == "line":
        a, b = item["start"], item["end"]
        d = [b[0] - a[0], b[1] - a[1]]
        length = d[0] ** 2 + d[1] ** 2
        t = 0.0 if length == 0 else max(0.0, min(1.0, ((point[0] - a[0]) * d[0] + (point[1] - a[1]) * d[1]) / length))
        return math.dist(point, [a[0] + t * d[0], a[1] + t * d[1]])
    if item["type"] == "circle":
        return abs(math.dist(point, item["center"]) - item["radius"])
    return min(math.dist(point, p) for p in sample(item, 0.02))


def check_dimension_lines(report: Report, raster: Raster, dimension_lines: list[dict]) -> None:
    """The rendered dimension, extension, and leader lines must be where the bound drawing puts them."""
    for item in dimension_lines:
        if item.get("not_tested"):
            report.add("DIM-05", "not_tested", "info", f"Dimension {item['id']}: {item['not_tested']}", feature=item["id"], evidence=item["evidence"])
            continue
        # Each segment on its own: a missing extension line cannot hide in a long dimension line.
        fraction = min(sum(covered) / len(covered) for covered in
                       (raster.covered(sample({"type": "line", "start": a, "end": b}, 0.3)) for a, b in item["segments"]))
        region = _bounds([p for segment in item["segments"] for p in segment])
        if fraction >= 0.8:
            report.add("DIM-05", "pass", "info", f"Dimension {item['id']} shows its dimension and extension lines.", region=region,
                       feature=item["id"], observed=round(fraction, 3), evidence=item["evidence"])
        else:
            report.add("DIM-05", "fail", "major", f"Dimension {item['id']} has missing or moved dimension, extension, or leader lines.",
                       region=region, feature=item["id"], expected=">= 0.8", observed=round(fraction, 3), evidence=item["evidence"])


def check_extra_ink(report: Report, raster: Raster, views: list[dict], derived: dict[str, dict], request: dict) -> None:
    """Ink in a view that no model edge, declared primitive, dimension, label, or sheet item explains is extra content."""
    from PIL import Image, ImageDraw

    numpy = raster.numpy
    mask = Image.new("1", raster.image.size, 0)
    draw = ImageDraw.Draw(mask)
    width = max(1, round(2 * EXTRA_TOLERANCE_MM * raster.dpi / 25.4))

    def polyline(points):
        pixels = [raster.pixel(p) for p in points]
        if len(pixels) > 1:
            draw.line(pixels, fill=1, width=width, joint="curve")

    for view in views:
        for item in view["geometry"] + (derived.get(view["id"]) or {}).get("geometry", []):
            polyline([_sheet(view, p) for p in sample(item, 0.3)])
    annotations = request.get("annotations") or {}
    for a, b in annotations.get("lines", []):
        polyline([a, b])
    for polygon in annotations.get("polygons", []):
        if len(polygon) >= 3:
            draw.polygon([raster.pixel(p) for p in polygon], fill=1, outline=1)
            polyline(polygon + [polygon[0]])
    explained = numpy.asarray(mask, dtype=bool) | _hatch_lines(raster, request.get("hatching", []))
    for view in views:
        if view["id"] not in derived:
            continue
        x0, y1 = raster.pixel([view["frame"][0], view["frame"][1]])
        x1, y0 = raster.pixel([view["frame"][2], view["frame"][3]])
        rows, columns = slice(max(0, int(y0)), max(0, int(y1))), slice(max(0, int(x0)), max(0, int(x1)))
        stray = raster.ink[rows, columns] & ~explained[rows, columns]
        area = float(stray.sum()) * (25.4 / raster.dpi) ** 2
        component = _largest_component(stray, raster.dpi)
        scale = 25.4 / raster.dpi
        if component is None or component["extent_mm"] < THRESHOLDS["extra_extent_mm"]:
            report.add("MODEL-05", "pass", "info", f"View {view['id']}: the rendered view has no content outside the model and the annotations.",
                       region=view["frame"], feature=view["id"], observed={"unexplained_mm2": round(area, 3),
                                                                          "largest_extent_mm": component["extent_mm"] if component else 0.0})
            continue
        left, top, right, bottom = component["box_px"]
        left, right = float((left + columns.start) * scale), float((right + columns.start) * scale)
        top, bottom = float((top + rows.start) * scale), float((bottom + rows.start) * scale)
        report.add("MODEL-05", "fail", "major", f"View {view['id']}: the rendered view has content that the bound model and drawing do not explain.",
                   region=[left, raster.height_mm - bottom, right, raster.height_mm - top], feature=view["id"],
                   expected=f"no unexplained content of {THRESHOLDS['extra_extent_mm']} mm or more",
                   observed={"unexplained_mm2": round(area, 3), "largest_extent_mm": component["extent_mm"]})


def _hatch_lines(raster: Raster, hatching: list[dict]):
    """The expected hatch lines inside each hatched surface, not the complete surface.

    The renderer uses the pattern ANSI31 with its base point at the sheet origin, so the lines are p · n = k · spacing,
    where n is the normal of the hatch direction. The surface is the even-odd area of its loops.
    """
    from PIL import Image, ImageDraw

    numpy = raster.numpy
    result = numpy.zeros(raster.ink.shape, dtype=bool)
    width = max(1, round(2 * HATCH_TOLERANCE_MM * raster.dpi / 25.4))
    for hatch in hatching:
        area = numpy.zeros(raster.ink.shape, dtype=bool)
        for loop in hatch["loops"]:
            if len(loop) < 3:
                continue
            layer = Image.new("1", raster.image.size, 0)
            ImageDraw.Draw(layer).polygon([raster.pixel(p) for p in loop], fill=1)
            area ^= numpy.asarray(layer, dtype=bool)
        points = [p for loop in hatch["loops"] for p in loop]
        if not points:
            continue
        angle = math.radians(hatch["angle"])
        direction = [math.cos(angle), math.sin(angle)]
        normal = [-direction[1], direction[0]]
        offsets = [p[0] * normal[0] + p[1] * normal[1] for p in points]
        along = [p[0] * direction[0] + p[1] * direction[1] for p in points]
        lines = Image.new("1", raster.image.size, 0)
        draw = ImageDraw.Draw(lines)
        for k in range(math.floor(min(offsets) / hatch["spacing"]) - 1, math.ceil(max(offsets) / hatch["spacing"]) + 2):
            c = k * hatch["spacing"]
            start = [c * normal[0] + (min(along) - 1) * direction[0], c * normal[1] + (min(along) - 1) * direction[1]]
            end = [c * normal[0] + (max(along) + 1) * direction[0], c * normal[1] + (max(along) + 1) * direction[1]]
            draw.line([raster.pixel(start), raster.pixel(end)], fill=1, width=width)
        result |= area & numpy.asarray(lines, dtype=bool)
    return result


def _largest_component(mask, dpi) -> dict | None:
    """The largest connected region of a mask on a 0.5 mm grid, with its extent in mm and its pixel box."""
    import numpy

    cell = max(1, round(0.5 * dpi / 25.4))
    height, width = mask.shape
    rows, columns = -(-height // cell), -(-width // cell)
    padded = numpy.zeros((rows * cell, columns * cell), dtype=bool)
    padded[:height, :width] = mask
    grid = padded.reshape(rows, cell, columns, cell).any(axis=(1, 3))
    seen = numpy.zeros_like(grid)
    best = None
    for start in zip(*numpy.nonzero(grid)):
        if seen[start]:
            continue
        stack, cells = [start], []
        seen[start] = True
        while stack:
            r, c = stack.pop()
            cells.append((r, c))
            for dr in (-1, 0, 1):
                for dc in (-1, 0, 1):
                    nr, nc = r + dr, c + dc
                    if 0 <= nr < rows and 0 <= nc < columns and grid[nr, nc] and not seen[nr, nc]:
                        seen[nr, nc] = True
                        stack.append((nr, nc))
        rs = [r for r, _ in cells]
        cs = [c for _, c in cells]
        extent = max(max(rs) - min(rs) + 1, max(cs) - min(cs) + 1) * cell * 25.4 / dpi
        if best is None or extent > best["extent_mm"]:
            best = {"extent_mm": round(float(extent), 3),
                    "box_px": [int(min(cs)) * cell, int(min(rs)) * cell, (int(max(cs)) + 1) * cell, (int(max(rs)) + 1) * cell]}
    return best


def check_dimensions(report: Report, views: list[dict], derived: dict[str, dict]) -> None:
    """Anchors on the model, round values against the model, and round-feature coverage."""
    dimensioned = set()
    for view in views:
        model = derived.get(view["id"])
        for dimension in view["dimensions"]:
            if dimension["type"] in {"radius", "diameter"}:
                dimensioned.add(round(dimension["radius"] * view["scale"] if view["kind"] == "isometric" else dimension["radius"], 3))
            if model is None or view["kind"] == "isometric":
                continue
            if dimension["type"] in {"radius", "diameter"}:
                circles = [item for item in model["geometry"] if item["type"] in {"circle", "arc"}
                           and math.dist(item["center"], dimension["center"]) <= THRESHOLDS["anchor_mm"]]
                match = [item for item in circles if abs(item["radius"] - dimension["radius"]) <= THRESHOLDS["radius_mm"]]
                expected = dimension["expected"] / (2 if dimension["type"] == "diameter" else 1)
                if not match:
                    observed = sorted({round(item["radius"], 4) for item in circles})
                    report.add("DIM-02", "fail", "major", f"Dimension {dimension['id']} is not attached to a round edge of the bound model.",
                               feature=dimension["id"], expected=dimension["radius"], observed=observed or None, evidence=dimension["evidence_ids"])
                elif abs(match[0]["radius"] - expected) > THRESHOLDS["radius_mm"]:
                    report.add("DIM-04", "fail", "major", f"Dimension {dimension['id']} states a value that differs from the bound model.",
                               feature=dimension["id"], expected=round(match[0]["radius"] * (2 if dimension["type"] == "diameter" else 1), 4),
                               observed=dimension["expected"], evidence=dimension["evidence_ids"])
                else:
                    report.add("DIM-02", "pass", "info", f"Dimension {dimension['id']} is attached to the model and has its value.",
                               feature=dimension["id"], evidence=dimension["evidence_ids"])
                continue
            anchors = [point for point in (dimension.get("p1"), dimension.get("p2")) if point is not None]
            distances = [min((_distance_to(point, item) for item in model["geometry"] if item["style"] in {"visible", "hidden", "section"}),
                             default=math.inf) for point in anchors]
            if all(distance <= THRESHOLDS["anchor_mm"] for distance in distances):
                report.add("DIM-02", "pass", "info", f"Dimension {dimension['id']} is attached to edges of the bound model.",
                           feature=dimension["id"], evidence=dimension["evidence_ids"])
            else:
                report.add("DIM-02", "fail", "major", f"Dimension {dimension['id']} has an anchor that is not on an edge of the bound model.",
                           feature=dimension["id"], expected=f"<= {THRESHOLDS['anchor_mm']} mm", observed=[round(d, 4) for d in distances],
                           evidence=dimension["evidence_ids"])
    round_views = model_views = 0
    for view in views:
        model = derived.get(view["id"])
        if model is None or view["kind"] != "orthographic":
            continue
        radii = sorted({round(item["radius"], 3) for item in model["geometry"] if item["type"] == "circle" and item["style"] == "visible"})
        for radius in radii:
            if radius not in dimensioned:
                report.add("DIM-03", "fail", "major", f"View {view['id']}: a round feature of the bound model (radius {radius} mm) has no dimension.",
                           region=view["frame"], feature=view["id"], expected=f"diameter {number_text(2 * radius)}", observed=None)
        if radii and all(radius in dimensioned for radius in radii):
            report.add("DIM-03", "pass", "info", f"View {view['id']}: each round feature of the bound model has a dimension.", feature=view["id"])
        round_views += bool(radii)
        model_views += 1
    if model_views and not round_views:
        report.add("DIM-03", "not_applicable", "info", "The bound model shows no round feature in an orthographic view.")


def check_datums(report: Report, raster: Raster, datums: list[dict]) -> None:
    """The datum symbols on the part: the triangle, the leader, and the square must be present. The letter is read by OCR."""
    for datum in datums:
        a, b = datum["leader"]
        leader = sample({"type": "line", "start": a, "end": b}, 0.2) if math.dist(a, b) > 0.3 else []
        x0, y0, x1, y1 = datum["box"]
        square = [p for edge in (([x0, y0], [x1, y0]), ([x1, y0], [x1, y1]), ([x1, y1], [x0, y1]), ([x0, y1], [x0, y0]))
                  for p in sample({"type": "line", "start": edge[0], "end": edge[1]}, 0.2)]
        triangle = datum["triangle"]
        centroid = [sum(p[0] for p in triangle) / 3, sum(p[1] for p in triangle) / 3]
        shares = {"leader": sum(raster.covered(leader)) / len(leader) if leader else 1.0,
                  "square": sum(raster.covered(square)) / len(square), "triangle": float(all(raster.covered([centroid])))}
        if min(shares.values()) >= 0.85:
            report.add("GPS-09", "pass", "info", f"Datum symbol {datum['letter']} is attached to its feature.", region=datum["box"],
                       feature="datum_" + datum["letter"], observed={key: round(value, 3) for key, value in shares.items()})
        else:
            report.add("GPS-09", "fail", "major", f"Datum symbol {datum['letter']} is missing or not attached to its feature.",
                       region=_bounds([*triangle, [x0, y0], [x1, y1]]), feature="datum_" + datum["letter"],
                       expected=">= 0.85 for leader, square, and triangle", observed={key: round(value, 3) for key, value in shares.items()})


def check_frames(report: Report, raster: Raster, frames: list[dict]) -> None:
    for frame in frames:
        if frame.get("symbol"):
            strokes = frame["symbol"]
            items = ([{"type": "line", "start": a, "end": b} for a, b in strokes["lines"]]
                     + [{"type": "circle", "center": c, "radius": r} for c, r in strokes["circles"]]
                     + [{"type": "arc", "center": c, "radius": r, "start_angle": a, "end_angle": b} for c, r, a, b in strokes["arcs"]])
            points = [p for item in items for p in sample(item, 0.2)]
            fraction = sum(raster.covered(points)) / len(points) if points else 0.0
            inner = frame["symbol_rect"]
            inset = [inner[0] + 0.5, inner[1] + 0.5, inner[2] - 0.5, inner[3] - 0.5]
            stray = raster.unexplained(inset, items, 0.35)
            circles = [{"type": "circle", "center": item["center"], "radius": item["radius"]} for item in frame.get("modifier_circles", [])]
            for circle in circles:
                points = sample(circle, 0.2)
                share = sum(raster.covered(points)) / len(points)
                if share < 0.85:
                    report.add("GPS-07", "fail", "major", f"Tolerance frame {frame['id']}: a modifier circle is missing.",
                               region=[circle["center"][0] - circle["radius"], circle["center"][1] - circle["radius"],
                                       circle["center"][0] + circle["radius"], circle["center"][1] + circle["radius"]],
                               feature=frame["id"], expected=">= 0.85", observed=round(share, 3))
            if fraction >= 0.85 and stray <= 0.6:
                report.add("GPS-05", "pass", "info", f"Tolerance frame {frame['id']} shows the symbol of {frame['characteristic']}.",
                           region=inner, feature=frame["id"], observed=round(fraction, 3))
            else:
                report.add("GPS-05", "fail", "major", f"Tolerance frame {frame['id']} does not show the symbol of {frame['characteristic']}.",
                           region=inner, feature=frame["id"], expected=frame["characteristic"],
                           observed={"symbol_coverage": round(fraction, 3), "unexplained_mm2": round(stray, 3)})
        ink = raster.ink_fraction(frame["rect"])
        if ink < 0.01:
            report.add("GPS-01", "fail", "major", f"Tolerance frame {frame['id']} is missing in the rendered PDF.", region=frame["rect"],
                       feature=frame["id"], observed=round(ink, 4))
        else:
            report.add("GPS-01", "pass" if frame["status"] == "pass" else "needs_review",
                       "info" if frame["status"] == "pass" else "minor",
                       f"Tolerance frame {frame['id']} is present." + ("" if frame["status"] == "pass" else
                                                                         " It is outside the supported GPS profile and needs review."),
                       region=frame["rect"], feature=frame["id"])


def preview(raster: Raster, report: Report, path: Path) -> dict:
    """A reduced copy of the raster with the regions of failed and review findings."""
    from PIL import ImageDraw

    scale = min(1.0, 2400 / max(raster.image.size))
    image = raster.image.resize((max(1, int(raster.image.size[0] * scale)), max(1, int(raster.image.size[1] * scale)))).convert("RGB")
    draw = ImageDraw.Draw(image)
    for number, item in enumerate(report.findings, 1):
        if item["status"] not in {"fail", "needs_review"} or not item["region_mm"]:
            continue
        x0, y0, x1, y1 = item["region_mm"]
        a = raster.pixel([x0, y1])
        b = raster.pixel([x1, y0])
        color = (220, 0, 0) if item["status"] == "fail" else (230, 140, 0)
        draw.rectangle([a[0] * scale - 4, a[1] * scale - 4, b[0] * scale + 4, b[1] * scale + 4], outline=color, width=3)
        draw.text((a[0] * scale, max(0, a[1] * scale - 14)), f"{number} {item['rule_id']}", fill=color)
    image.save(path, format="PNG")
    data = path.read_bytes()
    return {"name": path.name, "path": str(path), "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(), "role": "drawing_verification_preview"}


def verify(directory: Path, request: dict) -> dict:
    """Run the verification layers. The request comes from drawing_verification.build_request."""
    from .adapters.tesseract import Ocr

    report = Report()
    pdf = check_pdf(report, directory / "input.pdf", request["expected"], request.get("sheet"))
    size = request.get("sheet") or ({"width": pdf["page_size_mm"][0], "height": pdf["page_size_mm"][1], "margin": 10.0}
                                    if pdf["page_size_mm"] else None)
    tools = {"verifier": VERIFIER_VERSION}
    raster = None
    digest = hashlib.sha256((directory / "input.pdf").read_bytes()).hexdigest()
    if request.get("raster_pdf_sha256") and request["raster_pdf_sha256"] != digest:
        report.add("RENDER-04", "fail", "critical", "The raster was made from other PDF bytes than the verified PDF.",
                   expected=request["raster_pdf_sha256"], observed=digest)
    elif request.get("raster_pdf_sha256"):
        report.add("RENDER-04", "pass", "info", "The raster was made from the verified PDF bytes.", observed=digest)
    if size is not None and (directory / "input.png").is_file():
        raster = Raster(directory / "input.png", size["width"], size["height"], request["dpi"])
        check_raster(report, raster, request["pages_rendered"], pdf["pages"], size)
    else:
        report.add("RENDER-01", "fail", "critical", "No complete raster of the PDF exists. The PDF was not inspected.")
    views = request.get("views", [])
    check_views(report, views, request.get("required", {}))
    if request["mode"] == "unbound":
        for rule, reason in (("MODEL-01", "No bound model evidence exists for this PDF."),
                             ("DIM-02", "No bound drawing specification exists for this PDF."),
                             ("TEXT-01", "No bound drawing specification gives the expected texts.")):
            report.add(rule, "not_tested", "info", reason)
    elif raster is not None:
        derived = {}
        if (directory / "input.step").is_file():
            derived = check_model(report, raster, directory, views)
        else:
            report.add("MODEL-01", "not_tested", "info", "No bound model candidate was supplied.")
        check_dimensions(report, views, derived)
        check_dimension_lines(report, raster, request.get("dimension_lines", []))
        check_datums(report, raster, request.get("datums", []))
        if derived:
            check_extra_ink(report, raster, views, derived, request)
        check_frames(report, raster, request.get("frames", []))
        ocr = Ocr()
        try:
            tools["tesseract"] = ocr.version
            check_texts(report, raster, request.get("texts", []), ocr)
        finally:
            ocr.close()
    for rule, reason in request.get("service_findings", []):
        report.add(rule["rule_id"], rule["status"], rule["severity"], reason, expected=rule.get("expected"), observed=rule.get("observed"))
    present = {item["rule_id"] for item in report.findings}
    for rule in MANDATORY_RULES:
        if rule in present:
            continue
        if rule in ABSENT_REASONS and request["mode"] == "bound":
            report.add(rule, "not_applicable", "info", ABSENT_REASONS[rule])
        else:
            report.add(rule, "not_tested", "info", "The verifier did not run this mandatory rule for this PDF.")
    report.add("STYLE-01", "not_tested", "info", "Line types and line widths are not tested in the raster.")
    report.add("REVIEW-01", "not_tested", "info", "An identified review is not part of this report. Record it with drawing_review.")
    artifacts = [preview(raster, report, directory / "verification-preview.png")] if raster is not None else []
    body = {"schema_version": REPORT_SCHEMA, "verifier": VERIFIER, "verifier_version": VERIFIER_VERSION,
            "profile": request.get("profile"), "thresholds": THRESHOLDS, "dpi": request["dpi"], "tools": tools,
            "binding": request["expected"], "mode": request["mode"], "status": report.status(),
            "untested_rules": sorted({item["rule_id"] for item in report.findings if item["status"] == "not_tested"}),
            "findings": report.findings,
            "scope": "A pass is a result of the supported verification profile. It is not ISO conformity and not a manufacturing release."}
    path = directory / "verification-report.json"
    path.write_text(json.dumps(body, sort_keys=True, ensure_ascii=False, allow_nan=False, indent=2), encoding="utf-8")
    data = path.read_bytes()
    artifacts.append({"name": path.name, "path": str(path), "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(),
                      "role": "drawing_verification_report"})
    return {"status": "pass", "report": body, "artifacts": artifacts}
