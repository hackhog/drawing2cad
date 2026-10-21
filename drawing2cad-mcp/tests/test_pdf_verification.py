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


def run(tmp_path, pdf_bytes, *, step=None, spec=None, description=None, expected=None, unbound=False, raster_sha=None):
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
    if raster_sha is not None:
        request["raster_pdf_sha256"] = raster_sha
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


def layout_of(drawing):
    return drawing_validate(drawing["spec"], drawing["description"], 1)["resolved"]["layout"]


def test_extra_geometry_in_the_pdf_fails(drawing, tmp_path):
    def circle(page, k):
        page.draw_circle(pymupdf.Point(64 * k, (297 - 193) * k), 3 * k, color=(0, 0, 0), width=0.5)
    data = mutate(drawing["pdf"], circle)
    report = run(tmp_path, data, step=drawing["step"], spec=drawing["spec"], description=drawing["description"],
                 expected=expected_for(drawing, data))
    assert any(item["feature"] == "top" for item in by_rule(report, "MODEL-05", "fail"))


def test_critical_values_need_their_exact_number_and_qualifier():
    from drawing2cad_mcp.pdf_verifier import text_matches

    assert text_matches("Ø10", "-810", True) and text_matches("Ø10", "@10-", True) and text_matches("Ø10", "Ø10", True)
    assert not text_matches("Ø10", "210", True) and not text_matches("Ø10", "10", True) and not text_matches("Ø10", "Ø10.5", True)
    assert text_matches("R5", "R5", True) and not text_matches("R5", "5", True)
    assert text_matches("1:1, 1:1.25", "1:1, 1:1.25", True) and not text_matches("1:1", "1:10", True)
    assert not text_matches("0.1", "0.1 ± 0.9", True) and not text_matches("A", "AB", True)


def test_changed_frame_semantics_fail(drawing, tmp_path):
    frames = {item["id"]: item for item in layout_of(drawing)["frames"]}
    compartments = frames["bolt_position"]["layout"]["compartments"]
    symbol = next(item for item in compartments if item["kind"] == "symbol")["rect"]
    datum = next(item for item in compartments if item["kind"] == "datum")

    def change(page, k):
        # Replace the position symbol with a flatness-like stroke, and datum A with B.
        white(page, k, [symbol[0] + 0.4, symbol[1] + 0.4, symbol[2] - 0.4, symbol[3] - 0.4])
        page.draw_line(pymupdf.Point((symbol[0] + 1.5) * k, (297 - (symbol[1] + 2)) * k),
                       pymupdf.Point((symbol[2] - 1.5) * k, (297 - (symbol[3] - 2)) * k), color=(0, 0, 0), width=0.6)
        x0, y0, x1, y1 = datum["rect"]
        white(page, k, [x0 + 0.4, y0 + 0.4, x1 - 0.4, y1 - 0.4])
        page.insert_text(((x0 + 1.2) * k, (297 - (y0 + 1.6)) * k), "B", fontsize=9)
    data = mutate(drawing["pdf"], change)
    report = run(tmp_path, data, spec=drawing["spec"], description=drawing["description"], expected=expected_for(drawing, data))
    assert any(item["feature"] == "bolt_position" for item in by_rule(report, "GPS-05", "fail"))
    assert any(item["feature"] == "bolt_position" for item in by_rule(report, "GPS-06", "fail"))


def test_removed_dimension_lines_fail(drawing, tmp_path):
    from drawing2cad_mcp.drawing_verification import _dimension_lines

    resolved = drawing_validate(drawing["spec"], drawing["description"], 1)["resolved"]
    top = next(view for view in resolved["views"] if view["id"] == "top")
    hub = next(item for item in _dimension_lines(top, 2.5) if item["id"] == "d_hub")
    a, b = hub["segments"][0]

    def erase(page, k):
        white(page, k, [min(a[0], b[0]) - 0.8, min(a[1], b[1]) - 0.8, max(a[0], b[0]) + 0.8, max(a[1], b[1]) + 0.8])
    data = mutate(drawing["pdf"], erase)
    report = run(tmp_path, data, spec=drawing["spec"], description=drawing["description"], expected=expected_for(drawing, data))
    assert any(item["feature"] == "d_hub" for item in by_rule(report, "DIM-05", "fail"))


def test_encrypted_pdf_fails_with_a_report(drawing, tmp_path):
    with pymupdf.open(drawing["pdf"]) as document:
        data = document.tobytes(encryption=pymupdf.PDF_ENCRYPT_AES_256, owner_pw="owner", user_pw="user")
    report = run(tmp_path, data, spec=drawing["spec"], description=drawing["description"], expected=expected_for(drawing, data))
    assert by_rule(report, "PDF-STRUCT-01", "fail") and report["status"] == "fail"


def test_datum_symbols_and_modifier_circles_must_be_present(drawing, tmp_path):
    layout = layout_of(drawing)
    datum = layout["datums"][0]
    frame = next(item for item in layout["frames"] if item["id"] == "bolt_position")
    circle = next(c for item in frame["layout"]["compartments"] for c in item.get("circles", []))

    def erase(page, k):
        a, b = datum["leader"]
        white(page, k, [min(a[0], b[0]) - 0.6, min(a[1], b[1]) - 0.6, max(a[0], b[0]) + 0.6, max(a[1], b[1]) + 0.6])
        x0, y0, x1, y1 = datum["box"]
        white(page, k, [x0 + 0.6, y0 + 0.6, x1 - 0.6, y1 - 0.6])
        cx, cy = circle["center"]
        page.draw_circle(pymupdf.Point(cx * k, (297 - cy) * k), circle["radius"] * k + 0.6, color=(1, 1, 1), width=2.2)
    data = mutate(drawing["pdf"], erase)
    report = run(tmp_path, data, spec=drawing["spec"], description=drawing["description"], expected=expected_for(drawing, data))
    assert by_rule(report, "GPS-09", "fail") and by_rule(report, "GPS-08", "fail") and by_rule(report, "GPS-07", "fail")


def test_one_missing_extension_line_fails(drawing, tmp_path):
    from drawing2cad_mcp.drawing_verification import _dimension_lines

    resolved = drawing_validate(drawing["spec"], drawing["description"], 1)["resolved"]
    front = next(view for view in resolved["views"] if view["id"] == "front")
    height = next(item for item in _dimension_lines(front, 2.5) if item["id"] == "h_total")
    a, b = height["segments"][0]

    def erase(page, k):
        white(page, k, [min(a[0], b[0]) - 0.6, min(a[1], b[1]) - 0.6, max(a[0], b[0]) + 0.6, max(a[1], b[1]) + 0.6])
    data = mutate(drawing["pdf"], erase)
    report = run(tmp_path, data, spec=drawing["spec"], description=drawing["description"], expected=expected_for(drawing, data))
    assert any(item["feature"] == "h_total" for item in by_rule(report, "DIM-05", "fail"))


def test_extra_geometry_inside_a_hatched_surface_fails(drawing, tmp_path):
    # The section shows the disc from x = 40..50 mm left of the bore; its cut surface is hatched (sheet x 240..250, y 80..92).
    def circle(page, k):
        page.draw_circle(pymupdf.Point(245 * k, (297 - 86) * k), 2.5 * k, color=(0, 0, 0), width=0.5)
    data = mutate(drawing["pdf"], circle)
    report = run(tmp_path, data, step=drawing["step"], spec=drawing["spec"], description=drawing["description"],
                 expected=expected_for(drawing, data))
    assert any(item["feature"] == "section_a" for item in by_rule(report, "MODEL-05", "fail")), by_rule(report, "MODEL-05")


def test_raster_of_other_bytes_and_prefix_revision_fail(drawing, tmp_path):
    data = drawing["pdf"].read_bytes()
    report = run(tmp_path / "raster", data, spec=drawing["spec"], description=drawing["description"],
                 expected=expected_for(drawing, data), raster_sha="0" * 64)
    assert by_rule(report, "RENDER-04", "fail")

    def keywords(document):
        metadata = document.metadata
        metadata["keywords"] = metadata["keywords"].replace("part_revision:1;", "part_revision:10;")
        document.set_metadata(metadata)
    with pymupdf.open(drawing["pdf"]) as document:
        keywords(document)
        changed = document.tobytes()
    report = run(tmp_path / "meta", changed, spec=drawing["spec"], description=drawing["description"], expected=expected_for(drawing, changed))
    assert by_rule(report, "PDF-BIND-01", "fail")


def test_a_removed_note_fails(drawing, tmp_path):
    spec = deepcopy(drawing["spec"])
    spec["notes"] = [{"text": "Remove sharp edges", "position": [25, 30], "evidence_ids": ["drawing"]}]
    description = drawing["description"]
    out = tmp_path / "out"
    out.mkdir()
    result = render_drawing(spec, description, 1, out)
    assert result["status"] == "pass", result["defects"][:4]
    removed = mutate(out / "drawing.pdf", lambda page, k: white(page, k, [24, 28, 80, 35]))
    expected = {"pdf_sha256": hashlib.sha256(removed).hexdigest(), "part_revision": 1, "description_sha256": spec["description_sha256"],
                "dxf_sha256": result["dxf_sha256"]}
    report = run(tmp_path, removed, spec=spec, description=description, expected=expected)
    assert any(item["feature"] == "note_0" for item in by_rule(report, "TEXT-03", "fail"))
    intact = (out / "drawing.pdf").read_bytes()
    report = run(tmp_path / "intact", intact, spec=spec, description=description, expected={**expected, "pdf_sha256": hashlib.sha256(intact).hexdigest()})
    assert by_rule(report, "TEXT-03", "pass")


def test_the_correct_flange_passes_the_acceptance_gate_after_its_review_decisions(drawing, tmp_path):
    from drawing2cad_mcp.drawing_verification import PROFILE, gate, record
    from drawing2cad_mcp.pdf_verifier import MANDATORY_RULES

    data = drawing["pdf"].read_bytes()
    report = run(tmp_path, data, step=drawing["step"], spec=drawing["spec"], description=drawing["description"],
                 expected={**expected_for(drawing, data)}, raster_sha=hashlib.sha256(data).hexdigest())
    # Each mandatory rule has a finding: a result, or not_applicable with its reason.
    assert {item["rule_id"] for item in report["findings"]} >= set(MANDATORY_RULES)
    assert not [item for item in report["findings"] if item["rule_id"] in MANDATORY_RULES and item["status"] == "not_tested"]
    stored = {**record(report, {}, []), "validity": "current"}
    assert stored["profile"] == PROFILE
    open_items = [item for item in stored["findings"] if item["status"] == "needs_review"]
    assert open_items and not gate(stored, [])["passed"]
    decisions = [{"rule_id": item["rule_id"], "feature": item["feature"], "reason": "Reviewed."} for item in open_items]
    assert gate(stored, decisions)["passed"]


def test_each_dimension_states_the_model_value(drawing, tmp_path):
    data = drawing["pdf"].read_bytes()
    report = run(tmp_path, data, step=drawing["step"], spec=drawing["spec"], description=drawing["description"],
                 expected=expected_for(drawing, data))
    values = {item["feature"]: item for item in by_rule(report, "DIM-06")}
    assert len(values) == 8 and all(item["status"] == "pass" for item in values.values()), [
        (key, item["message"]) for key, item in values.items() if item["status"] != "pass"]
    height = values["h_total"]["observed"]
    assert height["model"] == 32 and height["declared"] == 32 and height["observed"] and height["unit"] == "mm"
    assert "GPS-10" in report["untested_rules"]


def test_a_dimension_that_differs_from_the_step_fails_also_with_the_same_wrong_specification(drawing, tmp_path):
    # The drawing and its specification agree with each other (height 32), but the bound STEP has a hub of 24 mm (height 36).
    description = flange()
    next(f for f in description["features"] if f["id"] == "hub")["height"] = 24
    next(f for f in description["features"] if f["id"] == "bore")["position"][2] = 36
    description["measurements"][0]["expected"] = [100, 100, 36]
    step = candidate(description, tmp_path / "taller")
    data = drawing["pdf"].read_bytes()
    report = run(tmp_path, data, step=step, spec=drawing["spec"], description=drawing["description"], expected=expected_for(drawing, data))
    height = next(item for item in by_rule(report, "DIM-06") if item["feature"] == "h_total")
    assert height["status"] == "fail" and height["observed"]["model"] == 36 and height["observed"]["declared"] == 32


def test_dimension_values_in_synthetic_views():
    from drawing2cad_mcp.pdf_verifier import Report, check_dimension_values

    true_size = {"scale_convention": "true_size"}
    model = {"geometry": [{"type": "line", "style": "visible", "start": [0, 0], "end": [40, 0], "id": "a"},
                          {"type": "line", "style": "visible", "start": [0, 0], "end": [0, 25], "id": "b"}]}
    base = {"evidence_ids": ["drawing"]}
    length = {**base, "id": "length", "type": "linear", "axis": "horizontal", "p1": [0, 0], "p2": [38, 0], "expected": 38}
    angle = {**base, "id": "angle", "type": "angular", "center": [0, 0], "p1": [40, 0], "p2": [0, 25], "expected": 90}
    report = Report()
    report.add("DIM-01", "pass", "info", "read", feature="length", observed="38")
    report.add("DIM-01", "pass", "info", "read", feature="angle", observed="90°")
    views = [{"id": "front", "kind": "orthographic", "projection": true_size, "frame": [0, 0, 50, 50], "dimensions": [length, angle]},
             {"id": "iso", "kind": "isometric", "projection": {"scale_convention": "isometric_drawing"}, "frame": [0, 0, 50, 50],
              "dimensions": [{**length, "id": "iso_length", "p2": [40, 0], "expected": 40}]}]
    check_dimension_values(report, views, {"front": model, "iso": model})
    results = {item["feature"]: item for item in report.findings if item["rule_id"] == "DIM-06"}
    # The specification declares 38 mm, the model has 40 mm: the length fails although the specification agrees with itself.
    assert results["length"]["status"] == "fail" and results["length"]["observed"]["model"] == 40
    assert results["angle"]["status"] == "pass" and results["angle"]["observed"]["model"] == 90
    assert results["iso_length"]["status"] == "fail" and "not true size" in results["iso_length"]["message"]


def _rectangle(width, height):
    corners = [[0, 0], [width, 0], [width, height], [0, height]]
    return [{"type": "line", "style": "visible", "start": corners[i], "end": corners[(i + 1) % 4], "id": f"e{i}"} for i in range(4)]


def test_dimension_values_with_anchors_inside_edges_and_concentric_circles():
    from drawing2cad_mcp.pdf_verifier import Report, check_dimension_values

    base = {"evidence_ids": ["drawing"]}
    width = {**base, "id": "width", "type": "linear", "axis": "horizontal", "p1": [0, 10], "p2": [40, 10], "expected": 40}
    tangent = {**base, "id": "tangent", "type": "linear", "axis": "horizontal", "p1": [0, 10], "p2": [25, 10], "expected": 25}
    leg = {**base, "id": "leg", "type": "angular", "center": [0, 0], "p1": [20, 0], "p2": [0, 10], "expected": 90}
    bore = {**base, "id": "bore", "type": "radius", "center": [0, 0], "radius": 10, "expected": 10}
    circles = [{"type": "circle", "style": "visible", "center": [20, 10], "radius": 5, "id": "hole"},
               {"type": "circle", "style": "visible", "center": [0.0000001, 0], "radius": 10, "id": "inner"},
               {"type": "circle", "style": "visible", "center": [0, 0], "radius": 20, "id": "outer"}]
    view = {"id": "front", "kind": "orthographic", "projection": {"scale_convention": "true_size"}, "frame": [0, 0, 50, 50],
            "dimensions": [width, tangent, leg, bore]}

    def run(geometry, declared_width=40):
        report = Report()
        for feature in ("width", "tangent", "leg", "bore"):
            report.add("DIM-01", "pass", "info", "read", feature=feature, observed="x")
        check_dimension_values(report, [{**view, "dimensions": [{**width, "expected": declared_width}, tangent, leg, bore]}],
                               {"front": {"geometry": geometry}})
        return {item["feature"]: item for item in report.findings if item["rule_id"] == "DIM-06"}

    # Anchors inside the vertical edges and at the extreme point of a hole: the correct values pass.
    results = run(_rectangle(40, 20) + circles)
    assert all(results[name]["status"] == "pass" for name in ("width", "tangent", "leg", "bore")), results
    assert results["width"]["observed"]["model"] == 40 and results["tangent"]["observed"]["model"] == 25
    # A model of 36 mm width: the anchor inside the edge snaps to the real edge, and the declared 40 mm fails.
    results = run(_rectangle(36, 20) + circles)
    assert results["width"]["status"] == "fail" and results["width"]["observed"]["model"] == 36


def test_dimension_values_with_midpoints_ellipses_and_leg_directions():
    from drawing2cad_mcp.pdf_verifier import Report, check_dimension_values

    base = {"evidence_ids": ["drawing"]}
    # From the midpoint of the bottom edge to the midpoint of the right edge: 20 mm.
    half = {**base, "id": "half", "type": "linear", "axis": "horizontal", "p1": [20, 0], "p2": [40, 10], "expected": 20}
    # The legs are an edge that starts 0.04 mm above the vertex and a vertical edge: the model angle is 90 degrees,
    # also when the leg anchors give 89.54 degrees from the vertex.
    skew = {**base, "id": "skew", "type": "angular", "center": [0, 0], "p1": [5, 0.04], "p2": [0, 5], "expected": 89.54164354}
    ellipse = {"type": "ellipse", "style": "visible", "center": [20, 10], "major_axis": [4, 0], "ratio": 0.5,
               "start_parameter": 0, "end_parameter": 360, "id": "oblique_hole"}
    geometry = [{"type": "line", "style": "visible", "start": [0, 0], "end": [40, 0], "id": "bottom"},
                {"type": "line", "style": "visible", "start": [40, 0], "end": [40, 20], "id": "right"},
                {"type": "line", "style": "visible", "start": [0, 0.04], "end": [10, 0.04], "id": "ledge"},
                {"type": "line", "style": "visible", "start": [0, 0], "end": [0, 10], "id": "left"}, ellipse]
    report = Report()
    for feature in ("half", "skew"):
        report.add("DIM-01", "pass", "info", "read", feature=feature, observed="x")
    view = {"id": "front", "kind": "orthographic", "projection": {"scale_convention": "true_size"}, "frame": [0, 0, 50, 50],
            "dimensions": [half, skew]}
    # The ellipse in the view does not stop the check.
    check_dimension_values(report, [view], {"front": {"geometry": geometry}})
    results = {item["feature"]: item for item in report.findings if item["rule_id"] == "DIM-06"}
    assert results["half"]["status"] == "pass" and results["half"]["observed"]["model"] == 20
    assert results["skew"]["status"] == "fail" and results["skew"]["observed"]["model"] == 90
