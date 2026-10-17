"""Exercise drawing output through the production sandbox process boundary."""

from pathlib import Path
import os

import pytest

from drawing2cad_mcp.worker_runner import WorkerRunner
from test_drafting import drawing_fixture


@pytest.fixture
def runner(tmp_path):
    runner = WorkerRunner(tmp_path / "workers")
    capability = runner.capabilities()
    if os.environ.get("DRAWING2CAD_REQUIRE_SANDBOX") == "1":
        assert capability["available"], capability
    if not capability["available"]:
        pytest.skip("The verified Linux sandbox is unavailable.")
    return runner


def test_drawing_worker_uses_verified_sandbox(runner):
    description, spec = drawing_fixture()
    result = runner.run("drawing", description=description, drawing_spec=spec, revision=1)
    assert result["status"] == "pass", result
    assert result["native_dimension_count"] == 3
    assert result["checks"]["rendered_layout"] == "pass"
    assert result["sandbox"]
    directory = Path(result["worker"]["work_dir"])
    assert {artifact["name"] for artifact in result["artifacts"]} == {
        "drawing.dxf", "drawing.pdf", "drawing-report.json"}
    assert all(Path(artifact["path"]).parent == directory for artifact in result["artifacts"])


def test_drawing_worker_rejects_stale_binding(runner):
    description, spec = drawing_fixture()
    result = runner.run("drawing", description=description, drawing_spec=spec, revision=2)
    assert result["status"] == "fail", result
    assert "stale_binding" in {d["code"] for d in result["defects"]}
    assert not list(Path(result["worker"]["work_dir"]).glob("drawing.*"))
