"""Bounded recovery from failed tool requests in the agent loop, with scripted model responses and a stub MCP session."""

import json
import time
from types import SimpleNamespace

import pytest
from jsonschema import Draft202012Validator

from drawing2cad_mcp.local_model_client import (
    Trace, canonical_request, decode_json_text_arguments, deterministic_failure, drive,
)
from drawing2cad_mcp.server import invalid_arguments
from test_local_model_client import Session, call, catalog, model_response, plan, report

SOURCE_ID = "src_" + "a" * 32
SOURCE_SHA = "b" * 64
INVALID_REGION = {"code": "INVALID_ARGUMENTS", "target": "/references/0/source_region/2",
                  "message": "Arguments do not match the published tool schema. 10 is greater than the maximum of 1"}
UPDATE = {"run_id": "localtest-a", "expected_revision": 1, "operations": []}
BUILD = {"run_id": "localtest-a", "expected_revision": 2}
PAGE = {"path": "/inputs/part.pdf", "page": 1}


def domain_plan(**changes):
    return plan(source_id=SOURCE_ID, source_sha256=SOURCE_SHA, **changes)


def calibration(region, first=(10, 10), second=(10, 10), reverse=False):
    reference = {"source_region": region, "p0": list(first), "p1": list(second), "length_mm": 50}
    if reverse:
        return {"references": [dict(reversed(list(reference.items())))], "source_id": SOURCE_ID}
    return {"source_id": SOURCE_ID, "references": [reference]}


def error_response(error):
    return {"isError": True, "structuredContent": {"error": error}, "content": []}


def ok_response():
    return {"isError": False, "structuredContent": {"status": "pass"}, "content": []}


class ScriptedSession:
    """Answer each MCP call with the response that `respond` returns for its name, arguments, and call number."""

    def __init__(self, respond):
        self.respond = respond
        self.calls = []

    async def call_tool(self, name, arguments):
        self.calls.append(name)
        response = self.respond(name, arguments, len(self.calls))
        return SimpleNamespace(model_dump=lambda **kwargs: response)


def recorded(*responses):
    """A model call that records the messages of each request and returns the scripted responses in sequence."""
    requests = []
    iterator = iter(responses)

    def model(plan, payload, timeout):
        requests.append(json.loads(json.dumps(payload["messages"])))
        return next(iterator)

    return model, requests


def trace_kinds(path):
    return [json.loads(line)["kind"] for line in (path / "trace.jsonl").read_text().splitlines()]


def test_canonical_requests_ignore_object_key_order():
    assert canonical_request("pdf_calibrate", calibration([0, 0, 10, 10])) == \
        canonical_request("pdf_calibrate", calibration([0, 0, 10, 10], reverse=True))
    assert canonical_request("pdf_calibrate", calibration([0, 0, 1, 1])) != \
        canonical_request("pdf_calibrate", calibration([0, 0, 10, 10]))


@pytest.mark.parametrize(("response", "expected"), [
    (error_response(INVALID_REGION), {**INVALID_REGION}),
    (error_response({"code": "BUILD_FAILED", "message": "The fillet failed."}),
     {"code": "BUILD_FAILED", "target": None, "message": "The fillet failed."}),
    ({"isError": True, "structuredContent": {"status": "fail"}, "content": [{"type": "text", "text": "fail"}]},
     {"code": "STATUS_FAIL", "target": None, "message": "fail"}),
    ({"isError": True, "client_rejected": True, "content": [{"type": "text", "text": "Not permitted."}]},
     {"code": "CLIENT_REJECTED", "target": None, "message": "Not permitted."}),
    (error_response({"code": "WORKER_TIMEOUT", "message": "Timeout."}), None),
    ({"isError": True, "transport_error": True, "content": []}, None),
    (ok_response(), None),
])
def test_only_deterministic_failures_have_a_signature(response, expected):
    assert deterministic_failure(response) == expected


@pytest.mark.asyncio
async def test_a_repeated_invalid_calibration_is_blocked_and_stops_without_progress(tmp_path):
    # The recorded failure: identical pdf_calibrate requests with a region outside 0..1 and a zero-length segment.
    session = ScriptedSession(lambda name, arguments, count: error_response(INVALID_REGION))
    model, requests = recorded(
        model_response([{"id": "call_1", "function": {"name": "pdf_calibrate", "arguments": calibration([0, 0, 10, 10])}}]),
        # The same arguments in another key order and with another call ID are the same request.
        model_response([{"id": "call_2", "function": {"name": "pdf_calibrate",
                                                      "arguments": calibration([0, 0, 10, 10], reverse=True)}}]),
        model_response(text="Not reached."),
    )
    result = await drive(session, catalog("pdf_calibrate"), domain_plan(step_budget=45), "Skill", Trace(tmp_path),
                         model_call=model)
    assert session.calls == ["pdf_calibrate"]
    assert result["status"] == "no_progress"
    assert result["no_progress"] == {"tool": "pdf_calibrate", "repeat_count": 2, **INVALID_REGION}
    assert (result["tool_requests"], result["mcp_calls"], result["blocked_requests"]) == (2, 1, 1)
    assert len(requests) == 2  # The run stops long before the general budgets.
    second = requests[1]
    assert INVALID_REGION["target"] in second[-2]["content"]  # The original tool error.
    correction = second[-1]["content"]
    assert correction.startswith("The pdf_calibrate request failed with INVALID_ARGUMENTS at /references/0/source_region/2")
    assert "calibration when the printed dimensions are sufficient" in correction
    events = [json.loads(line) for line in (tmp_path / "trace.jsonl").read_text().splitlines()]
    kinds = [event["kind"] for event in events]
    for kind in ("tool-response", "corrective-instruction", "blocked-request", "no-progress", "summary"):
        assert kind in kinds
    assert kinds.count("corrective-instruction") == 1 and kinds.count("tool-response") == 1
    # The trace records the corrective text that the model received.
    assert next(e for e in events if e["kind"] == "corrective-instruction")["message"] == correction


@pytest.mark.asyncio
async def test_a_corrected_request_continues_to_later_steps(tmp_path):
    def respond(name, arguments, count):
        if name == "pdf_calibrate" and arguments["references"][0]["source_region"][2] > 1:
            return error_response(INVALID_REGION)
        return ok_response()
    session = ScriptedSession(respond)
    model, _ = recorded(
        model_response([call("pdf_calibrate", calibration([0, 0, 10, 10]))]),
        model_response([call("pdf_calibrate", calibration([0.1, 0.1, 0.4, 0.3], first=(120, 400), second=(320, 400)))]),
        model_response([call("part_validate", {"description": {}})]),
        model_response(text=report("Done.")),
    )
    result = await drive(session, catalog("pdf_calibrate", "part_validate"), domain_plan(), "Skill", Trace(tmp_path),
                         model_call=model)
    assert session.calls == ["pdf_calibrate", "pdf_calibrate", "part_validate"]
    assert result["status"] == "stopped_without_release" and result["blocked_requests"] == 0


@pytest.mark.asyncio
async def test_a_successful_read_can_repeat_and_a_failed_build_cannot(tmp_path):
    def respond(name, arguments, count):
        if name == "build_from_description":
            return error_response({"code": "BUILD_FAILED", "message": "The fillet failed."})
        return ok_response()
    session = ScriptedSession(respond)
    model, _ = recorded(
        model_response([call("pdf_render_page", PAGE)]),
        model_response([call("pdf_render_page", PAGE)]),
        model_response([call("build_from_description", BUILD)]),
        model_response([call("build_from_description", BUILD)]),
        model_response(text="Not reached."),
    )
    result = await drive(session, catalog("pdf_render_page", "build_from_description"), plan(step_budget=10), "Skill", Trace(tmp_path),
                         model_call=model)
    assert session.calls == ["pdf_render_page", "pdf_render_page", "build_from_description"]
    assert result["status"] == "no_progress" and result["no_progress"]["code"] == "BUILD_FAILED"


@pytest.mark.asyncio
async def test_a_changed_part_state_and_transient_errors_permit_a_new_attempt(tmp_path):
    responses = {1: error_response({"code": "BUILD_FAILED", "message": "The fillet failed."}),
                 3: error_response({"code": "WORKER_TIMEOUT", "message": "Timeout."}),
                 4: error_response({"code": "WORKER_TIMEOUT", "message": "Timeout."})}
    session = ScriptedSession(lambda name, arguments, count: responses.get(count, ok_response()))
    model, _ = recorded(
        model_response([call("build_from_description", BUILD)]),  # Fails.
        model_response([call("part_update", UPDATE)]),             # A successful mutation changes the part state.
        model_response([call("build_from_description", BUILD)]),  # Permitted again; a transient error.
        model_response([call("build_from_description", BUILD)]),  # A transient error can repeat.
        model_response(text=report("Done.")),
    )
    result = await drive(session, catalog("build_from_description", "part_update"), plan(step_budget=10), "Skill", Trace(tmp_path),
                         model_call=model)
    assert session.calls == ["build_from_description", "part_update", "build_from_description", "build_from_description"]
    assert result["status"] == "stopped_without_release" and result["blocked_requests"] == 0


@pytest.mark.asyncio
async def test_a_deadline_during_model_inference_is_a_time_budget_result(tmp_path):
    def slow(plan, payload, timeout):
        time.sleep(timeout)
        raise RuntimeError("Model endpoint did not answer: Request timed out.")
    result = await drive(Session(), [], plan(total_timeout_seconds=0.3), "Skill", Trace(tmp_path), slow)
    assert result["status"] == "time_budget_reached" and "error" not in result
    assert result["time_budget"]["phase"] == "model_inference"
    assert "did not answer" in result["time_budget"]["message"]


@pytest.mark.asyncio
async def test_a_model_error_before_the_deadline_stays_a_failure(tmp_path):
    def failed(plan, payload, timeout):
        raise RuntimeError("Model endpoint returned HTTP 400")
    result = await drive(Session(), [], plan(total_timeout_seconds=60), "Skill", Trace(tmp_path), failed)
    assert result["status"] == "failed" and "HTTP 400" in result["error"]["message"]


@pytest.mark.asyncio
async def test_a_successful_state_change_outside_the_part_permits_a_new_attempt(tmp_path):
    # part_export_review fails before export_step. After a successful export_step, the same request is legitimate.
    review = {"run_id": "localtest-a", "expected_revision": 2}
    responses = {1: error_response({"code": "NOT_EXPORTED", "message": "Export the STEP first."})}
    session = ScriptedSession(lambda name, arguments, count: responses.get(count, ok_response()))
    model, _ = recorded(
        model_response([call("part_export_review", review)]),
        model_response([call("export_step", review)]),
        model_response([call("part_export_review", review)]),
        model_response(text=report("Done.")),
    )
    result = await drive(session, catalog("part_export_review", "export_step"), plan(step_budget=10), "Skill",
                         Trace(tmp_path), model_call=model)
    assert session.calls == ["part_export_review", "export_step", "part_export_review"]
    assert result["blocked_requests"] == 0 and result["status"] == "stopped_without_release"


# A drawing_validate schema in the published form, with a local reference, a type list, and string parameters.
DECODE_SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["run_id", "drawing_spec"],
    "properties": {
        "run_id": {"type": "string"},
        "drawing_spec": {"type": "object", "properties": {
            "sheet": {"type": "object"},
            "views": {"type": "array", "items": {"$ref": "#/$defs/view"}},
            "note": {"type": "string"},
            "other": {"$ref": "#/$defs/missing"},
            "anchor": {"$ref": "#/$defs/view/properties/origin"}}},
        "tags": {"type": ["array", "null"]},
        "label": {"type": "string"},
    },
    "$defs": {"view": {"type": "object", "properties": {"origin": {"type": "array"}}}},
}
# An input value that the trace events of a decoding must not contain.
PRIVATE = "private-value-7f3a"
SPEC = {"schema_version": "2.0", "sheet": {"size": "A3"}, "views": [{"id": "front", "origin": [0, 0]}], "note": PRIVATE}


def decode_catalog():
    return [{"name": "drawing_validate", "description": "Test", "inputSchema": DECODE_SCHEMA}]


def schema_response(name, arguments):
    """The response of the MCP server: the real schema error text for the published schema, or a pass."""
    validator = Draft202012Validator(DECODE_SCHEMA)
    if validator.is_valid(arguments):
        return ok_response()
    return invalid_arguments(validator, name, arguments).model_dump(mode="json", by_alias=True)


def validate_call(arguments):
    return {"function": {"name": "drawing_validate", "arguments": arguments}}


def trace_events(path, kind):
    return [event for line in (path / "trace.jsonl").read_text().splitlines() if (event := json.loads(line))["kind"] == kind]


@pytest.mark.asyncio
async def test_an_object_argument_sent_as_json_text_reaches_the_mcp_as_an_object(tmp_path):
    received = []
    session = ScriptedSession(lambda name, arguments, count: received.append(arguments) or schema_response(name, arguments))
    model, _ = recorded(
        model_response([validate_call({"run_id": "localtest-a", "drawing_spec": json.dumps(SPEC)})]),
        model_response(text=report("Validated.")))
    result = await drive(session, decode_catalog(), plan(step_budget=5), "Skill", Trace(tmp_path), model_call=model)
    assert received == [{"run_id": "localtest-a", "drawing_spec": SPEC}]
    assert result["status"] == "stopped_without_release" and result["mcp_calls"] == 1
    assert not trace_events(tmp_path, "tool-response")[0]["response"]["isError"]
    assert "corrective-instruction" not in trace_kinds(tmp_path)
    decoded = trace_events(tmp_path, "argument-decoded")
    assert [{key: event[key] for key in ("turn", "request_number", "name", "path", "original_type", "decoded_type")}
            for event in decoded] == [{"turn": 1, "request_number": 1, "name": "drawing_validate", "path": "/drawing_spec",
                                       "original_type": "string", "decoded_type": "object"}]
    assert PRIVATE not in json.dumps(decoded) and "A3" not in json.dumps(decoded)
    # The decoding is written before the request, so that the request and its response stay adjacent.
    kinds = trace_kinds(tmp_path)
    assert kinds.index("argument-decoded") + 1 == kinds.index("tool-request") == kinds.index("tool-response") - 1
    assert trace_events(tmp_path, "tool-request")[0]["arguments"]["drawing_spec"] == SPEC
    # The model response in the trace keeps the original JSON text.
    original = trace_events(tmp_path, "model-response")[0]["response"]["message"]["tool_calls"][0]["function"]["arguments"]
    assert isinstance(original["drawing_spec"], str)


@pytest.mark.asyncio
async def test_nested_object_and_array_arguments_sent_as_json_text_are_decoded(tmp_path):
    received = []
    session = ScriptedSession(lambda name, arguments, count: received.append(arguments) or schema_response(name, arguments))
    spec = {**SPEC, "sheet": json.dumps(SPEC["sheet"]), "views": json.dumps([{"id": "front", "origin": "[0, 0]"}])}
    arguments = {"run_id": "localtest-a", "drawing_spec": json.dumps(spec), "tags": json.dumps(["a"])}
    model, _ = recorded(model_response([validate_call(arguments)]), model_response(text=report("Done.")))
    await drive(session, decode_catalog(), plan(step_budget=5), "Skill", Trace(tmp_path), model_call=model)
    assert received == [{"run_id": "localtest-a", "drawing_spec": SPEC, "tags": ["a"]}]
    assert not trace_events(tmp_path, "tool-response")[0]["response"]["isError"]
    assert [(event["path"], event["decoded_type"]) for event in trace_events(tmp_path, "argument-decoded")] == [
        ("/drawing_spec", "object"), ("/drawing_spec/sheet", "object"), ("/drawing_spec/views", "array"),
        ("/drawing_spec/views/0/origin", "array"), ("/tags", "array")]


@pytest.mark.parametrize("arguments", [
    # String parameters keep JSON text.
    {"run_id": "localtest-a", "label": '{"a": 1}', "drawing_spec": {"note": "[1, 2]"}},
    # An unresolved reference and a schema without a type keep the value.
    {"run_id": "localtest-a", "drawing_spec": {"other": "{}", "views": [{"id": "[]"}]}},
])
def test_strings_of_string_and_unknown_schemas_stay_unchanged(arguments):
    result, decoded = decode_json_text_arguments(arguments, DECODE_SCHEMA)
    assert result is arguments and decoded == []


def test_a_type_list_that_permits_a_string_keeps_the_string():
    schema = {"type": "object", "properties": {"value": {"type": ["object", "string"]}}}
    assert decode_json_text_arguments({"value": "{}"}, schema) == ({"value": "{}"}, [])


def test_a_nested_local_reference_is_resolved_as_a_json_pointer():
    arguments = {"run_id": "localtest-a", "drawing_spec": {"anchor": "[0, 0]"}}
    result, decoded = decode_json_text_arguments(arguments, DECODE_SCHEMA)
    assert result == {"run_id": "localtest-a", "drawing_spec": {"anchor": [0, 0]}}
    assert decoded == [{"path": "/drawing_spec/anchor", "original_type": "string", "decoded_type": "array"}]


@pytest.mark.parametrize("text", ['{"a": NaN}', '{"a": Infinity}', '{"a": -Infinity}', '{"a": 1e999}', '{"a": [1, {"b": -1e999}]}'])
def test_json_text_with_a_non_finite_number_stays_a_string(text):
    arguments = {"run_id": "localtest-a", "drawing_spec": text}
    result, decoded = decode_json_text_arguments(arguments, DECODE_SCHEMA)
    assert result is arguments and decoded == []


@pytest.mark.asyncio
@pytest.mark.parametrize("text", ['{"a": NaN}', '{"a": Infinity}', '{"a": 1e999}'])
async def test_json_text_with_a_non_finite_number_reaches_the_mcp_unchanged(tmp_path, text):
    received = []
    session = ScriptedSession(lambda name, arguments, count: received.append(arguments) or ok_response())
    arguments = {"run_id": "localtest-a", "drawing_spec": text}
    model, _ = recorded(model_response([validate_call(arguments)]), model_response(text=report("Done.")))
    result = await drive(session, decode_catalog(), plan(step_budget=5), "Skill", Trace(tmp_path), model_call=model)
    assert received == [arguments] and result["mcp_calls"] == 1
    assert "argument-decoded" not in trace_kinds(tmp_path)


TRUNCATED_SURROGATE_TEXTS = ['{"name": "\\ud83d"}', '{"\\ud83d": 1}', '{"a": [1, {"b": "x\\ude00y"}]}']


@pytest.mark.parametrize("text", TRUNCATED_SURROGATE_TEXTS)
def test_json_text_with_a_lone_surrogate_stays_a_string(text):
    arguments = {"run_id": "localtest-a", "drawing_spec": text}
    result, decoded = decode_json_text_arguments(arguments, DECODE_SCHEMA)
    assert result is arguments and decoded == []


def test_json_text_with_an_escaped_emoji_pair_is_decoded():
    arguments = {"run_id": "localtest-a", "drawing_spec": '{"name": "\\ud83d\\ude00"}'}
    result, decoded = decode_json_text_arguments(arguments, DECODE_SCHEMA)
    assert result == {"run_id": "localtest-a", "drawing_spec": {"name": "\U0001F600"}}
    assert [item["path"] for item in decoded] == ["/drawing_spec"]


@pytest.mark.asyncio
@pytest.mark.parametrize("text", TRUNCATED_SURROGATE_TEXTS)
async def test_json_text_with_a_lone_surrogate_reaches_the_mcp_unchanged(tmp_path, text):
    received = []
    session = ScriptedSession(lambda name, arguments, count: received.append(arguments) or ok_response())
    arguments = {"run_id": "localtest-a", "drawing_spec": text}
    model, _ = recorded(model_response([validate_call(arguments)]), model_response(text=report("Done.")))
    result = await drive(session, decode_catalog(), plan(step_budget=5), "Skill", Trace(tmp_path), model_call=model)
    assert received == [arguments] and result["mcp_calls"] == 1
    assert "argument-decoded" not in trace_kinds(tmp_path)


@pytest.mark.asyncio
async def test_a_string_parameter_with_json_text_reaches_the_mcp_unchanged(tmp_path):
    received = []
    session = ScriptedSession(lambda name, arguments, count: received.append(arguments) or schema_response(name, arguments))
    arguments = {"run_id": "localtest-a", "label": '{"a": 1}', "drawing_spec": {"note": "[1, 2]"}}
    model, _ = recorded(model_response([validate_call(arguments)]), model_response(text=report("Done.")))
    await drive(session, decode_catalog(), plan(step_budget=5), "Skill", Trace(tmp_path), model_call=model)
    assert received == [arguments] and "argument-decoded" not in trace_kinds(tmp_path)


@pytest.mark.asyncio
@pytest.mark.parametrize(("field", "text", "container"), [
    ("drawing_spec", '{"schema_version": "2.0",', "object"),  # Invalid JSON.
    ("drawing_spec", "[1, 2]", "object"),  # JSON of another type.
    ("tags", '{"a": 1}', "array"),  # An object text for an array parameter with a type list.
])
async def test_invalid_json_text_is_sent_unchanged_and_the_correction_has_a_hint(tmp_path, field, text, container):
    received = []
    session = ScriptedSession(lambda name, arguments, count: received.append(arguments) or schema_response(name, arguments))
    arguments = {"run_id": "localtest-a", "drawing_spec": {"note": PRIVATE}, field: text}
    model, requests = recorded(model_response([validate_call(arguments)]), model_response(text=report("Blocked.")))
    result = await drive(session, decode_catalog(), plan(step_budget=5), "Skill", Trace(tmp_path), model_call=model)
    assert received == [arguments] and result["mcp_calls"] == 1
    assert "argument-decoded" not in trace_kinds(tmp_path)
    correction = requests[1][-1]["content"]
    assert correction.startswith(f"The drawing_validate request failed with INVALID_ARGUMENTS at /{field}: ")
    assert f"The value at /{field} is a string. Send the JSON {container} itself, not a JSON text." in correction
    assert text not in correction and PRIVATE not in correction
    assert trace_events(tmp_path, "corrective-instruction")[0]["message"] == correction


@pytest.mark.asyncio
async def test_a_type_error_of_a_value_that_is_not_a_string_has_no_json_text_hint(tmp_path):
    session = ScriptedSession(lambda name, arguments, count: schema_response(name, arguments))
    model, requests = recorded(model_response([validate_call({"run_id": "localtest-a", "drawing_spec": 5})]),
                               model_response(text=report("Blocked.")))
    await drive(session, decode_catalog(), plan(step_budget=5), "Skill", Trace(tmp_path), model_call=model)
    correction = requests[1][-1]["content"]
    assert "fails the schema rule 'type'" in correction and "not a JSON text" not in correction


@pytest.mark.asyncio
async def test_the_repeat_guard_compares_the_decoded_arguments(tmp_path):
    # The same request as JSON text and then as an object is one request: the client blocks the second.
    session = ScriptedSession(lambda name, arguments, count: error_response(
        {"code": "LABEL_CLIPPING", "target": "/drawing_spec/views/0", "message": "A label is clipped."}))
    model, _ = recorded(
        model_response([validate_call({"run_id": "localtest-a", "drawing_spec": json.dumps(SPEC)})]),
        model_response([validate_call({"run_id": "localtest-a", "drawing_spec": SPEC})]),
        model_response(text="Not reached."))
    result = await drive(session, decode_catalog(), plan(step_budget=5), "Skill", Trace(tmp_path), model_call=model)
    assert session.calls == ["drawing_validate"]
    assert result["status"] == "no_progress" and result["blocked_requests"] == 1
