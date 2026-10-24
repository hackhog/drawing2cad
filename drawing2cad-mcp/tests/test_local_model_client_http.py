"""The local model CLI uses authenticated HTTP and keeps credentials out of evidence."""

from contextlib import asynccontextmanager
import json

import pytest

from drawing2cad_mcp import local_model_client
from protocol_fixtures import TOKEN, TOKEN_ENV, protocol_server
from test_local_model_client import call, inference, model_response, plan, report


def write_plan(tmp_path, server, **changes):
    (tmp_path / "SKILL.md").write_text("Use only the published MCP tools.", encoding="utf-8")
    path = tmp_path / "plan.json"
    path.write_text(json.dumps(plan(server=server, skill_path="SKILL.md", **changes)), encoding="utf-8")
    return path


async def test_run_records_authenticated_http_tool_call(tmp_path, monkeypatch):
    monkeypatch.setenv(TOKEN_ENV, TOKEN)
    monkeypatch.setattr(local_model_client, "call_model", inference(
        model_response([call("drawing2cad_status")]), model_response(text=report("Fixture completed."))))
    async with protocol_server(tool_name="drawing2cad_status") as fixture:
        path = write_plan(tmp_path, fixture.server)
        summary = await local_model_client.run(path, tmp_path / "run")
    assert summary["mcp_calls"] == 1
    assert summary["final_text"] == report("Fixture completed.")
    assert fixture.calls == [{"name": "drawing2cad_status", "arguments": {}}]
    events = [json.loads(line) for line in (tmp_path / "run" / "trace.jsonl").read_text().splitlines()]
    assert any(event["kind"] == "initialize" for event in events)
    assert any(event["kind"] == "tool-response" and event["response"]["_meta"] == {"marker": 42} for event in events)
    assert all(TOKEN not in file.read_text() for file in (tmp_path / "run").iterdir())
    assert (tmp_path / "run" / "plan.json").read_bytes() == path.read_bytes()
    assert not (tmp_path / "run" / "server-stderr.log").exists()


async def test_wrong_token_records_failure_without_credentials(tmp_path, monkeypatch, caplog):
    wrong = "incorrect-local-model-bearer-token"
    monkeypatch.setenv(TOKEN_ENV, wrong)
    async with protocol_server(tool_name="drawing2cad_status") as fixture:
        summary = await local_model_client.run(write_plan(tmp_path, fixture.server), tmp_path / "run")
    assert summary["status"] == "failed"
    assert fixture.calls == []
    assert wrong not in json.dumps(summary) + caplog.text
    assert all(wrong not in file.read_text() for file in (tmp_path / "run").iterdir())


@pytest.mark.parametrize("fields", [{}, {"metadata": {"notes": TOKEN}}])
async def test_missing_token_or_plan_secret_creates_no_output(tmp_path, monkeypatch, fields):
    monkeypatch.delenv(TOKEN_ENV, raising=False)
    if fields:
        monkeypatch.setenv(TOKEN_ENV, TOKEN)
    server = {"url": "http://127.0.0.1:8000/mcp", "token_env": TOKEN_ENV}
    with pytest.raises(ValueError) as error:
        await local_model_client.run(write_plan(tmp_path, server, **fields), tmp_path / "run")
    assert TOKEN not in str(error.value)
    assert not (tmp_path / "run").exists()


async def test_response_and_model_errors_do_not_enter_trace_with_credentials(tmp_path, monkeypatch):
    monkeypatch.setenv(TOKEN_ENV, TOKEN)
    responses = iter([model_response([call("drawing2cad_status")]), RuntimeError(f"model error: {TOKEN}")])

    def model(*args):
        result = next(responses)
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(local_model_client, "call_model", model)
    async with protocol_server(tool_name="drawing2cad_status", response_value=TOKEN) as fixture:
        summary = await local_model_client.run(write_plan(tmp_path, fixture.server), tmp_path / "run")
    assert summary["status"] == "failed"
    assert TOKEN not in json.dumps(summary)
    assert all(TOKEN not in file.read_text() for file in (tmp_path / "run").iterdir())
    assert "[REDACTED]" in (tmp_path / "run" / "trace.jsonl").read_text()


async def test_nested_connection_errors_are_redacted(tmp_path, monkeypatch):
    monkeypatch.setenv(TOKEN_ENV, TOKEN)

    @asynccontextmanager
    async def failing_connection(*args):
        raise ExceptionGroup(TOKEN, [ValueError(TOKEN), ExceptionGroup("nested", [RuntimeError(TOKEN)])])
        yield

    monkeypatch.setattr(local_model_client, "connect", failing_connection)
    server = {"url": "http://127.0.0.1:8000/mcp", "token_env": TOKEN_ENV}
    summary = await local_model_client.run(write_plan(tmp_path, server), tmp_path / "run")
    assert summary["status"] == "failed"
    assert TOKEN not in json.dumps(summary)
    assert summary["error"]["exceptions"][0]["message"] == "[REDACTED]"
    assert all(TOKEN not in file.read_text() for file in (tmp_path / "run").iterdir())


async def test_loaded_skill_secret_creates_no_output_after_source_changes(tmp_path, monkeypatch, caplog):
    monkeypatch.setenv(TOKEN_ENV, TOKEN)
    server = {"url": "http://127.0.0.1:8000/mcp", "token_env": TOKEN_ENV}
    path = write_plan(tmp_path, server)
    (tmp_path / "SKILL.md").write_text(f"Private skill data: {TOKEN}", encoding="utf-8")
    original_skill_text = local_model_client.skill_text

    def load_then_replace(skill_path, domain):
        text = original_skill_text(skill_path, domain)
        # The source can change between the skill and reference reads.
        skill_path.write_text("Use only the published MCP tools.", encoding="utf-8")
        return text

    monkeypatch.setattr(local_model_client, "skill_text", load_then_replace)
    with pytest.raises(ValueError, match="bearer token") as error:
        await local_model_client.run(path, tmp_path / "run")
    assert TOKEN not in str(error.value) + caplog.text
    assert not (tmp_path / "run").exists()
