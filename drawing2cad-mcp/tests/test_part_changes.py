"""Change reports distinguish references from validated geometric effects."""

from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import sys

import pytest
from pypdf import PdfWriter

from drawing2cad_mcp.cad_service import CadError, CadService
from drawing2cad_mcp.config import CadSettings
from drawing2cad_mcp.worker_runner import WorkerLimits, WorkerRunner
from test_cad_service import setup_service, create, coverage


def test_update_preserves_validated_baseline_and_invalidates_release(setup_service):
    service, runner, description, source = setup_service
    create(setup_service)
    service.build_from_description(run_id="example", expected_revision=1)
    updated = deepcopy(description)
    updated["parameters"][0]["value"] = 21
    updated["features"].append({"id": "bore", "type": "hole", "position": [5, 5, 5],
                                "diameter": 2, "evidence_ids": ["drawing"]})
    assert service.part_validate(updated)["status"] == "pass"
    result = service.part_update(run_id="example", expected_revision=1, description=updated)
    report = result["change_report"]
    assert result["build_invalidated"] and result["release_invalidated"]
    assert report["baseline"]["revision"] == 1
    assert report["baseline"]["build"]["candidate_sha256"]
    assert report["parameter_changes"][0]["before"] == {"value": 20, "unit": "mm"}
    assert report["parameter_changes"][0]["after"] == {"value": 21, "unit": "mm"}
    assert report["parameter_changes"][0]["direct_references"] == [{"feature_id": "base", "path": "/features/0/length"}]
    assert report["potentially_affected_downstream_features"] == ["bore"]
    assert service.part_read(run_id="example")["part"]["build"] is None
    with pytest.raises(CadError) as error:
        service.export_step(run_id="example", expected_revision=2, coverage=coverage(source))
    assert error.value.code == "VALIDATED_BUILD_REQUIRED"
    with pytest.raises(CadError) as error:
        service.part_update(run_id="example", expected_revision=1, description=updated)
    assert error.value.code == "REVISION_CONFLICT"
    built = service.build_from_description(run_id="example", expected_revision=2)
    assert built["change_report"]["status"] == "validated_rebuild"
    effect = built["change_report"]["actual_effect"]
    assert effect["fresh_worker_reimport"] == "pass"
    assert effect["build_import_agreement"]["status"] == "pass"
    assert effect["aggregate_geometry"]["volume_mm3"]["delta"] == 0
    assert "unchanged" not in json.dumps(effect)
    exported = service.part_export_review(run_id="example", expected_revision=2)
    report_path = next(Path(item["path"]) for item in exported["artifacts"] if item["path"].endswith("change-report.json"))
    assert json.loads(report_path.read_text(encoding="utf-8"))["baseline"]["revision"] == 1


def test_failed_rebuild_and_followup_edit_keep_last_validated_revision(setup_service):
    service, runner, description, source = setup_service
    create(setup_service)
    service.build_from_description(run_id="example", expected_revision=1)
    first = deepcopy(description)
    first["parameters"][0]["value"] = 21
    service.part_update(run_id="example", expected_revision=1, description=first)
    runner.fail_operation = "build"
    failed = service.build_from_description(run_id="example", expected_revision=2)
    assert failed["change_report"]["status"] == "rebuild_failed"
    second = deepcopy(first)
    second["parameters"][0]["value"] = 22
    updated = service.part_update(run_id="example", expected_revision=2, description=second)
    assert updated["change_report"]["baseline"]["revision"] == 1
    assert updated["change_report"]["parameter_changes"][0]["before"]["value"] == 20
    assert updated["change_report"]["parameter_changes"][0]["after"]["value"] == 22
    runner.fail_operation = None
    assert service.build_from_description(run_id="example", expected_revision=3)["change_report"]["status"] == "validated_rebuild"


def test_failed_fresh_validation_reports_executed_check(setup_service):
    service, runner, description, source = setup_service
    create(setup_service)
    service.build_from_description(run_id="example", expected_revision=1)
    changed = deepcopy(description)
    changed["parameters"][0]["value"] = 21
    service.part_update(run_id="example", expected_revision=1, description=changed)
    runner.fail_operation = "validate"
    failed = service.build_from_description(run_id="example", expected_revision=2)
    effect = failed["change_report"]["actual_effect"]
    assert effect["fresh_worker_reimport"] == "fail"
    assert effect["build_import_agreement"]["status"] == "not_tested"


def _sandbox_service(tmp_path):
    capability = WorkerRunner.capabilities()
    if os.environ.get("DRAWING2CAD_REQUIRE_SANDBOX") == "1":
        assert capability["available"], capability
    if not capability["available"]:
        pytest.skip(capability["reason"])
    from test_part_schema import sample_description
    description = sample_description()
    source_dir = tmp_path / "sources"
    source_dir.mkdir()
    pdf = source_dir / "sample.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    with pdf.open("wb") as stream:
        writer.write(stream)
    digest = hashlib.sha256(pdf.read_bytes()).hexdigest()
    description["evidence"][0]["source"].update(source_id="drawing", source_sha256=digest)
    source = {"path": str(pdf), "sha256": digest, "source_id": "drawing", "role": "construction"}
    runner = WorkerRunner(tmp_path / "output" / "cad" / "workers", WorkerLimits(timeout_seconds=60))
    service = CadService([source_dir], tmp_path / "output", CadSettings(enabled=True), runner=runner)
    return service, description, source


@pytest.mark.skipif(sys.platform != "linux", reason="Restricted CAD workers require Linux.")
def test_sandbox_assumed_parameter_change_rebuilds_and_reimports(tmp_path):
    service, description, source = _sandbox_service(tmp_path)
    service.part_create(run_id="assumedchange", description=description, sources=[source])
    assert service.build_from_description(run_id="assumedchange", expected_revision=1)["status"] == "pass"
    revised = deepcopy(description)
    revised["evidence"].append({"id": "assumed_length", "status": "assumed", "reason": "New geometric estimate.",
                                "source": deepcopy(description["evidence"][0]["source"])})
    revised["parameters"][0].update(value=21, evidence_ids=["assumed_length"])
    revised["measurements"][0].update(expected=[21, 10, 5], basis="independent_measurement",
                                       evidence_ids=["assumed_length"])
    service.part_update(run_id="assumedchange", expected_revision=1, description=revised)
    result = service.build_from_description(run_id="assumedchange", expected_revision=2)
    assert result["status"] == "pass", result
    effect = result["change_report"]["actual_effect"]
    assert effect["fresh_worker_reimport"] == "pass"
    assert effect["build_import_agreement"]["status"] == "pass"
    assert effect["aggregate_geometry"]["bbox_max"]["delta"][0] == pytest.approx(1)
    assert effect["aggregate_geometry"]["volume_mm3"]["delta"] == pytest.approx(50)


@pytest.mark.skipif(sys.platform != "linux", reason="Restricted CAD workers require Linux.")
def test_sandbox_changed_parameter_with_unchanged_printed_dimension_fails(tmp_path):
    service, description, source = _sandbox_service(tmp_path)
    service.part_create(run_id="printedconflict", description=description, sources=[source])
    assert service.build_from_description(run_id="printedconflict", expected_revision=1)["status"] == "pass"
    revised = deepcopy(description)
    revised["parameters"][0]["value"] = 21
    service.part_update(run_id="printedconflict", expected_revision=1, description=revised)
    result = service.build_from_description(run_id="printedconflict", expected_revision=2)
    assert result["status"] == "fail", result
    assert result["change_report"]["status"] == "rebuild_failed"
    assert result["change_report"]["baseline"]["revision"] == 1



def test_removed_feature_does_not_relabel_unchanged_definitions():
    from drawing2cad_mcp.part_changes import proposed_change
    original = {"parameters": [], "features": [{"id": name} for name in "ABCD"]}
    changed = {"parameters": [], "features": [{"id": name} for name in "ACD"]}
    report = proposed_change(original, changed, 2)
    assert report["changed_feature_definitions"] == ["B"]
    assert report["potentially_affected_downstream_features"] == ["C", "D"]
    assert report["feature_order_changes"] == [
        {"feature_id": "B", "before_index": 1, "after_index": None},
        {"feature_id": "C", "before_index": 2, "after_index": 1},
        {"feature_id": "D", "before_index": 3, "after_index": 2},
    ]
