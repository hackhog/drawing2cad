"""The run timeline condenses the agent trace into steps (ADR 0038). No model is called."""

import json

import pytest
from fastapi.testclient import TestClient

from drawing_demo import api
from drawing_demo.agent import timeline

from test_agent_runs import environment, upload  # noqa: F401  (fixture)


def write(trace, sequence, kind, **data):
    (trace / f"{sequence:03d}-{kind}.json").write_text(json.dumps({**data, "sequence": sequence, "at": "t", "kind": kind}))


def response(data, error=True, images=0):
    content = [{"type": "text", "text": json.dumps(data)}] + [{"type": "image", "data": "QUJD", "mimeType": "image/png"}] * images
    return {"content": content, "structuredContent": data, "isError": error}


@pytest.fixture
def trace(tmp_path):
    t = tmp_path / "trace"
    t.mkdir()
    write(t, 1, "skill-references", turn=0, reason="the first step", paths=["references/a.md"])
    # Model requests repeat the whole conversation with images; the timeline must never read them.
    (t / "002-model-request.json").write_text("not JSON")
    write(t, 3, "model-response", turn=1, duration_seconds=2.5, response={
        "message": {"role": "assistant", "content": "Render the page first.", "tool_calls": [
            {"function": {"name": "pdf_render_page", "arguments": {"page": 1}}},
            {"function": {"name": "build_from_description", "arguments": {}}}]},
        "prompt_eval_count": 1000, "eval_count": 20})
    write(t, 4, "tool-request", turn=1, request_number=1, name="pdf_render_page", arguments={"page": 1})
    write(t, 5, "tool-response", turn=1, name="pdf_render_page", duration_seconds=0.4, response=response({"ok": 1}, False, images=1))
    write(t, 6, "tool-request", turn=1, request_number=2, name="build_from_description", arguments={})
    write(t, 7, "tool-response", turn=1, name="build_from_description", duration_seconds=1.0, response=response({
        "status": "fail", "feature_id": "fillet",
        "build": {"status": "fail", "error": {"code": "EDGE_SELECTION", "message": "Expected 4 edges."}}}))
    write(t, 8, "corrective-instruction", turn=1, name="build_from_description",
          failure={"code": "EDGE_SELECTION", "target": None, "message": "Expected 4 edges."}, message="Correct the arguments.")
    write(t, 9, "tool-request", turn=2, request_number=3, name="part_validate", arguments={"description": {}})
    write(t, 10, "tool-response", turn=2, name="part_validate", duration_seconds=0.1, response=response({
        "status": "fail", "defects": [{"code": "schema", "pointer": "/parameters/7/note", "message": "Extra inputs are not permitted"}]}))
    write(t, 11, "tool-request", turn=2, request_number=4, name="part_update", arguments={})
    return t


def test_a_continuation_message_is_a_step_of_its_own(tmp_path):
    t = tmp_path / "trace"
    t.mkdir()
    write(t, 1, "model-response", turn=4, duration_seconds=1.0, response={
        "message": {"role": "assistant", "content": "Now I will build the part description."}})
    write(t, 2, "continuation", turn=4, count=1, limit=3, message="No release exists. Continue with the next tool call.")
    write(t, 3, "summary", status="stopped_without_tool_call", released=False, continuations=3)
    steps = timeline.steps(t)
    assert [(s["sequence"], s["kind"]) for s in steps] == [(1, "model"), (2, "continuation")]
    assert {key: steps[1][key] for key in ("turn", "count", "limit", "text")} == {
        "turn": 4, "count": 1, "limit": 3, "text": "No release exists. Continue with the next tool call."}
    detail = timeline.step_detail(t, 2)
    assert detail["kind"] == "continuation" and detail["text"].startswith("No release exists.") and detail["problem"] is None
    assert timeline.summary(t)["status"] == "stopped_without_tool_call" and timeline.summary(t)["continuations"] == 3


def test_a_decoded_argument_is_a_step_of_its_own_before_its_tool_request(tmp_path):
    t = tmp_path / "trace"
    t.mkdir()
    write(t, 1, "argument-decoded", turn=2, request_number=5, name="drawing_validate", path="/drawing_spec",
          original_type="string", decoded_type="object")
    write(t, 2, "tool-request", turn=2, request_number=5, name="drawing_validate", arguments={"drawing_spec": {}})
    write(t, 3, "tool-response", turn=2, name="drawing_validate", duration_seconds=0.1, response=response({"status": "pass"}, False))
    steps = timeline.steps(t)
    # The decoding does not separate the tool request from its response.
    assert [(s["sequence"], s["kind"]) for s in steps] == [(1, "decoding"), (2, "tool")]
    assert steps[1]["status"] == "ok"
    decoding = steps[0]
    assert {key: decoding[key] for key in ("turn", "tool", "path", "original_type", "decoded_type")} == {
        "turn": 2, "tool": "drawing_validate", "path": "/drawing_spec", "original_type": "string", "decoded_type": "object"}
    assert decoding["text"] == ("The model sent the value at /drawing_spec as a JSON text, a string. "
                                "The tool schema expects an object. The loop decoded the text and sent the object.")
    detail = timeline.step_detail(t, 1)
    assert detail["kind"] == "decoding" and detail["tool"] == "drawing_validate" and detail["text"] == decoding["text"]
    assert detail["arguments"] is None and detail["problem"] is None


def test_steps_join_requests_with_responses_and_name_the_specific_problem(trace):
    steps = timeline.steps(trace)
    assert [(s["sequence"], s["kind"]) for s in steps] == [
        (1, "skill"), (3, "model"), (4, "tool"), (6, "tool"), (8, "correction"), (9, "tool"), (11, "tool")]
    model = steps[1]
    assert model["tool_calls"] == ["pdf_render_page", "build_from_description"] and model["prompt_tokens"] == 1000
    render, build, _, validate, open_request = steps[2], steps[3], steps[4], steps[5], steps[6]
    assert render["status"] == "ok" and render["phase"] == "analyzing" and render["images"] == 1 and render["seconds"] == 0.4
    assert build["status"] == "failed" and build["phase"] == "modeling"
    assert build["problem"] == {"code": "EDGE_SELECTION", "target": "fillet", "message": "Expected 4 edges."}
    assert validate["problem"]["code"] == "schema" and validate["problem"]["target"] == "/parameters/7/note"
    # A request without a response: the run is active or was interrupted.
    assert open_request["status"] == "no_response" and open_request["problem"] is None
    assert timeline.summary(trace) is None


def test_problem_prefers_service_errors_and_marks_client_rejections():
    assert timeline.problem({"isError": False}) is None
    service = response({"error": {"code": "INVALID_ARGUMENTS", "target": "/description", "message": "Schema rule."}})
    assert timeline.problem(service) == {"code": "INVALID_ARGUMENTS", "target": "/description", "message": "Schema rule."}
    rejected = {"isError": True, "client_rejected": True, "content": [{"type": "text", "text": "Run ID outside the prefix."}]}
    assert timeline.problem(rejected)["code"] == "CLIENT_REJECTED"
    plain = {"isError": True, "content": [{"type": "text", "text": "Worker crashed."}]}
    assert timeline.problem(plain) == {"code": "TOOL_ERROR", "target": None, "message": "Worker crashed."}


def test_step_details_hold_arguments_result_and_images(trace):
    render = timeline.step_detail(trace, 4)
    assert render["tool"] == "pdf_render_page" and json.loads(render["arguments"]) == {"page": 1}
    assert render["images"] == ["data:image/png;base64,QUJD"] and json.loads(render["result"]) == {"ok": 1}
    assert timeline.step_detail(trace, 3)["text"] == "Render the page first."
    assert timeline.step_detail(trace, 8)["problem"]["code"] == "EDGE_SELECTION"
    assert timeline.step_detail(trace, 11)["result"] is None
    # A response and a model request are not steps.
    assert timeline.step_detail(trace, 5) is None and timeline.step_detail(trace, 2) is None


def test_long_texts_are_bounded(trace):
    write(trace, 12, "model-response", turn=3, response={"message": {"content": "x" * 5000}})
    step = timeline.steps(trace)[-1]
    assert len(step["text"]) < 400 and "more characters" in step["text"]
    write(trace, 13, "summary", status="tool_budget_reached", released=False, model_turns=3, conversation=["long"])
    assert timeline.summary(trace) == {"status": "tool_budget_reached", "released": False, "model_turns": 3,
                                       "tool_requests": None, "mcp_calls": None, "blocked_requests": None,
                                       "continuations": None, "model_seconds": None, "mcp_seconds": None, "duration_seconds": None}


def test_the_api_serves_steps_and_step_details(environment):  # noqa: F811
    with TestClient(api.create_app()) as client:
        source = upload(client)
        jobs = client.app.state.services.jobs
        run_id = jobs.add(source["source_id"])["run_id"]
        trace = jobs.directory(run_id) / "trace"
        write(trace, 1, "tool-request", turn=1, request_number=1, name="pdf_info", arguments={})
        write(trace, 2, "tool-response", turn=1, name="pdf_info", duration_seconds=0.1, response=response({}, False))
        body = client.get(f"/api/runs/{run_id}/steps").json()
        assert [s["tool"] for s in body["steps"]] == ["pdf_info"] and body["summary"] is None
        assert client.get(f"/api/runs/{run_id}/steps/1").json()["tool"] == "pdf_info"
        assert client.get(f"/api/runs/{run_id}/steps/2").status_code == 404
        assert client.get("/api/runs/run_" + "0" * 32 + "/steps").status_code == 404
