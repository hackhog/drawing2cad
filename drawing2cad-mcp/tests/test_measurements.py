"""Test printed-reference calibration, observations, and source integrity."""

from copy import deepcopy
from hashlib import sha256
import math

from pypdf import PdfWriter
import pytest

from drawing2cad_mcp.pdf import PdfError, PdfService


@pytest.fixture
def fixture(tmp_path):
    path = tmp_path / "drawing.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=1200, height=900)
    writer.write(path)
    return PdfService((tmp_path,), tmp_path / "out", None), path


def refs():
    return [
        {"dimension_id": "D1", "printed_value_mm": 40, "p0": [20, 20], "p1": [100, 20],
         "evidence": "printed_dimension", "source_region": [0.1, 0.1, 0.2, 0.2]},
        {"dimension_id": "D2", "printed_value_mm": 30, "p0": [20, 40], "p1": [80, 40],
         "evidence": "printed_dimension", "source_region": [0.1, 0.3, 0.2, 0.4]},
    ]


def evidence(origin="vector"):
    return {"origin": origin, "view_id": "view-1", "source_region": [0.1, 0.1, 0.9, 0.9],
            "reason": "Measure the selected outline points."}


def test_vector_calibration_distance_and_source_immutability(fixture):
    service, path = fixture
    before = sha256(path.read_bytes()).hexdigest()
    result = service.calibrate(path, 1, refs())
    cal = result["calibration"]
    assert cal["mm_per_coordinate_unit"] == 0.5
    measured = service.measure_distance(path, 1, [20, 20], [100, 80], cal, evidence())
    assert measured["distance_mm"] == 50
    assert measured["status"] == "estimated"
    assert measured["source_sha256"] == before == sha256(path.read_bytes()).hexdigest()


def test_inconsistent_printed_dimensions_fail(fixture):
    service, path = fixture
    values = refs()
    values[1]["printed_value_mm"] = 32
    with pytest.raises(PdfError, match="inconsistent scales"):
        service.calibrate(path, 1, values)


@pytest.mark.parametrize("field", ["dimension_id", "source_region", "segment"])
def test_two_references_must_be_distinct(fixture, field):
    service, path = fixture
    values = refs()
    if field == "segment":
        values[1]["p0"], values[1]["p1"] = values[0]["p1"], values[0]["p0"]
    else:
        values[1][field] = values[0][field]
    with pytest.raises(PdfError, match="distinct dimensions"):
        service.calibrate(path, 1, values)


def test_pixel_crop_scale_and_bounds(fixture):
    service, path = fixture
    cal = service.calibrate(path, 1, refs(), coordinate_space="pixels", crop_context={
        "full_page_pixels": [1000, 800], "pixel_bbox": [100, 100, 300, 300],
    })["calibration"]
    measured = service.measure_distance(path, 1, [0, 0], [200, 0], cal, evidence("pixel_observation"))
    assert measured["distance_mm"] == 100
    with pytest.raises(PdfError, match="inside the registered crop"):
        service.measure_distance(path, 1, [0, 0], [201, 0], cal, evidence("pixel_observation"))


def test_measurements_reject_changed_source_and_forged_scale(fixture):
    service, path = fixture
    cal = service.calibrate(path, 1, refs())["calibration"]
    bad = deepcopy(cal)
    bad["mm_per_coordinate_unit"] = 10
    with pytest.raises(PdfError, match="scale does not match"):
        service.measure_distance(path, 1, [20, 20], [100, 20], bad, evidence())
    path.write_bytes(path.read_bytes() + b"\n% changed\n")
    with pytest.raises(PdfError, match="source hash or page"):
        service.measure_distance(path, 1, [20, 20], [100, 20], cal, evidence())


def test_measurements_require_matching_view_and_origin(fixture):
    service, path = fixture
    cal = service.calibrate(path, 1, refs())["calibration"]
    with pytest.raises(PdfError, match="view_id"):
        service.measure_distance(path, 1, [20, 20], [100, 20], cal, {**evidence(), "view_id": "view-2"})
    with pytest.raises(PdfError, match="origin"):
        service.measure_distance(path, 1, [20, 20], [100, 20], cal, evidence("pixel_observation"))


def test_measurement_rechecks_reference_page_bounds(fixture):
    service, path = fixture
    cal = service.calibrate(path, 1, refs())["calibration"]
    for reference in cal["references"]:
        reference["p0"][0] += 1000
        reference["p1"][0] += 1000
    with pytest.raises(PdfError, match="inside the displayed sheet"):
        service.measure_distance(path, 1, [20, 20], [100, 20], cal, evidence())


def test_circle_measurement_is_estimate_and_does_not_prove_hole(fixture):
    service, path = fixture
    cal = service.calibrate(path, 1, refs())["calibration"]
    points = [[50 + 20 * math.cos(t * math.pi / 4), 50 + 20 * math.sin(t * math.pi / 4)] for t in range(8)]
    result = service.measure_circle(path, 1, points, cal, evidence())
    assert result["diameter_mm"] == pytest.approx(20)
    assert result["center_in_input_coordinates"] == pytest.approx([50, 50])
    assert result["semantic_status"] == "unverified"
    assert result["relative_radial_error"] == pytest.approx(0, abs=1e-12)


@pytest.mark.parametrize("points", [[[20, 20], [40, 40], [60, 60]],
                                    [[20, 20], [40, 20], [40, 40], [20, 40], [30, 30]]])
def test_non_circular_or_collinear_samples_fail(fixture, points):
    service, path = fixture
    cal = service.calibrate(path, 1, refs())["calibration"]
    with pytest.raises(PdfError):
        service.measure_circle(path, 1, points, cal, evidence())


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), True])
def test_nonfinite_observations_are_rejected(fixture, bad):
    service, path = fixture
    values = refs()
    values[0]["p0"] = [bad, 10]
    with pytest.raises(PdfError, match="finite"):
        service.calibrate(path, 1, values)


def test_calibration_reports_all_reference_defects_together():
    from drawing2cad_mcp.measurements import MeasurementError, calibrate, calibration_defects
    equal = {"dimension_id": "a", "printed_value_mm": 20, "p0": [3, 4], "p1": [3, 4],
             "source_region": [0.5, 0.2, 0.4, 0.3], "evidence": "printed_dimension"}
    second = {**equal, "dimension_id": "b"}
    defects = calibration_defects([equal, second])
    assert [target for target, _ in defects] == ["/references/0/p1", "/references/0/source_region",
                                                 "/references/1/p1", "/references/1/source_region"]
    assert all("[3, 4]" not in message for _, message in defects)
    with pytest.raises(MeasurementError) as error:
        calibrate("a" * 64, 1, [equal, second])
    assert "/references/0/p1" in str(error.value) and "/references/1/source_region" in str(error.value)
    assert calibration_defects("not a list") == [] and calibration_defects([None, {"p0": "x"}]) == []
