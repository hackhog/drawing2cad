"""Translation between the drive() message format and OpenAI Chat Completions (ADR 0018)."""

import io
import json

import pytest

from drawing_demo.agent import model
from drawing_demo.agent.model import ModelSettings, from_openai, make_model_call, to_openai


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
