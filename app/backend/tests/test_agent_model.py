"""Translation between the drive() message format and OpenAI Chat Completions (ADR 0018)."""

import io
import json
import os

import pytest

from drawing_demo.agent import model
from drawing_demo.agent.model import (
    ModelSettings, from_openai, from_responses, make_model_call, profiles_from_env, responses_tools, to_openai, to_responses,
)


def test_tool_results_take_the_ids_of_their_calls_in_order():
    messages = [
        {"role": "system", "content": "skill"},
        {"role": "assistant", "content": "", "tool_calls": [
            {"id": "a", "function": {"name": "pdf_info", "arguments": {"path": "/x.pdf"}}},
            {"id": "b", "function": {"name": "pdf_render_page", "arguments": {"path": "/x.pdf"}}}]},
        {"role": "tool", "tool_name": "pdf_info", "content": "{}"},
        {"role": "tool", "tool_name": "pdf_render_page", "content": "{}"},
        {"role": "user", "content": "Image evidence", "images": ["QUJD"]},
    ]
    result = to_openai(messages)
    assert result[1]["tool_calls"][0] == {"id": "a", "type": "function", "function": {"name": "pdf_info", "arguments": '{"path": "/x.pdf"}'}}
    assert [m.get("tool_call_id") for m in result[2:4]] == ["a", "b"]
    assert result[4]["content"][1] == {"type": "image_url", "image_url": {"url": "data:image/png;base64,QUJD"}}


def test_a_tool_result_without_open_call_is_rejected():
    with pytest.raises(ValueError):
        to_openai([{"role": "tool", "tool_name": "x", "content": ""}])


def test_response_keeps_call_ids_and_parses_arguments():
    body = {"choices": [{"finish_reason": "tool_calls", "message": {"content": None, "tool_calls": [
        {"id": "c1", "type": "function", "function": {"name": "part_read", "arguments": '{"run_id": "web-1"}'}},
        {"id": "c2", "type": "function", "function": {"name": "part_read", "arguments": "not json"}}]}}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 3}}
    response = from_openai(body)
    calls = response["message"]["tool_calls"]
    assert calls[0] == {"id": "c1", "function": {"name": "part_read", "arguments": {"run_id": "web-1"}}}
    assert calls[1]["function"]["arguments"] == "not json"  # drive() reports this to the model as a tool error.
    assert (response["prompt_eval_count"], response["eval_count"]) == (10, 3)


def test_final_answer_has_no_tool_calls():
    response = from_openai({"choices": [{"finish_reason": "stop", "message": {"content": "Report"}}]})
    assert response["message"] == {"role": "assistant", "content": "Report"}


@pytest.mark.parametrize("header,expected", [("Authorization", "Bearer k"), ("api-key", "k")])
def test_model_call_posts_chat_completions(monkeypatch, header, expected):
    seen = {}

    class Response(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    def fake_urlopen(request, timeout):
        seen.update(url=request.full_url, header=request.get_header(header.capitalize()), body=json.loads(request.data), timeout=timeout)
        return Response(json.dumps({"choices": [{"finish_reason": "stop", "message": {"content": "ok"}}]}).encode())

    monkeypatch.setattr(model, "urlopen", fake_urlopen)
    call = make_model_call(ModelSettings("https://example.test/openai/v1", "m", "k", header))
    result = call({"options": {"temperature": 0}}, {"messages": [{"role": "user", "content": "x"}], "tools": []}, 30)
    assert result["message"]["content"] == "ok"
    assert seen["url"] == "https://example.test/openai/v1/chat/completions"
    assert seen["header"] == expected
    assert seen["body"]["model"] == "m" and seen["body"]["temperature"] == 0
    assert 29 < seen["timeout"] <= 30  # The remaining time of the call budget.


def test_settings_require_endpoint_model_and_key(monkeypatch):
    for name in ("DRAWING2CAD_AGENT_BASE_URL", "DRAWING2CAD_AGENT_MODEL", "DRAWING2CAD_AGENT_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    assert ModelSettings.from_env() is None
    monkeypatch.setenv("DRAWING2CAD_AGENT_BASE_URL", "https://example.test/v1/")
    monkeypatch.setenv("DRAWING2CAD_AGENT_MODEL", "m")
    monkeypatch.setenv("DRAWING2CAD_AGENT_API_KEY", "k")
    assert ModelSettings.from_env() == ModelSettings("https://example.test/v1", "m", "k", "Authorization")
    monkeypatch.setenv("DRAWING2CAD_AGENT_REASONING_EFFORT", "none")
    assert ModelSettings.from_env().reasoning_effort == "none"


def _response(payload):
    class Response(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False
    return Response(json.dumps(payload).encode())


def test_transient_failures_are_retried(monkeypatch):
    from urllib.error import HTTPError
    outcomes = [TimeoutError("timed out"), HTTPError("u", 503, "busy", {}, io.BytesIO(b"busy")),
                _response({"choices": [{"finish_reason": "stop", "message": {"content": "ok"}}]})]

    def fake_urlopen(request, timeout):
        outcome = outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    monkeypatch.setattr(model, "urlopen", fake_urlopen)
    monkeypatch.setattr(model, "RETRY_DELAY_SECONDS", 0)
    call = make_model_call(ModelSettings("https://example.test/v1", "m", "k"))
    assert call({}, {"messages": [], "tools": []}, 60)["message"]["content"] == "ok"
    assert outcomes == []


def test_a_client_error_is_not_retried(monkeypatch):
    from urllib.error import HTTPError
    calls = []

    def fake_urlopen(request, timeout):
        calls.append(1)
        raise HTTPError("u", 400, "bad", {}, io.BytesIO(b"tools not supported"))

    monkeypatch.setattr(model, "urlopen", fake_urlopen)
    with pytest.raises(RuntimeError, match="HTTP 400: tools not supported"):
        make_model_call(ModelSettings("https://example.test/v1", "m", "k"))({}, {"messages": [], "tools": []}, 60)
    assert len(calls) == 1


def test_each_attempt_has_its_own_bounded_timeout(monkeypatch):
    timeouts = []

    def fake_urlopen(request, timeout):
        timeouts.append(timeout)
        if len(timeouts) < 3:
            raise TimeoutError("stalled")
        return _response({"choices": [{"finish_reason": "stop", "message": {"content": "ok"}}]})

    monkeypatch.setattr(model, "urlopen", fake_urlopen)
    monkeypatch.setattr(model, "RETRY_DELAY_SECONDS", 0)
    make_model_call(ModelSettings("https://example.test/v1", "m", "k"))({}, {"messages": [], "tools": []}, 300)
    assert len(timeouts) == 3 and all(t <= model.ATTEMPT_TIMEOUT_SECONDS for t in timeouts)


def test_only_the_latest_image_messages_keep_their_images():
    messages = [{"role": "user", "content": f"img {i}", "images": [f"I{i}"]} for i in range(4)]
    result = to_openai(messages)
    assert [isinstance(m["content"], list) for m in result] == [False, False, True, True]
    assert model.OMITTED_IMAGE_NOTE in result[0]["content"]


def test_rate_limit_waits_for_retry_after(monkeypatch):
    from email.message import Message
    from urllib.error import HTTPError
    headers = Message()
    headers["Retry-After"] = "7"
    outcomes = [HTTPError("u", 429, "limit", headers, io.BytesIO(b"rate limit")),
                _response({"choices": [{"finish_reason": "stop", "message": {"content": "ok"}}]})]
    waits = []
    def fake_urlopen(request, timeout):
        outcome = outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    monkeypatch.setattr(model, "urlopen", fake_urlopen)
    monkeypatch.setattr(model.time, "sleep", waits.append)
    assert make_model_call(ModelSettings("https://example.test/v1", "m", "k"))({}, {"messages": [], "tools": []}, 300)["message"]["content"] == "ok"
    assert waits == [7.0]


def test_rate_limits_are_retried_until_the_turn_deadline(monkeypatch):
    from urllib.error import HTTPError
    clock = [0.0]
    waits = []
    monkeypatch.setattr(model.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(model.time, "sleep", lambda seconds: (waits.append(seconds), clock.__setitem__(0, clock[0] + seconds)))
    outcomes = [HTTPError("u", 429, "limit", {}, io.BytesIO(b"rate limit")) for _ in range(model.ATTEMPTS + 2)]
    outcomes.append(_response({"choices": [{"finish_reason": "stop", "message": {"content": "ok"}}]}))

    def fake_urlopen(request, timeout):
        outcome = outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    monkeypatch.setattr(model, "urlopen", fake_urlopen)
    assert make_model_call(ModelSettings("https://example.test/v1", "m", "k"))({}, {"messages": [], "tools": []}, 300)["message"]["content"] == "ok"
    # More rate-limit answers than ATTEMPTS, with longer waits up to one minute.
    assert waits == [10.0, 15.0, 30.0, 45.0, 60.0, 60.0]


def test_a_rate_limit_after_the_turn_deadline_is_reported(monkeypatch):
    from urllib.error import HTTPError
    clock = [0.0]
    monkeypatch.setattr(model.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(model.time, "sleep", lambda seconds: clock.__setitem__(0, clock[0] + seconds))
    monkeypatch.setattr(model, "urlopen", lambda request, timeout: (_ for _ in ()).throw(
        HTTPError("u", 429, "limit", {}, io.BytesIO(b"rate limit"))))
    with pytest.raises(RuntimeError, match="HTTP 429"):
        make_model_call(ModelSettings("https://example.test/v1", "m", "k"))({}, {"messages": [], "tools": []}, 100)
    assert clock[0] < 100


def test_only_recent_tool_results_and_schemas_stay_complete():
    large = "x" * (model.SHORTENED_TOOL_CHARS * 3)
    messages = [{"role": "assistant", "content": "", "tool_calls": [
        {"id": f"c{i}", "function": {"name": "t", "arguments": {}}} for i in range(model.KEPT_TOOL_RESULTS + 2)]}]
    messages += [{"role": "tool", "tool_name": "part_schema", "content": large},
                 {"role": "tool", "tool_name": "drawing_extract", "content": large}]
    messages += [{"role": "tool", "tool_name": "part_read", "content": large} for _ in range(model.KEPT_TOOL_RESULTS)]
    tools = [m for m in to_openai(messages) if m["role"] == "tool"]
    assert tools[0]["content"] == large  # A schema stays complete.
    assert tools[1]["content"].startswith("x" * model.SHORTENED_TOOL_CHARS) and model.SHORTENED_TOOL_NOTE in tools[1]["content"]
    assert len(tools[1]["content"]) < len(large)
    assert all(m["content"] == large for m in tools[2:])  # The latest results stay complete.
    assert [m["tool_call_id"] for m in tools] == [f"c{i}" for i in range(model.KEPT_TOOL_RESULTS + 2)]


def test_responses_input_has_instructions_calls_outputs_and_images():
    messages = [
        {"role": "system", "content": "Follow the skill."},
        {"role": "user", "content": "Reconstruct."},
        {"role": "assistant", "content": "", "tool_calls": [{"id": "c1", "function": {"name": "pdf_info", "arguments": {"source_id": "s"}}},
                                                           {"id": "c2", "function": {"name": "part_schema", "arguments": {}}}]},
        {"role": "tool", "tool_name": "pdf_info", "content": "{}"},
        {"role": "tool", "tool_name": "part_schema", "content": "{\"schema\": 1}"},
        {"role": "user", "content": "Image evidence.", "images": ["AAA"]},
    ]
    instructions, items = to_responses(messages)
    assert instructions == "Follow the skill."
    assert items[0] == {"role": "user", "content": "Reconstruct."}
    assert items[1] == {"type": "function_call", "call_id": "c1", "name": "pdf_info", "arguments": json.dumps({"source_id": "s"})}
    assert [i["call_id"] for i in items[3:5]] == ["c1", "c2"] and items[4]["output"] == "{\"schema\": 1}"
    assert items[5]["content"][1] == {"type": "input_image", "image_url": "data:image/png;base64,AAA"}


def test_responses_tools_are_not_strict():
    tools = [{"type": "function", "function": {"name": "pdf_info", "description": "Inspect.", "parameters": {"type": "object"}}}]
    assert responses_tools(tools) == [{"type": "function", "name": "pdf_info", "description": "Inspect.",
                                       "parameters": {"type": "object"}, "strict": False}]


def test_responses_output_becomes_the_drive_message():
    body = {"status": "completed", "usage": {"input_tokens": 120, "output_tokens": 30}, "output": [
        {"type": "reasoning", "summary": []},
        {"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": "Reading the PDF."}]},
        {"type": "function_call", "call_id": "call_1", "name": "pdf_info", "arguments": "{\"source_id\": \"s\"}"},
        {"type": "function_call", "call_id": "call_2", "name": "bad", "arguments": "{not json"},
    ]}
    result = from_responses(body)
    assert result["message"]["content"] == "Reading the PDF."
    assert result["message"]["tool_calls"][0] == {"id": "call_1", "function": {"name": "pdf_info", "arguments": {"source_id": "s"}}}
    assert result["message"]["tool_calls"][1]["function"]["arguments"] == "{not json"
    assert result["prompt_eval_count"] == 120 and result["eval_count"] == 30 and result["done_reason"] == "completed"
    with pytest.raises(ValueError):
        from_responses({"error": "x"})


def test_model_call_posts_responses_with_reasoning(monkeypatch):
    seen = {}

    def fake_urlopen(request, timeout):
        seen.update(url=request.full_url, body=json.loads(request.data))
        return _response({"status": "completed", "output": [
            {"type": "message", "content": [{"type": "output_text", "text": "ok"}]}]})

    monkeypatch.setattr(model, "urlopen", fake_urlopen)
    settings = ModelSettings("https://example.test/openai/v1", "gpt-6.1-sol", "k", "api-key", "medium", "responses")
    payload = {"messages": [{"role": "system", "content": "S"}, {"role": "user", "content": "x"}],
               "tools": [{"type": "function", "function": {"name": "t", "parameters": {}}}]}
    assert make_model_call(settings)({}, payload, 30)["message"]["content"] == "ok"
    assert seen["url"] == "https://example.test/openai/v1/responses"
    body = seen["body"]
    assert body["instructions"] == "S" and body["input"] == [{"role": "user", "content": "x"}]
    assert body["reasoning"] == {"effort": "medium"} and body["store"] is False and body["tools"][0]["strict"] is False
    assert "messages" not in body and "reasoning_effort" not in body


def test_settings_select_the_api(monkeypatch):
    for name, value in (("BASE_URL", "https://example.test/v1"), ("MODEL", "m"), ("API_KEY", "k")):
        monkeypatch.setenv("DRAWING2CAD_AGENT_" + name, value)
    monkeypatch.delenv("DRAWING2CAD_AGENT_API", raising=False)
    assert ModelSettings.from_env().api == "chat"
    monkeypatch.setenv("DRAWING2CAD_AGENT_API", "responses")
    assert ModelSettings.from_env().api == "responses"
    monkeypatch.setenv("DRAWING2CAD_AGENT_API", "completions")
    with pytest.raises(ValueError, match="chat or responses"):
        ModelSettings.from_env()


def clear_agent_environment(monkeypatch):
    for name in list(os.environ):
        if name.startswith("DRAWING2CAD_AGENT_"):
            monkeypatch.delenv(name)


def test_unprefixed_variables_make_the_default_profile(monkeypatch):
    clear_agent_environment(monkeypatch)
    assert profiles_from_env() == {}
    for name, value in (("BASE_URL", "https://example.test/v1"), ("MODEL", "m"), ("API_KEY", "k")):
        monkeypatch.setenv("DRAWING2CAD_AGENT_" + name, value)
    assert profiles_from_env() == {"Standard": ModelSettings("https://example.test/v1", "m", "k")}


def test_listed_profiles_read_their_own_variables_and_skip_incomplete_ones(monkeypatch):
    clear_agent_environment(monkeypatch)
    monkeypatch.setenv("DRAWING2CAD_AGENT_PROFILES", " Foundry , OpenRouter ")
    for name, value in (("BASE_URL", "https://foundry.test/v1"), ("MODEL", "gpt"), ("API_KEY", "k"),
                        ("API_KEY_HEADER", "api-key"), ("API", "responses")):
        monkeypatch.setenv("DRAWING2CAD_AGENT_FOUNDRY_" + name, value)
    monkeypatch.setenv("DRAWING2CAD_AGENT_OPENROUTER_MODEL", "vendor/model")
    profiles = profiles_from_env()
    assert list(profiles) == ["Foundry"]
    assert profiles["Foundry"] == ModelSettings("https://foundry.test/v1", "gpt", "k", "api-key", None, "responses")


@pytest.mark.parametrize("names", ["Foundry,foundry", "Open-Router", "1st"])
def test_invalid_or_repeated_profile_names_are_rejected(monkeypatch, names):
    clear_agent_environment(monkeypatch)
    monkeypatch.setenv("DRAWING2CAD_AGENT_PROFILES", names)
    with pytest.raises(ValueError):
        profiles_from_env()


@pytest.mark.parametrize("base_url, expected", [
    ("https://openrouter.ai/api/v1", {"reasoning": {"effort": "low"}}),
    ("https://res.openai.azure.com/openai/v1", {"reasoning_effort": "low"}),
])
def test_chat_reasoning_uses_the_parameter_of_the_provider(base_url, expected):
    settings = ModelSettings(base_url, "m", "k", reasoning_effort="low")
    path, _, body = model.request_for(settings, {"messages": [{"role": "user", "content": "x"}], "tools": []})
    assert path == "/chat/completions"
    assert {k: body[k] for k in ("reasoning", "reasoning_effort") if k in body} == expected
