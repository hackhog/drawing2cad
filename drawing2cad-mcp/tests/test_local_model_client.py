"""Tests for the bounded model client, without inference or CAD execution."""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from drawing2cad_mcp.local_model_client import (
    DOMAIN_SKILL_REFERENCES, Trace, authorize_call, drive, response_messages, skill_text, tool_catalog, validate_plan,
)


def plan(**changes):
    value = {"server": {"command": "unused"}, "model": "local-test", "source_path": "/inputs/part.pdf",
             "run_prefix": "localtest", "ollama_url": "http://127.0.0.1:11434", "step_budget": 3}
    value.update(changes)
    return value


def call(name, arguments=None):
    return {"function": {"name": name, "arguments": arguments or {}}}


def model_response(calls=(), text=""):
    return {"message": {"role": "assistant", "content": text, "tool_calls": list(calls), "thinking": "Retained reasoning."},
            "eval_count": 12, "eval_duration": 1000000}


class Session:
    def __init__(self, response=None):
        self.calls = []
        self.response = response or {"isError": False, "structuredContent": {"status": "pass"}, "content": []}

    async def call_tool(self, name, arguments):
        self.calls.append((name, arguments))
        return SimpleNamespace(model_dump=lambda **kwargs: self.response)


def catalog(*names):
    return [{"name": name, "description": "Test", "inputSchema": {"type": "object"}} for name in names]


def inference(*responses):
    iterator = iter(responses)
    return lambda *args: next(iterator)


@pytest.mark.parametrize("changes", [
    {"step_budget": 0}, {"step_budget": True}, {"total_timeout_seconds": 1000000},
    {"ollama_url": "https://public.example"}, {"ollama_url": "http://127.0.0.1:11434/private"},
    {"run_prefix": "../other"}, {"source_path": "/inputs/file.step"},
    {"docker_bridge": {"container": "safe", "image": "safe"}},
])
def test_invalid_plan(changes):
    with pytest.raises(ValueError):
        validate_plan(plan(**changes))


def test_local_or_container_transport():
    validate_plan(plan())
    validate_plan(plan(ollama_url=None, docker_bridge={"container": "ollama-1", "image": "drawing2cad-mcp:m1"}))


def test_catalog_removes_unsafe_tools():
    result = tool_catalog(catalog("pdf_info", "freecad_execute_code", "build_code", "step_append_payload"))
    assert [item["function"]["name"] for item in result] == ["pdf_info", "request_user_input"]


def test_source_and_run_scope():
    config = plan()
    with pytest.raises(ValueError, match="PDF source"):
        authorize_call("pdf_info", {"path": "/inputs/verification.pdf"}, config, {"pdf_info"})
    with pytest.raises(ValueError, match="prefix"):
        authorize_call("part_read", {"run_id": "another-run"}, config, {"part_read"})
    with pytest.raises(ValueError, match="construction PDF"):
        authorize_call("part_create", {"run_id": "localtest-a", "sources": [{"path": "/inputs/part.pdf", "role": "verification"}]}, config, {"part_create"})
    assert authorize_call("pdf_info", {"path": config["source_path"]}, config, {"pdf_info"})


def test_uploaded_source_scope():
    source_id, digest = "src_" + "a" * 32, "b" * 64
    config = plan(source_id=source_id, source_sha256=digest)
    with pytest.raises(ValueError, match="PDF source"):
        authorize_call("drawing_extract", {"source_id": "src_" + "c" * 32}, config, {"drawing_extract"})
    with pytest.raises(ValueError, match="PDF source"):
        authorize_call("pdf_info", {"path": config["source_path"]}, config, {"pdf_info"})
    with pytest.raises(ValueError, match="construction PDF"):
        authorize_call("part_create", {"run_id": "localtest-a", "sources": [
            {"source_id": source_id, "sha256": "c" * 64, "role": "construction"}]}, config, {"part_create"})
    assert authorize_call("pdf_info", {"source_id": source_id}, config, {"pdf_info"})
    assert authorize_call("part_create", {"run_id": "localtest-a", "sources": [
        {"source_id": source_id, "sha256": digest, "role": "construction"}]}, config, {"part_create"})


async def test_uploaded_source_prompt_requires_a_complete_drawing_before_release(tmp_path):
    session = Session()
    config = plan(source_id="src_" + "a" * 32, source_sha256="b" * 64)
    requests = []

    def model(plan, payload, timeout):
        requests.append(payload)
        return model_response(text="Done.")

    await drive(session, catalog("drawing_review"), config, "Skill", Trace(tmp_path), model_call=model)
    system = requests[0]["messages"][0]["content"]
    assert "src_" + "a" * 32 in system and "/inputs/part.pdf" not in system
    assert "drawing is a required deliverable" in system and "drawings, semantic PMI" not in system
    assert "rejects the drawing, correct the drawing_spec" in system
    assert "Call export_step only after an accepted drawing review" in system
    assert "complete dimensioned drawing" in requests[0]["messages"][1]["content"]
    assert [tool["function"]["name"] for tool in requests[0]["tools"]] == ["drawing_review", "request_user_input"]


def test_the_skill_text_embeds_every_reference(tmp_path):
    (tmp_path / "references").mkdir()
    (tmp_path / "SKILL.md").write_text("# Skill")
    names = (*DOMAIN_SKILL_REFERENCES, "validation.md")
    for name in names:
        (tmp_path / "references" / name).write_text(f"Rules of {name}")
    (tmp_path / "references" / "notes.txt").write_text("Not a reference")
    for domain in (False, True):
        text = skill_text(tmp_path / "SKILL.md", domain=domain)
        assert text.startswith("# Skill")
        for name in names:
            assert f'<reference path="references/{name}">\nRules of {name}\n</reference>' in text
        assert "Not a reference" not in text


def test_the_domain_skill_requires_the_drawing_references(tmp_path):
    (tmp_path / "references").mkdir()
    (tmp_path / "SKILL.md").write_text("# Skill")
    (tmp_path / "references" / DOMAIN_SKILL_REFERENCES[0]).write_text("Rules")
    assert skill_text(tmp_path / "SKILL.md", domain=False).count("<reference path=") == 1
    with pytest.raises(ValueError, match=DOMAIN_SKILL_REFERENCES[1]):
        skill_text(tmp_path / "SKILL.md", domain=True)


def test_the_skill_text_has_a_size_limit(tmp_path):
    (tmp_path / "references").mkdir()
    (tmp_path / "SKILL.md").write_text("# Skill")
    (tmp_path / "references" / "large.md").write_text("x" * (256 * 1024))
    with pytest.raises(ValueError, match="256 KiB"):
        skill_text(tmp_path / "SKILL.md", domain=False)


def test_the_maintained_skill_is_embedded_completely():
    skill = Path(__file__).resolve().parents[2] / "skills" / "drawing2cad" / "SKILL.md"
    text = skill_text(skill, domain=True)
    assert "fully describe the required shape" in text and "Always use the complete skill" in text
    for reference in sorted((skill.parent / "references").glob("*.md")):
        assert f'<reference path="references/{reference.name}">' in text


def test_images_and_truncation_are_explicit():
    result = response_messages("pdf_render_page", {"content": [{"type": "text", "text": "x" * 4000},
                               {"type": "image", "data": "AAAA", "mimeType": "image/png"}]}, 1000)
    assert json.loads(result[0]["content"])["client_truncated"] is True
    assert result[1]["images"] == ["AAAA"]
    assert '"data"' not in result[0]["content"]


def test_exact_duplicate_text_is_omitted_only_from_model_context():
    raw = {"structuredContent": {"status": "pass", "values": [1, 2]}, "content": [
        {"type": "text", "text": '{"status":"pass","values":[1,2]}'},
        {"type": "text", "text": "Separate explanation."}]}
    forwarded = json.loads(response_messages("part_schema", raw, 1000)[0]["content"])
    assert forwarded["structuredContent"] == raw["structuredContent"]
    assert forwarded["content"] == [{"type": "text", "text": "Separate explanation."}]
    assert len(raw["content"]) == 2


def test_event_metadata_cannot_be_replaced_by_data(tmp_path):
    Trace(tmp_path).write("question", {"sequence": 999, "at": "false-time", "kind": "summary"})
    event = json.loads((tmp_path / "001-question.json").read_text())
    assert event["sequence"] == 1
    assert event["kind"] == "question"
    assert event["at"] != "false-time"


@pytest.mark.asyncio
async def test_budget_counts_rejected_calls_and_preserves_exact_trace(tmp_path):
    session = Session()
    result = await drive(session, catalog("pdf_info"), plan(step_budget=2), "Test skill", Trace(tmp_path),
        inference(model_response([call("unknown"), call("pdf_info", {"path": "/inputs/part.pdf"}), call("pdf_info")])))
    assert result["status"] == "tool_budget_reached"
    assert result["tool_requests"] == 2
    assert result["mcp_calls"] == 1
    events = [json.loads(line) for line in (tmp_path / "trace.jsonl").read_text().splitlines()]
    assert next(event for event in events if event["kind"] == "model-response")["response"]["message"]["thinking"] == "Retained reasoning."
    assert any(event["kind"] == "tool-response" and event["response"].get("client_rejected") for event in events)
    assert result["model_statistics"][0]["eval_count"] == 12
    assert result["model_seconds"] >= 0 and result["mcp_seconds"] >= 0


@pytest.mark.asyncio
async def test_required_question_stops_without_mcp_call(tmp_path):
    session = Session()
    result = await drive(session, catalog("pdf_info"), plan(), "Test skill", Trace(tmp_path),
        inference(model_response([call("request_user_input", {"question": "Which view controls?", "reason": "Conflicting source dimensions."})])))
    assert result["status"] == "user_input_required"
    assert result["questions"][0]["question"] == "Which view controls?"
    assert session.calls == []


@pytest.mark.asyncio
async def test_release_requires_actual_tool_response(tmp_path):
    session = Session({"isError": False, "structuredContent": {"status": "pass", "release": {"sha256": "a" * 64}}, "content": []})
    result = await drive(session, catalog("export_step"), plan(), "Test skill", Trace(tmp_path),
        inference(model_response([call("export_step", {"run_id": "localtest-a"})]), model_response(text="Finished.")))
    assert result["status"] == "released"
    assert result["final_text"] == "Finished."


@pytest.mark.asyncio
@pytest.mark.parametrize("mutation", ["part_update", "add_hole", "build_from_description", "part_create"])
async def test_later_mutation_invalidates_recorded_release(tmp_path, mutation):
    class ChangingSession(Session):
        async def call_tool(self, name, arguments):
            data = {"status": "pass", "release": {"sha256": "a" * 64}} if name == "export_step" else {"status": "pass", "revision": 2}
            return SimpleNamespace(model_dump=lambda **kwargs: {"isError": False, "structuredContent": data, "content": []})
    arguments = {"run_id": "localtest-a"}
    if mutation == "part_create":
        arguments["sources"] = [{"path": "/inputs/part.pdf", "role": "construction"}]
    result = await drive(ChangingSession(), catalog("export_step", mutation), plan(), "Test skill", Trace(tmp_path),
        inference(model_response([call("export_step", {"run_id": "localtest-a"})]),
                  model_response([call(mutation, arguments)]), model_response(text="Finished.")))
    assert result["released"] is False
    assert result["status"] == "stopped_without_release"


@pytest.mark.asyncio
@pytest.mark.parametrize("drawing_call", ["drawing_render", "drawing_review"])
async def test_drawing_call_after_release_keeps_the_release(tmp_path, drawing_call):
    """The drawing does not gate the STEP release, so a later drawing call keeps it."""
    class DrawingSession(Session):
        async def call_tool(self, name, arguments):
            data = {"status": "pass", "release": {"sha256": "a" * 64}} if name == "export_step" else {"status": "pass"}
            return SimpleNamespace(model_dump=lambda **kwargs: {"isError": False, "structuredContent": data, "content": []})
    result = await drive(DrawingSession(), catalog("export_step", drawing_call), plan(), "Test skill", Trace(tmp_path),
        inference(model_response([call("export_step", {"run_id": "localtest-a"})]),
                  model_response([call(drawing_call, {"run_id": "localtest-a"})]), model_response(text="Finished.")))
    assert result["released"] is True
    assert result["status"] == "released"


@pytest.mark.asyncio
async def test_uncertain_mutation_cannot_retain_release_claim(tmp_path):
    class UncertainSession(Session):
        async def call_tool(self, name, arguments):
            if name == "part_update":
                raise TimeoutError("Mutation completion is unknown.")
            return SimpleNamespace(model_dump=lambda **kwargs: {"isError": False, "structuredContent": {
                "status": "pass", "release": {"sha256": "a" * 64}}, "content": []})
    result = await drive(UncertainSession(), catalog("export_step", "part_update"), plan(), "Test skill", Trace(tmp_path),
        inference(model_response([call("export_step", {"run_id": "localtest-a"})]),
                  model_response([call("part_update", {"run_id": "localtest-a"})])))
    assert result["released"] is False
    assert result["status"] == "transport_failed"


@pytest.mark.asyncio
async def test_final_claim_without_release_is_not_pass(tmp_path):
    result = await drive(Session(), [], plan(), "Test skill", Trace(tmp_path), inference(model_response(text="Success.")))
    assert result["status"] == "stopped_without_release"
    assert result["released"] is False


@pytest.mark.asyncio
async def test_model_failure_has_timing_and_error_evidence(tmp_path):
    def failed(*args):
        raise TimeoutError("Inference timed out.")
    result = await drive(Session(), [], plan(), "Test skill", Trace(tmp_path), failed)
    assert result["status"] == "failed"
    assert result["error"]["type"] == "TimeoutError"
    assert list(tmp_path.glob("*-model-error.json"))
