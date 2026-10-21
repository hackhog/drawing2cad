"""System tools of the shared runtime: the report, the start check, and their presence in the image."""

import os

import pytest

from drawing2cad_mcp import runtime_tools


def fake_report(**absent):
    return {name: {"available": not absent.get(name, False)} for name in ("poppler", "tesseract", "stepcode")}


def test_missing_tools_are_named_with_their_purpose(monkeypatch):
    monkeypatch.setattr(runtime_tools, "report", lambda: fake_report(tesseract=True, stepcode=True))
    assert runtime_tools.missing() == ["stepcode", "tesseract"]
    with pytest.raises(RuntimeError) as error:
        runtime_tools.require()
    assert "tesseract (drawing_verify reads" in str(error.value) and "stepcode" in str(error.value)


def test_the_start_check_runs_only_in_an_image_that_requires_the_tools(monkeypatch):
    monkeypatch.setattr(runtime_tools, "report", lambda: fake_report(poppler=True))
    monkeypatch.delenv(runtime_tools.REQUIRE_ENV, raising=False)
    runtime_tools.require_if_configured()
    monkeypatch.setenv(runtime_tools.REQUIRE_ENV, "1")
    with pytest.raises(RuntimeError):
        runtime_tools.require_if_configured()


def test_the_mcp_server_refuses_to_start_without_its_tools(monkeypatch, tmp_path, capsys):
    from drawing2cad_mcp import server

    monkeypatch.setattr(runtime_tools, "report", lambda: fake_report(tesseract=True))
    monkeypatch.setenv(runtime_tools.REQUIRE_ENV, "1")
    monkeypatch.setattr("sys.argv", ["drawing2cad-mcp", "--config", str(tmp_path / "missing.toml")])
    with pytest.raises(SystemExit):
        server.main()
    assert "Missing system tools" in capsys.readouterr().err


@pytest.mark.skipif(os.environ.get(runtime_tools.REQUIRE_ENV) != "1", reason="This environment is not an image of the shared runtime.")
def test_each_tool_is_present_in_the_image():
    assert runtime_tools.missing() == []


def test_a_tool_that_cannot_load_does_not_pass(monkeypatch, tmp_path):
    broken = tmp_path / "reader"
    broken.write_text("#!/bin/sh\necho 'reader: error while loading shared libraries: libx.so' >&2\nexit 127\n")
    broken.chmod(0o755)
    ok, detail = runtime_tools._run([str(broken)])
    assert not ok and "shared libraries" in detail
    usage = tmp_path / "usage"
    usage.write_text("#!/bin/sh\necho 'usage: reader FILE' >&2\nexit 64\n")
    usage.chmod(0o755)
    assert runtime_tools._run([str(usage)])[0]
