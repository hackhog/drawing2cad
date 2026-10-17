"""STEP-only reconstruction and edits in distinct restricted processes."""

from hashlib import sha256
import os
from pathlib import Path
import sys

import pytest

from drawing2cad_mcp.worker_runner import WorkerLimits, WorkerRunner
from test_part_schema import sample_description
from test_semantic_pmi import cylinder_case

pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="Restricted CAD workers require Linux.")


@pytest.fixture
def runner(tmp_path):
    capability = WorkerRunner.capabilities()
    if os.environ.get("DRAWING2CAD_REQUIRE_SANDBOX") == "1":
        assert capability["available"], capability
    if not capability["available"]:
        pytest.skip(capability["reason"])
    return WorkerRunner(tmp_path / "workers", WorkerLimits(timeout_seconds=60))


def test_fresh_worker_step_only_edit_reexport_and_repeat_with_pmi(runner):
    description, pmi = cylinder_case()
    description["features"][0]["height"] = {"parameter": "length"}
    pmi["dimensions"][1]["value"] = {"parameter": "length"}
    pmi["dimensions"][1]["targets"][1]["origin"][2] = {"parameter": "length"}
    first = runner.run("build", description=description, export_profile="ap242", pmi=pmi)
    assert first["status"] == "pass", first
    path = Path(first["candidate_step"])
    second = runner.run("reconstruct_step", input_step=path)
    assert second["status"] == "pass", second
    assert second["input_sha256"] == sha256(path.read_bytes()).hexdigest()
    assert second["construction"]["original_agreement"] == "pass"
    third = runner.run("reconstruct_step", input_step=Path(second["candidate_step"]), parameter_changes={"length": 40})
    assert third["status"] == "pass", third
    assert third["measured"]["bbox_size"] == pytest.approx([20, 20, 40])
    fourth = runner.run("reconstruct_step", input_step=Path(third["candidate_step"]))
    assert fourth["status"] == "pass", fourth
    assert fourth["description"]["parameters"][0]["value"] == 40
    validated = runner.run("validate", description=fourth["description"], input_step=Path(fourth["candidate_step"]))
    assert validated["status"] == "pass", validated
    assert len({result["worker"]["worker_id"] for result in (first, second, third, fourth, validated)}) == 5
    assert all(result["sandbox"]["profile"] == "linux-landlock-seccomp-v1" for result in (first, second, third, fourth, validated))
    # Independent read-back runs in the test parent after all isolated workers.
    from drawing2cad_mcp.adapters.semantic_pmi import read_ap242_pmi
    records = read_ap242_pmi(Path(fourth["candidate_step"]))
    assert sorted(item["value"] for item in records) == [20, 40]
    assert sorted(len(item["references"]) for item in records) == [1, 2]
    assert all(item["has_plane"] and item["presentation_edges"] > 5 for item in records)


def test_worker_rejects_missing_recipe_and_stale_measurement(runner):
    first = runner.run("build", description=sample_description())
    assert first["status"] == "pass", first
    unsupported = runner.run("reconstruct_step", input_step=Path(first["candidate_step"]))
    assert unsupported["status"] == "fail"
    assert "actual AP242" in unsupported["error"]["message"]
    second = runner.run("build", description=sample_description(), export_profile="ap242")
    assert second["status"] == "pass", second
    failed = runner.run("reconstruct_step", input_step=Path(second["candidate_step"]), parameter_changes={"length": 30})
    assert failed["status"] == "fail", failed
    assert failed["candidate_step"] is None
    assert any(row["check"] == "overall" and row["status"] == "fail" for row in failed["checks"])
