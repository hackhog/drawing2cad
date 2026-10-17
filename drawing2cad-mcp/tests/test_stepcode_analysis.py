"""Actual independent schema-reader and nominal graph tests in fresh workers."""

from copy import deepcopy
from hashlib import sha256
import os
from pathlib import Path
import re
import sys

import pytest

from drawing2cad_mcp.adapters.stepcode import capabilities
from drawing2cad_mcp.adapters.stepcode_pmi import verify_nominal_pmi
from drawing2cad_mcp.worker_runner import WorkerLimits, WorkerRunner


@pytest.fixture(scope="module")
def external_case(tmp_path_factory):
    if sys.platform != "linux" or not capabilities()["available"]:
        if os.environ.get("DRAWING2CAD_REQUIRE_STEPCODE") == "1":
            pytest.fail("The required independent STEPcode analyzer is unavailable.")
        pytest.skip("The independent STEPcode executable requires its Linux image.")
    from test_semantic_pmi import cylinder_case
    storage = tmp_path_factory.mktemp("stepcode-analysis")
    runner = WorkerRunner(storage, WorkerLimits(timeout_seconds=60))
    description, specification = cylinder_case()
    built = runner.run("build", description=description, export_profile="ap242", pmi=specification)
    assert built["status"] == "pass", built
    path = Path(built["candidate_step"])
    expected = [{"id": "diameter", "kind": "diameter", "value": 20},
                {"id": "height", "kind": "linear", "value": 30}]
    return runner, path, expected, description["name"], storage


def test_independent_schema_and_nominal_graph(external_case):
    runner, path, expected, name, _ = external_case
    report = runner.run("analyze_ap242", input_step=path)
    assert report["status"] == "pass", report
    assert report["input_sha256"] == sha256(path.read_bytes()).hexdigest()
    assert report["analyzer"] == "STEPcode"
    assert report["sandbox"]["profile"] == "linux-landlock-seccomp-v1"
    assert report["source_revision"] == capabilities()["source_revision"]
    assert report["schema_sha256"] == capabilities()["schema_sha256"]
    assert report["read_severity"] == report["verify_severity"] == 3
    assert report["entity_count"] > 100
    statuses = {row["check"]: row["status"] for row in report["checks"]}
    assert statuses["independent_ap242_schema_read"] == "pass"
    assert statuses["full_express_validation"] == "not_tested"
    assert statuses["exact_edition_conformance"] == "not_tested"
    checked = verify_nominal_pmi(report, expected, name)
    assert checked["status"] == "pass", checked
    assert sorted(row["value"] for row in checked["dimensions"]) == [20, 30]
    assert sorted(len(row["face_entities"]) for row in checked["dimensions"]) == [1, 2]
    truncated = deepcopy(report)
    truncated["pmi_inventory_complete"] = False
    assert verify_nominal_pmi(truncated, expected, name)["status"] == "fail"
    assert verify_nominal_pmi(report, expected, "wrong product")["status"] == "fail"


def _mutate(text, case):
    if case == "wrong_nominal":
        return text.replace("POSITIVE_LENGTH_MEASURE(20.)", "POSITIVE_LENGTH_MEASURE(21.)", 1)
    if case == "wrong_unit":
        return text.replace("SI_UNIT(.MILLI.,.METRE.)", "SI_UNIT(.CENTI.,.METRE.)", 1)
    if case == "wrong_identifier":
        return re.sub(r"(DESCRIPTIVE_REPRESENTATION_ITEM\(\s*'drawing2cad dimension id',\s*)'diameter'", r"\1'unknown'", text, count=1)
    if case == "missing_required":
        return re.sub(r"DIMENSIONAL_SIZE\(#[0-9]+,", "DIMENSIONAL_SIZE($,", text, count=1)
    if case == "unknown_entity":
        return text.replace("DIMENSIONAL_SIZE(", "UNSUPPORTED_DIMENSION(", 1)
    if case == "dangling_reference":
        return re.sub(r"DIMENSIONAL_SIZE\(#[0-9]+,", "DIMENSIONAL_SIZE(#999999,", text, count=1)
    if case == "wrong_type_reference":
        point = re.search(r"#([0-9]+) = CARTESIAN_POINT", text)[1]
        return re.sub(r"DIMENSIONAL_SIZE\(#[0-9]+,", f"DIMENSIONAL_SIZE(#{point},", text, count=1)
    if case in {"detached_product", "unsupported_datum"}:
        aspect = re.search(r"SHAPE_ASPECT\('','',#([0-9]+),\.T\.\)", text)
        shape_id = aspect[1]
        fresh_id = max(map(int, re.findall(r"#([0-9]+)\s*=", text))) + 1
        if case == "unsupported_datum":
            added = f"#{fresh_id}=DATUM_FEATURE('','',#{shape_id},.T.);\n"
        else:
            source = re.search(rf"#{shape_id}\s*=\s*(PRODUCT_DEFINITION_SHAPE\([^;]+;)", text)[1]
            added = f"#{fresh_id}={source}\n"
            text = text.replace(aspect[0], aspect[0].replace(f"#{shape_id}", f"#{fresh_id}"), 1)
        return text.replace("ENDSEC;\nEND-ISO-10303-21;", added + "ENDSEC;\nEND-ISO-10303-21;")
    raise AssertionError(case)


@pytest.mark.parametrize("case", ["wrong_nominal", "wrong_unit", "wrong_identifier", "missing_required",
                                  "unknown_entity", "dangling_reference", "wrong_type_reference",
                                  "detached_product", "unsupported_datum"])
def test_actual_mutations_fail_independent_checks(external_case, case):
    runner, path, expected, name, storage = external_case
    original = path.read_text()
    changed = _mutate(original, case)
    assert changed != original, "The test must change the actual export."
    candidate = storage / (case + ".step")
    candidate.write_text(changed)
    report = runner.run("analyze_ap242", input_step=candidate)
    if case in {"missing_required", "unknown_entity", "dangling_reference", "wrong_type_reference"}:
        assert report["status"] == "fail", report
    else:
        assert report["status"] == "pass", report
        checked = verify_nominal_pmi(report, expected, name)
        assert checked["status"] == "fail", checked


def test_failed_parser_cannot_pass_semantics():
    assert verify_nominal_pmi({"status": "fail"})["status"] == "fail"


@pytest.mark.parametrize("name", ["Prüfung", "Cylinder's part", "Part\\revision"])
def test_actual_product_name_encoding(external_case, name):
    runner, path, expected, old_name, storage = external_case
    encoded = name.replace("\\", "\\\\").replace("'", "''")
    if not name.isascii():
        encoded = "\\X2\\" + name.encode("utf-16-be").hex().upper() + "\\X0\\"
    # The part schema deliberately restricts product names. These diagnostic
    # copies test the independent reader's encoding, not a broader build scope.
    changed = path.read_text().replace("'" + old_name + "'", "'" + encoded + "'")
    assert changed != path.read_text()
    candidate = storage / ("encoded-" + sha256(name.encode()).hexdigest()[:8] + ".step")
    candidate.write_text(changed)
    report = runner.run("analyze_ap242", input_step=candidate)
    assert report["status"] == "pass", report
    checked = verify_nominal_pmi(report, expected, name)
    assert checked["status"] == "pass", checked
