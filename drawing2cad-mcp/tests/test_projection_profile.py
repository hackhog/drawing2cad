"""Optional reproduction with authorized retained inputs. Do not store these inputs in the repository."""

import json
import os
from pathlib import Path
import sys

import pytest

from drawing2cad_mcp.worker_runner import WorkerRunner


@pytest.mark.skipif(sys.platform != "linux", reason="Restricted CAD workers require Linux.")
def test_retained_projection_inputs(tmp_path):
    inputs = os.environ.get("DRAWING2CAD_PROJECTION_INPUTS")
    request_path = os.environ.get("DRAWING2CAD_PROJECTION_REQUEST")
    if not inputs or not request_path:
        pytest.skip("Supply authorized source.pdf, candidate.step, and a projection request for this reproduction.")
    request = json.loads(Path(request_path).read_text(encoding="utf-8-sig"))
    args = request.get("arguments", request)
    runner = WorkerRunner(tmp_path / "workers")
    assert runner.capabilities()["available"], runner.capabilities()
    result = runner.run("projection_check", input_step=Path(inputs) / "candidate.step",
                        input_pdf=Path(inputs) / "source.pdf", page=args["page"], views=args["views"])
    (tmp_path / "projection-result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    expected = os.environ.get("DRAWING2CAD_PROJECTION_EXPECT_ERROR")
    if expected:
        assert result.get("error", {}).get("code") == expected, result
    else:
        assert "error" not in result, result
        assert len(result["views"]) == len(args["views"])
        assert result["status"] in {"pass", "fail"}
        assert result["artifacts"]
    assert result["worker"]["duration_seconds"] < 95
