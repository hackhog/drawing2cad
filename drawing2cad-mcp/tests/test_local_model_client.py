"""Tests for the bounded model client, without inference or CAD execution."""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from drawing2cad_mcp.local_model_client import (
    ALLOWED_TOOLS, DOMAIN_SKILL_REFERENCES, MUTATION_TOOLS, Trace, authorize_call, drive, response_messages, skill_references,
    skill_text, tool_catalog, validate_plan,
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


def test_projection_check_scope():
    source_id = "src_" + "a" * 32
    config = plan(source_id=source_id, source_sha256="b" * 64)
    available = {"model_projection_check"}
    assert "model_projection_check" not in MUTATION_TOOLS
    arguments = {"run_id": "localtest-a", "expected_revision": 1, "source_id": source_id, "page": 1, "views": []}
    assert [item["function"]["name"] for item in tool_catalog(catalog("model_projection_check"))] == [
        "model_projection_check", "request_user_input"]
    assert authorize_call("model_projection_check", arguments, config, available) == arguments
    with pytest.raises(ValueError, match="PDF source"):
        authorize_call("model_projection_check", {**arguments, "source_id": "src_" + "c" * 32}, config, available)
    with pytest.raises(ValueError, match="PDF source"):
        authorize_call("model_projection_check", {key: value for key, value in arguments.items() if key != "source_id"},
                       config, available)
    with pytest.raises(ValueError, match="prefix"):
        authorize_call("model_projection_check", {**arguments, "run_id": "another-run"}, config, available)
    # The local-path profile has no source ID, so a projection check cannot match its source.
    with pytest.raises(ValueError, match="PDF source"):
        authorize_call("model_projection_check", arguments, plan(), available)


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


STEP_TABLE = """# Skill

## References for each step

| Step | Tools | References |
|---|---|---|
| 1. Start | `drawing2cad_status` | [start.md](references/start.md) |
| 2. Inspect | `pdf_info`, `pdf_render_page` | [start.md](references/start.md), [inspect.md](references/inspect.md) |

## Other
"""


def write_skill(root, table=STEP_TABLE, names=("start.md", "inspect.md", "other.md")):
    (root / "references").mkdir()
    (root / "SKILL.md").write_text(table)
    for name in names:
        (root / "references" / name).write_text(f"Rules of {name}")
    return root / "SKILL.md"


def test_the_skill_text_is_skill_md_and_the_domain_profile_requires_the_drawing_references(tmp_path):
    skill = write_skill(tmp_path, "# Skill", (DOMAIN_SKILL_REFERENCES[0],))
    assert skill_text(skill, domain=False) == "# Skill"
    with pytest.raises(ValueError, match=DOMAIN_SKILL_REFERENCES[1]):
        skill_text(skill, domain=True)
    (tmp_path / "references" / DOMAIN_SKILL_REFERENCES[1]).write_text("Rules")
    assert skill_text(skill, domain=True) == "# Skill"


def test_skill_references_read_the_step_table(tmp_path):
    references = skill_references(write_skill(tmp_path))
    assert list(references.files) == ["SKILL.md", "references/inspect.md", "references/other.md", "references/start.md"]
    assert references.initial() == ["references/start.md"]
    assert references.for_tool("pdf_render_page") == ["references/start.md", "references/inspect.md"]
    assert references.for_tool("part_create") == []
    assert references.read({"path": "references/other.md"}) == "Rules of other.md"
    for arguments in ({"path": "../SKILL.md"}, {"path": "/etc/passwd"}, {"path": "references/missing.md"}, {}, {"path": 1}):
        with pytest.raises(ValueError):
            references.read(arguments)


def test_skill_references_reject_a_missing_file_in_the_table_and_large_skills(tmp_path):
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    with pytest.raises(ValueError, match="references/inspect.md"):
        skill_references(write_skill(tmp_path / "a", names=("start.md",)))
    skill = write_skill(tmp_path / "b")
    (tmp_path / "b" / "references" / "large.md").write_text("x" * (256 * 1024))
    with pytest.raises(ValueError, match="256 KiB"):
        skill_references(skill)


def test_the_maintained_skill_assigns_existing_references_to_its_steps():
    skill = Path(__file__).resolve().parents[2] / "skills" / "drawing2cad" / "SKILL.md"
    references = skill_references(skill)
    assigned = {path for _, paths in references.steps for path in paths}
    assert assigned and assigned <= set(references.files)
    assert "references/drawing-delivery.md" in references.for_tool("drawing_schema")
    assert "references/verification-loop.md" in references.for_tool("build_from_description")
    assert references.initial()
    # Each reference is assigned to a step or named in the text for a topic.
    text = references.files["SKILL.md"]
    for path in references.files:
        assert path == "SKILL.md" or path in assigned or f"]({path})" in text
    # The step table names only tools of the bounded client.
    named = {tool for tools, _ in references.steps for tool in tools}
    assert named <= ALLOWED_TOOLS


@pytest.mark.asyncio
async def test_drive_supplies_each_step_reference_once_and_skill_read_uses_no_budget(tmp_path):
    (tmp_path / "skill").mkdir()
    references = skill_references(write_skill(tmp_path / "skill"))
    session = Session()
    requests = []
    responses = iter([
        model_response([call("pdf_info", {"path": "/inputs/part.pdf"}), call("skill_read", {"path": "references/other.md"})]),
        model_response([call("pdf_render_page", {"path": "/inputs/part.pdf"}), call("skill_read", {"path": "../x"})]),
        model_response(text="Done."),
    ])

    def model(plan, payload, timeout):
        requests.append(json.loads(json.dumps(payload["messages"])))
        return next(responses)

    result = await drive(session, catalog("pdf_info", "pdf_render_page"), plan(step_budget=2), "Skill", Trace(tmp_path),
                         model_call=model, references=references)
    assert result["tool_requests"] == 2 and result["skill_reads"] == 2 and result["status"] == "stopped_without_release"
    assert [name for name, _ in session.calls] == ["pdf_info", "pdf_render_page"]
    assert result["supplied_references"] == ["references/start.md", "references/inspect.md"]
    first = requests[0]
    assert "skill_read" in first[0]["content"] and first[2]["content"].startswith("Skill references for the first step")
    assert "Rules of start.md" in first[2]["content"] and "Rules of inspect.md" not in first[2]["content"]
    second = requests[1]
    assert [m["content"] for m in second if m["role"] == "tool" and m.get("tool_name") == "skill_read"] == ["Rules of other.md"]
    assert "Rules of inspect.md" in second[-1]["content"] and "Rules of start.md" not in second[-1]["content"]
    third = requests[2]
    assert sum("Rules of inspect.md" in str(m.get("content")) for m in third) == 1
    assert any("Unknown skill file: ../x" in str(m.get("content")) for m in third if m["role"] == "tool")


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
