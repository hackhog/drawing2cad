"""The evaluation client records real MCP exchanges and rejects invalid plans."""

import json
import sys

import pytest

from drawing2cad_mcp.evaluation_client import _resolve, replay
from protocol_fixtures import UPSTREAM


async def test_trace_contains_exact_request_and_response(tmp_path):
    plan = {"server": {"command": sys.executable, "args": ["-u", "-c", UPSTREAM]},
            "metadata": {"model": "synthetic-protocol-fixture"},
            "calls": [{"name": "echo", "arguments": {"value": "trace test"}}]}
    path = tmp_path / "plan.json"
    path.write_text(json.dumps(plan), encoding="utf-8")
    output = tmp_path / "run"
    summary = await replay(path, output)
    assert summary["status"] == "pass", summary
    event = json.loads((output / "trace.jsonl").read_text())
    assert event["arguments"] == {"value": "trace test"}
    assert event["response"]["structuredContent"] == {"value": "trace test"}
    assert summary["calls"][0]["response_sha256"]


async def test_budget_is_rejected_before_server_start(tmp_path):
    path = tmp_path / "plan.json"
    path.write_text(json.dumps({"server": {"command": "must-not-run"}, "step_budget": 1,
                                "calls": [{"name": "a"}, {"name": "b"}]}))
    with pytest.raises(ValueError, match="budget"):
        await replay(path, tmp_path / "run")
    assert not (tmp_path / "run").exists()


def test_json_references_are_data_only(tmp_path):
    (tmp_path / "part.json").write_text('{"value": 42}', encoding="utf-8")
    assert _resolve({"description": {"$json_file": "part.json"}}, tmp_path) == {"description": {"value": 42}}
