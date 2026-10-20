"""Independent verification of final drawing PDF bytes: Poppler raster, model projections, OCR, and mutations."""

import hashlib
import math
import os
import shutil
import subprocess
from copy import deepcopy
from pathlib import Path

import pytest

pytest.importorskip("build123d")
pymupdf = pytest.importorskip("pymupdf")

from drawing2cad_mcp.adapters import tesseract  # noqa: E402
from drawing2cad_mcp.drafting import render_drawing  # noqa: E402
from drawing2cad_mcp.drawing_contract import drawing_validate  # noqa: E402
from drawing2cad_mcp.drawing_verification import build_request, build_unbound_request  # noqa: E402
from drawing2cad_mcp.pdf_verifier import verify  # noqa: E402
from test_drawing_render_v2 import flange_drawing  # noqa: E402
from test_view_derivation import candidate, flange  # noqa: E402

pytestmark = pytest.mark.skipif(not tesseract.capabilities()["available"] or not shutil.which("pdftoppm"),
                                reason="Tesseract or Poppler is not installed in this environment.")


@pytest.fixture(scope="module")
def drawing(tmp_path_factory):
    """The flange drawing, rendered once. The tests copy its files."""
    root = tmp_path_factory.mktemp("flange")
    description, spec = flange_drawing(root)
    out = root / "out"
    out.mkdir()
    result = render_drawing(spec, description, 1, out)
    assert result["status"] == "pass", result["defects"][:4]
    return {"description": description, "spec": spec, "pdf": out / "drawing.pdf", "step": root / "model" / "candidate.step",
            "dxf_sha256": result["dxf_sha256"]}


def run(tmp_path, pdf_bytes, *, step=None, spec=None, description=None, expected=None, unbound=False):
    directory = tmp_path / "work"
    directory.mkdir(parents=True)
    (directory / "input.pdf").write_bytes(pdf_bytes)
    rendered = subprocess.run(["pdftoppm", "-r", "300", "-gray", "-png", "-l", "8", str(directory / "input.pdf"), str(directory / "page")],
                              capture_output=True)
    pages = sorted(directory.glob("page-*.png"))
    if pages:
        pages[0].rename(directory / "input.png")
    if step is not None:
        shutil.copy(step, directory / "input.step")
    if unbound:
        request = build_unbound_request(expected or {"pdf_sha256": hashlib.sha256(pdf_bytes).hexdigest(), "part_revision": None,
                                                     "description_sha256": None, "dxf_sha256": None}, len(pages))
    else:
        resolved = drawing_validate(spec, description, 1)["resolved"]
        request = build_request(resolved, expected, len(pages) if rendered.returncode == 0 else 0)
    return verify(directory, request)["report"]


def expected_for(drawing, pdf_bytes, **changes):
    return {"pdf_sha256": hashlib.sha256(pdf_bytes).hexdigest(), "part_revision": 1,
            "description_sha256": drawing["spec"]["description_sha256"], "dxf_sha256": drawing["dxf_sha256"], **changes}


def by_rule(report, rule, status=None):
    return [item for item in report["findings"] if item["rule_id"] == rule and (status is None or item["status"] == status)]


def mutate(pdf_path, action) -> bytes:
    with pymupdf.open(pdf_path) as document:
        page = document[0]
        action(page, page.rect.width / 420)
        return document.tobytes()


def white(page, k, box):
    """Cover a sheet region (mm, bottom-left origin) with white."""
    x0, y0, x1, y1 = box
    page.draw_rect(pymupdf.Rect(x0 * k, (297 - y1) * k, x1 * k, (297 - y0) * k), color=None, fill=(1, 1, 1), overlay=True)


def test_correct_flange_drawing_passes_each_layer(drawing, tmp_path):
    data = drawing["pdf"].read_bytes()
    report = run(tmp_path, data, step=drawing["step"], spec=drawing["spec"], description=drawing["description"],
                 expected=expected_for(drawing, data))
    failed = [item for item in report["findings"] if item["status"] == "fail"]
    assert not failed, failed[:6]
    # The frame outside the GPS profile keeps the result at needs_review.
    assert report["status"] == "needs_review"
    for rule in ("PDF-INTEGRITY-01", "PDF-BIND-01", "RENDER-01", "RENDER-02", "RENDER-03", "VIEW-REQ-01", "VIEW-REQ-02", "ISO-01",
                 "MODEL-01", "MODEL-03", "MODEL-04", "DIM-01", "DIM-02", "DIM-03", "SEC-01", "GPS-02", "GPS-03", "UNITS-01", "REV-02"):
        assert by_rule(report, rule, "pass"), rule
    assert {"STYLE-01", "REVIEW-01"} <= set(report["untested_rules"])
    assert report["tools"]["tesseract"].startswith("5.")


def test_model_mutations_produce_findings(drawing, tmp_path):
    data = drawing["pdf"].read_bytes()
    expected = expected_for(drawing, data)

    def against(change, name):
        description = flange()
        change(description)
        step = candidate(description, tmp_path / name)
        directory = tmp_path / ("check_" + name)
        directory.mkdir()
        return run(directory, data, step=step, spec=drawing["spec"], description=drawing["description"], expected=expected)

    # The model has a hole that the drawing does not show.
    extra = against(lambda d: d["features"].append({"id": "extra", "type": "hole", "position": [-38, 0, 12], "diameter": 8,
                                                     "extent": "through", "axis": "-Z", "evidence_ids": ["drawing"]}), "extra_hole")
    assert by_rule(extra, "MODEL-01", "fail") and by_rule(extra, "DIM-03", "fail")
    # The bolt holes of the model are larger than drawn and dimensioned.
    larger = against(lambda d: [f.update(diameter=12) for f in d["features"] if f["id"].startswith("bolt")], "bolt_diameter")
    assert by_rule(larger, "MODEL-01", "fail") and by_rule(larger, "DIM-02", "fail")
    # The bore of the model is larger: the section and the bore dimension disagree.
    bore = against(lambda d: [f.update(diameter=34) for f in d["features"] if f["id"] == "bore"], "bore")
    assert by_rule(bore, "MODEL-03", "fail") and by_rule(bore, "DIM-02", "fail")
    # A bolt hole of the model moved: the dimension anchor is not on the model.
    moved = against(lambda d: [f["position"].__setitem__(0, f["position"][0] + 3) for f in d["features"] if f["id"] == "bolt0"], "moved")
    assert by_rule(moved, "DIM-02", "fail")


def test_wrong_hole_depth_fails(tmp_path):
    def blind(depth):
        """The bore becomes a blind hole from the hub face."""
        description = flange()
        next(f for f in description["features"] if f["id"] == "bore").update(extent="blind", depth=depth)
        return description

    (tmp_path / "drawn").mkdir()
    source, spec = flange_drawing(tmp_path / "drawn", blind(20))
    out = tmp_path / "out"
    out.mkdir()
    result = render_drawing(spec, source, 1, out)
    assert result["status"] == "pass", result["defects"][:4]
    data = (out / "drawing.pdf").read_bytes()
    step = candidate(blind(26), tmp_path / "deeper")
    report = run(tmp_path, data, step=step, spec=spec, description=source,
                 expected={"pdf_sha256": hashlib.sha256(data).hexdigest(), "part_revision": 1,
                           "description_sha256": spec["description_sha256"], "dxf_sha256": result["dxf_sha256"]})
    assert any(item["feature"] == "front" for item in by_rule(report, "MODEL-02", "fail"))


def test_pdf_mutations_fail_after_final_byte_rendering(drawing, tmp_path):
    spec, description = drawing["spec"], drawing["description"]
    # A removed bore dimension (Ø30 at the bottom of the top view).
    removed = mutate(drawing["pdf"], lambda page, k: white(page, k, [100, 128, 116, 148]))
    report = run(tmp_path / "removed", removed, spec=spec, description=description, expected=expected_for(drawing, removed))
    assert any(item["feature"] == "d_bore" for item in by_rule(report, "DIM-01", "fail"))
    # Wrong units in the title block.
    def units(page, k):
        white(page, k, [230, 10, 259, 15])
        page.insert_text(((230 + 1) * k, (297 - 11.5) * k), "in", fontsize=2.5 * k / 0.72 * 0.72 * 2.8)
    wrong = mutate(drawing["pdf"], units)
    report = run(tmp_path / "units", wrong, spec=spec, description=description, expected=expected_for(drawing, wrong))
    assert by_rule(report, "UNITS-01", "fail")
    # Content at the page edge is clipped.
    def edge(page, k):
        page.draw_line(pymupdf.Point(2, 20 * k), pymupdf.Point(2, 60 * k), color=(0, 0, 0), width=2)
    clipped = mutate(drawing["pdf"], edge)
    report = run(tmp_path / "edge", clipped, spec=spec, description=description, expected=expected_for(drawing, clipped))
    assert by_rule(report, "RENDER-03", "fail")
    # A blank page and malformed bytes.
    blank = pymupdf.open()
    blank.new_page(width=420 / 25.4 * 72, height=297 / 25.4 * 72)
    blank_bytes = blank.tobytes()
    report = run(tmp_path / "blank", blank_bytes, spec=spec, description=description, expected=expected_for(drawing, blank_bytes))
    assert by_rule(report, "RENDER-02", "fail") and report["status"] == "fail"
    broken = b"%PDF-1.7\nnot a pdf"
    report = run(tmp_path / "broken", broken, spec=spec, description=description, expected=expected_for(drawing, broken))
    assert by_rule(report, "PDF-STRUCT-01", "fail") and by_rule(report, "RENDER-01", "fail")


def test_changed_bytes_and_stale_revision_fail(drawing, tmp_path):
    data = drawing["pdf"].read_bytes()
    changed = mutate(drawing["pdf"], lambda page, k: page.draw_rect(pymupdf.Rect(100, 100, 101, 101), color=(0, 0, 0)))
    report = run(tmp_path / "bytes", changed, spec=drawing["spec"], description=drawing["description"], expected=expected_for(drawing, data))
    assert by_rule(report, "PDF-INTEGRITY-01", "fail")
    report = run(tmp_path / "revision", data, spec=drawing["spec"], description=drawing["description"],
                 expected=expected_for(drawing, data, part_revision=2))
    assert by_rule(report, "PDF-BIND-01", "fail")


def test_unbound_pdf_fails_required_views_and_does_not_test_the_model(drawing, tmp_path):
    data = drawing["pdf"].read_bytes()
    report = run(tmp_path, data, unbound=True)
    assert by_rule(report, "VIEW-REQ-01", "fail") and by_rule(report, "VIEW-REQ-02", "fail")
    assert by_rule(report, "MODEL-01", "not_tested")


@pytest.mark.skipif(not os.environ.get("DRAWING2CAD_FLANGE_PDF"), reason="The supplied flange PDF is not given (DRAWING2CAD_FLANGE_PDF).")
def test_supplied_flange_pdf_fails_required_views(tmp_path):
    data = Path(os.environ["DRAWING2CAD_FLANGE_PDF"]).read_bytes()
    report = run(tmp_path, data, unbound=True)
    assert by_rule(report, "VIEW-REQ-01", "fail") and by_rule(report, "VIEW-REQ-02", "fail")
    assert by_rule(report, "MODEL-01", "not_tested")
    assert report["status"] == "fail"


def test_verification_runs_in_the_verified_sandbox(drawing, tmp_path):
    from drawing2cad_mcp.worker_runner import WorkerRunner

    runner = WorkerRunner(tmp_path / "workers")
    capability = runner.capabilities()
    if os.environ.get("DRAWING2CAD_REQUIRE_SANDBOX") == "1":
        assert capability["available"], capability
    if not capability["available"]:
        pytest.skip("The verified Linux sandbox is unavailable.")
    rendered = runner.run("render_pdf_poppler", input_pdf=drawing["pdf"])
    assert rendered["status"] == "pass", rendered
    data = drawing["pdf"].read_bytes()
    resolved = drawing_validate(drawing["spec"], drawing["description"], 1)["resolved"]
    request = build_request(resolved, expected_for(drawing, data), len(rendered["pages"]))
    result = runner.run("verify_drawing_pdf", input_pdf=drawing["pdf"], input_image=Path(rendered["pages"][0]["path"]),
                        input_step=drawing["step"], verification=request, timeout=240)
    assert result["status"] == "pass", result
    assert result["sandbox"] and result["report"]["status"] == "needs_review"
    assert not [item for item in result["report"]["findings"] if item["status"] == "fail"]
