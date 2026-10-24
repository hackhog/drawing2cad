"""The evaluation client records real HTTP MCP exchanges and rejects invalid plans."""

from contextlib import asynccontextmanager
import json

import pytest

from drawing2cad_mcp import evaluation_client
from drawing2cad_mcp.evaluation_client import _resolve, replay
from protocol_fixtures import TOKEN, TOKEN_ENV, protocol_server


SERVER = {"url": "http://127.0.0.1:8000/mcp", "token_env": TOKEN_ENV}


def write_plan(tmp_path, server=SERVER, **fields):
    plan = {"server": server, "calls": [{"name": "echo", "arguments": {"value": "trace test"}}], **fields}
    path = tmp_path / "plan.json"
    path.write_text(json.dumps(plan), encoding="utf-8")
    return path


async def test_trace_contains_exact_request_and_response(tmp_path, monkeypatch):
    monkeypatch.setenv(TOKEN_ENV, TOKEN)
    async with protocol_server() as fixture:
        path = write_plan(tmp_path, fixture.server, metadata={"model": "synthetic-protocol-fixture"})
        output = tmp_path / "run"
        summary = await replay(path, output)
    assert summary["status"] == "pass", summary
    assert fixture.calls == [{"name": "echo", "arguments": {"value": "trace test"}}]
    event = json.loads((output / "trace.jsonl").read_text())
    assert event["arguments"] == {"value": "trace test"}
    assert event["response"]["structuredContent"] == {"value": "trace test"}
    assert event["response"]["_meta"] == {"marker": 42}
    assert [item["type"] for item in event["response"]["content"]] == ["text", "image", "resource"]
    assert json.loads((output / "catalog.json").read_text())["tools"][0]["_meta"] == {"custom": {"preserve": 7}}
    assert summary["calls"][0]["response_sha256"]
    assert (output / "plan.json").read_bytes() == path.read_bytes()
    assert not (output / "server-stderr.log").exists()
    assert all(TOKEN not in file.read_text() for file in output.iterdir())


async def test_budget_is_rejected_before_connection(tmp_path):
    path = write_plan(tmp_path, step_budget=1, calls=[{"name": "a"}, {"name": "b"}])
    with pytest.raises(ValueError, match="budget"):
        await replay(path, tmp_path / "run")
    assert not (tmp_path / "run").exists()


@pytest.mark.parametrize("server", [
    {"command": "must-not-run"},
    {**SERVER, "token": TOKEN},
    {**SERVER, "headers": {"Authorization": f"Bearer {TOKEN}"}},
    {**SERVER, "env": {TOKEN_ENV: TOKEN}},
    {**SERVER, "url": f"http://user:{TOKEN}@127.0.0.1/mcp"},
    {**SERVER, "url": f"http://127.0.0.1/mcp?token={TOKEN}"},
    {**SERVER, "url": f"http://127.0.0.1/mcp#{TOKEN}"},
    {**SERVER, "url": "http://127.0.0.1:invalid/mcp"},
    {**SERVER, "url": "file:///mcp"},
    {**SERVER, "url": "http:///mcp"},
    {**SERVER, "url": "http://127.0.0.1/mcp\n"},
    {**SERVER, "token_env": "BAD NAME"},
])
async def test_invalid_server_is_rejected_without_secret_output(tmp_path, server):
    path = write_plan(tmp_path, server)
    with pytest.raises(ValueError) as error:
        await replay(path, tmp_path / "run")
    assert TOKEN not in str(error.value)
    assert not (tmp_path / "run").exists()


@pytest.mark.parametrize("value", [None, "", "private token\n"])
async def test_missing_or_invalid_token_is_rejected_before_output(tmp_path, monkeypatch, value):
    monkeypatch.delenv(TOKEN_ENV, raising=False)
    if value is not None:
        monkeypatch.setenv(TOKEN_ENV, value)
    with pytest.raises(ValueError, match="token environment variable") as error:
        await replay(write_plan(tmp_path), tmp_path / "run")
    assert value is None or not value or value not in str(error.value)
    assert not (tmp_path / "run").exists()


@pytest.mark.parametrize("fields", [
    {"metadata": {"notes": TOKEN}},
    {"server": {**SERVER, "url": f"http://127.0.0.1/{TOKEN}/mcp"}},
    {"metadata": {"api_key": "another-private-value"}},
])
async def test_plan_secrets_are_rejected_before_output(tmp_path, monkeypatch, fields):
    monkeypatch.setenv(TOKEN_ENV, TOKEN)
    with pytest.raises(ValueError) as error:
        await replay(write_plan(tmp_path, **fields), tmp_path / "run")
    assert TOKEN not in str(error.value)
    assert "another-private-value" not in str(error.value)
    assert not (tmp_path / "run").exists()


async def test_wrong_token_fails_without_recording_credentials(tmp_path, monkeypatch, caplog):
    wrong = "incorrect-client-bearer-token"
    monkeypatch.setenv(TOKEN_ENV, wrong)
    async with protocol_server() as fixture:
        summary = await replay(write_plan(tmp_path, fixture.server), tmp_path / "run")
    assert summary["status"] == "fail"
    assert fixture.calls == []
    assert wrong not in json.dumps(summary) + caplog.text
    assert all(wrong not in file.read_text() for file in (tmp_path / "run").iterdir())


async def test_response_secrets_are_redacted(tmp_path, monkeypatch):
    monkeypatch.setenv(TOKEN_ENV, TOKEN)
    async with protocol_server(response_value=TOKEN) as fixture:
        summary = await replay(write_plan(tmp_path, fixture.server), tmp_path / "run")
    assert summary["status"] == "pass"
    assert all(TOKEN not in file.read_text() for file in (tmp_path / "run").iterdir())
    assert "[REDACTED]" in (tmp_path / "run" / "trace.jsonl").read_text()


async def test_nested_connection_errors_are_redacted(tmp_path, monkeypatch):
    monkeypatch.setenv(TOKEN_ENV, TOKEN)

    @asynccontextmanager
    async def failing_connection(*args):
        raise ExceptionGroup("connection failure", [ValueError(TOKEN), ExceptionGroup(TOKEN, [RuntimeError(TOKEN)])])
        yield

    monkeypatch.setattr(evaluation_client, "connect", failing_connection)
    summary = await replay(write_plan(tmp_path), tmp_path / "run")
    assert summary["status"] == "fail"
    assert TOKEN not in json.dumps(summary)
    assert all(TOKEN not in file.read_text() for file in (tmp_path / "run").iterdir())
    assert "[REDACTED]" in (tmp_path / "run" / "client-error.log").read_text()


def test_json_references_are_data_only(tmp_path):
    (tmp_path / "part.json").write_text('{"value": 42}', encoding="utf-8")
    assert _resolve({"description": {"$json_file": "part.json"}}, tmp_path) == {"description": {"value": 42}}
