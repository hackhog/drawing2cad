"""Translation between the drive() message format and OpenAI Chat Completions (ADR 0018)."""

import json
import os

import httpx2
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


OK_CHAT = {"choices": [{"finish_reason": "stop", "message": {"content": "ok"}}]}


def fake_endpoint(monkeypatch, outcomes):
    """Send the SDK requests to a mock transport. Each outcome is an answer body, an httpx2.Response, or an exception.

    A single outcome that is not a list answers every request. The returned list records each request as
    (URL, headers, JSON body, read timeout).
    """
    seen = []
    real_client_for = model.client_for

    def handle(request):
        seen.append((str(request.url), request.headers, json.loads(request.content), request.extensions["timeout"]["read"]))
        outcome = outcomes.pop(0) if isinstance(outcomes, list) else outcomes
        if isinstance(outcome, Exception):
            raise outcome
        return outcome if isinstance(outcome, httpx2.Response) else httpx2.Response(200, json=outcome)

    monkeypatch.setattr(model, "client_for", lambda settings: real_client_for(settings, httpx2.MockTransport(handle)))
    return seen


@pytest.mark.parametrize("header,expected", [("Authorization", "Bearer k"), ("api-key", "k")])
def test_model_call_posts_chat_completions(monkeypatch, header, expected):
    seen = fake_endpoint(monkeypatch, [OK_CHAT])
    call = make_model_call(ModelSettings("https://example.test/openai/v1", "m", "k", header))
    result = call({"options": {"temperature": 0}}, {"messages": [{"role": "user", "content": "x"}], "tools": []}, 30)
    assert result["message"]["content"] == "ok"
    url, headers, body, timeout = seen[0]
    assert url == "https://example.test/openai/v1/chat/completions"
    assert headers[header] == expected
    assert body["model"] == "m" and body["temperature"] == 0
    assert 29 < timeout <= 30  # The remaining time of the call budget.


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


def test_transient_failures_are_retried(monkeypatch):
    outcomes = [httpx2.ReadTimeout("timed out"), httpx2.Response(503, text="busy"), httpx2.ConnectError("refused"), OK_CHAT]
    fake_endpoint(monkeypatch, outcomes)
    monkeypatch.setattr(model, "RETRY_DELAY_SECONDS", 0)
    call = make_model_call(ModelSettings("https://example.test/v1", "m", "k"))
    assert call({}, {"messages": [], "tools": []}, 60)["message"]["content"] == "ok"
    assert outcomes == []


def test_retryable_failures_stop_after_the_attempt_limit(monkeypatch):
    seen = fake_endpoint(monkeypatch, httpx2.Response(503, text="busy"))
    monkeypatch.setattr(model, "RETRY_DELAY_SECONDS", 0)
    with pytest.raises(RuntimeError, match="HTTP 503: busy"):
        make_model_call(ModelSettings("https://example.test/v1", "m", "k"))({}, {"messages": [], "tools": []}, 60)
    assert len(seen) == model.ATTEMPTS


def test_a_client_error_is_not_retried(monkeypatch):
    seen = fake_endpoint(monkeypatch, httpx2.Response(400, text="tools not supported"))
    with pytest.raises(RuntimeError, match="HTTP 400: tools not supported"):
        make_model_call(ModelSettings("https://example.test/v1", "m", "k"))({}, {"messages": [], "tools": []}, 60)
    assert len(seen) == 1


def test_each_attempt_has_its_own_bounded_timeout(monkeypatch):
    seen = fake_endpoint(monkeypatch, [httpx2.ReadTimeout("stalled"), httpx2.ReadTimeout("stalled"), OK_CHAT])
    monkeypatch.setattr(model, "RETRY_DELAY_SECONDS", 0)
    make_model_call(ModelSettings("https://example.test/v1", "m", "k"))({}, {"messages": [], "tools": []}, 300)
    assert len(seen) == 3 and all(timeout <= 150 for *_, timeout in seen)


def test_a_short_turn_deadline_keeps_the_minimum_attempt_timeout(monkeypatch):
    seen = fake_endpoint(monkeypatch, OK_CHAT)
    make_model_call(ModelSettings("https://example.test/v1", "m", "k"))({}, {"messages": [], "tools": []}, 200)
    assert seen[0][-1] == pytest.approx(model.ATTEMPT_TIMEOUT_SECONDS, abs=1)


def test_a_long_turn_deadline_allows_a_long_attempt_and_one_retry(monkeypatch):
    # A slow model needs more than the minimum attempt timeout for one answer.
    seen = fake_endpoint(monkeypatch, [httpx2.ReadTimeout("stalled"), OK_CHAT])
    monkeypatch.setattr(model, "RETRY_DELAY_SECONDS", 0)
    clock = [0.0]
    monkeypatch.setattr(model.time, "monotonic", lambda: clock[0])
    original = model._post

    def slow_post(*args):
        clock[0] += args[-1]  # A stalled attempt uses its complete timeout.
        return original(*args)

    monkeypatch.setattr(model, "_post", slow_post)
    make_model_call(ModelSettings("https://example.test/v1", "m", "k"))({}, {"messages": [], "tools": []}, 1500)
    assert [timeout for *_, timeout in seen] == [pytest.approx(750), pytest.approx(750)]


def test_a_response_above_the_size_limit_is_rejected(monkeypatch):
    monkeypatch.setattr(model, "MAX_RESPONSE_BYTES", 100)
    fake_endpoint(monkeypatch, httpx2.Response(200, content=b"x" * 1000))
    with pytest.raises(ValueError, match="exceeds"):
        make_model_call(ModelSettings("https://example.test/v1", "m", "k"))({}, {"messages": [], "tools": []}, 60)


def test_only_the_latest_image_messages_keep_their_images():
    messages = [{"role": "user", "content": f"img {i}", "images": [f"I{i}"]} for i in range(4)]
    result = to_openai(messages)
    assert [isinstance(m["content"], list) for m in result] == [False, False, True, True]
    assert model.OMITTED_IMAGE_NOTE in result[0]["content"]


def test_rate_limit_waits_for_retry_after(monkeypatch):
    outcomes = [httpx2.Response(429, headers={"Retry-After": "7"}, text="rate limit"), OK_CHAT]
    waits = []
    fake_endpoint(monkeypatch, outcomes)
    monkeypatch.setattr(model.time, "sleep", waits.append)
    assert make_model_call(ModelSettings("https://example.test/v1", "m", "k"))({}, {"messages": [], "tools": []}, 300)["message"]["content"] == "ok"
    assert waits == [7.0]


def test_rate_limits_are_retried_until_the_turn_deadline(monkeypatch):
    clock = [0.0]
    waits = []
    monkeypatch.setattr(model.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(model.time, "sleep", lambda seconds: (waits.append(seconds), clock.__setitem__(0, clock[0] + seconds)))
    outcomes = [httpx2.Response(429, text="rate limit") for _ in range(model.ATTEMPTS + 2)] + [OK_CHAT]
    fake_endpoint(monkeypatch, outcomes)
    assert make_model_call(ModelSettings("https://example.test/v1", "m", "k"))({}, {"messages": [], "tools": []}, 300)["message"]["content"] == "ok"
    # More rate-limit answers than ATTEMPTS, with longer waits up to one minute.
    assert waits == [10.0, 15.0, 30.0, 45.0, 60.0, 60.0]


def test_a_rate_limit_after_the_turn_deadline_is_reported(monkeypatch):
    clock = [0.0]
    monkeypatch.setattr(model.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(model.time, "sleep", lambda seconds: clock.__setitem__(0, clock[0] + seconds))
    fake_endpoint(monkeypatch, httpx2.Response(429, text="rate limit"))
    with pytest.raises(RuntimeError, match="HTTP 429: rate limit"):
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
    seen = fake_endpoint(monkeypatch, [{"status": "completed", "output": [
        {"type": "message", "content": [{"type": "output_text", "text": "ok"}]}]}])
    settings = ModelSettings("https://example.test/openai/v1", "gpt-6.1-sol", "k", "api-key", "medium", "responses")
    payload = {"messages": [{"role": "system", "content": "S"}, {"role": "user", "content": "x"}],
               "tools": [{"type": "function", "function": {"name": "t", "parameters": {}}}]}
    assert make_model_call(settings)({}, payload, 30)["message"]["content"] == "ok"
    url, _, body, _ = seen[0]
    assert url == "https://example.test/openai/v1/responses"
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


PROVIDERS = [
    # Profile settings, the expected key header and value, a header that must be absent, and the reasoning fields.
    (ModelSettings("https://openrouter.ai/api/v1", "vendor/m", "k", reasoning_effort="low"),
     ("authorization", "Bearer k"), "api-key", {"reasoning": {"effort": "low"}}),
    (ModelSettings("https://res.openai.azure.com/openai/v1", "gpt", "k", "api-key", "low"),
     ("api-key", "k"), "authorization", {"reasoning_effort": "low"}),
    (ModelSettings("https://api.openai.com/v1", "gpt", "k", reasoning_effort="high"),
     ("authorization", "Bearer k"), "api-key", {"reasoning_effort": "high"}),
    (ModelSettings("http://localhost:11434/v1", "qwen", "ollama"),
     ("authorization", "Bearer ollama"), "api-key", {}),
]


@pytest.mark.parametrize("settings, key_header, absent_header, reasoning", PROVIDERS)
def test_the_sdk_sends_the_chat_body_and_headers_of_each_provider(monkeypatch, settings, key_header, absent_header, reasoning):
    seen = fake_endpoint(monkeypatch, [OK_CHAT])
    payload = {"messages": [{"role": "system", "content": "S"}, {"role": "user", "content": "x"}], "tools": [model.CHECK_TOOL]}
    options = {"temperature": 0, "max_tokens": 50}
    make_model_call(settings)({"options": options}, payload, 30)
    url, headers, body, _ = seen[0]
    assert url == settings.base_url + "/chat/completions"
    assert headers[key_header[0]] == key_header[1] and absent_header not in headers
    # The SDK sends the body of request_for without change, including the options and the reasoning fields.
    assert body == model.request_for(settings, payload, options)[2]
    assert {k: body[k] for k in ("reasoning", "reasoning_effort") if k in body} == reasoning


@pytest.mark.parametrize("settings, key_header, absent_header, reasoning", PROVIDERS[:2])
def test_the_sdk_sends_the_responses_body_without_change(monkeypatch, settings, key_header, absent_header, reasoning):
    settings = ModelSettings(settings.base_url, settings.model, settings.api_key, settings.api_key_header, "medium", "responses")
    seen = fake_endpoint(monkeypatch, [{"status": "completed", "output": []}])
    payload = {"messages": [{"role": "system", "content": "S"}, {"role": "user", "content": "x"}], "tools": [model.CHECK_TOOL]}
    make_model_call(settings)({"options": {"max_output_tokens": 50}}, payload, 30)
    url, headers, body, _ = seen[0]
    assert url == settings.base_url + "/responses"
    assert headers[key_header[0]] == key_header[1] and absent_header not in headers
    assert body == model.request_for(settings, payload, {"max_output_tokens": 50})[2]
    assert body["store"] is False and body["reasoning"] == {"effort": "medium"}


def test_the_connection_check_reports_the_status_and_body(monkeypatch):
    fake_endpoint(monkeypatch, httpx2.Response(401, text="invalid key"))
    result = model.check_connection(ModelSettings("https://example.test/v1", "m", "k"))
    assert result == {"ok": False, "message": "HTTP 401: invalid key"}


class BodyStream(httpx2.SyncByteStream):
    """A response body that sends `chunks` and then raises `error`, if any. `sent` counts the sent chunks."""

    def __init__(self, chunks, error=None):
        self.chunks, self.error, self.sent = chunks, error, 0

    def __iter__(self):
        for chunk in self.chunks:
            self.sent += 1
            yield chunk
        if self.error is not None:
            raise self.error


@pytest.mark.parametrize("error", [httpx2.ReadTimeout("stalled"), httpx2.RemoteProtocolError("peer closed")])
def test_a_failure_while_the_body_is_read_is_retried(monkeypatch, error):
    outcomes = [httpx2.Response(200, stream=BodyStream([b'{"choices": '], error)), OK_CHAT]
    seen = fake_endpoint(monkeypatch, outcomes)
    monkeypatch.setattr(model, "RETRY_DELAY_SECONDS", 0)
    assert make_model_call(ModelSettings("https://example.test/v1", "m", "k"))({}, {"messages": [], "tools": []}, 60)["message"]["content"] == "ok"
    assert len(seen) == 2


def test_failures_while_the_body_is_read_stop_after_the_attempt_limit(monkeypatch):
    seen = fake_endpoint(monkeypatch, [httpx2.Response(200, stream=BodyStream([b"{"], httpx2.ReadTimeout("stalled")))
                                       for _ in range(model.ATTEMPTS)])
    monkeypatch.setattr(model, "RETRY_DELAY_SECONDS", 0)
    with pytest.raises(RuntimeError, match="did not answer"):
        make_model_call(ModelSettings("https://example.test/v1", "m", "k"))({}, {"messages": [], "tools": []}, 60)
    assert len(seen) == model.ATTEMPTS


def test_the_connection_check_reports_a_failure_while_the_body_is_read(monkeypatch):
    fake_endpoint(monkeypatch, httpx2.Response(200, stream=BodyStream([b"{"], httpx2.ReadTimeout("stalled"))))
    result = model.check_connection(ModelSettings("https://example.test/v1", "m", "k"))
    assert result["ok"] is False and result["message"].startswith("APITimeoutError")


def test_an_error_body_is_read_only_up_to_the_error_limit(monkeypatch):
    chunk = b"e" * (16 * 1024)
    stream = BodyStream([chunk] * 1280)  # 20 MiB
    fake_endpoint(monkeypatch, httpx2.Response(400, stream=stream))
    with pytest.raises(RuntimeError, match="HTTP 400: e{4096}$"):
        make_model_call(ModelSettings("https://example.test/v1", "m", "k"))({}, {"messages": [], "tools": []}, 60)
    assert stream.sent * len(chunk) <= model.MAX_ERROR_BYTES


def test_the_connection_check_reads_an_error_body_only_up_to_the_error_limit(monkeypatch):
    chunk = b"e" * (16 * 1024)
    stream = BodyStream([chunk] * 1280)
    fake_endpoint(monkeypatch, httpx2.Response(429, stream=stream))
    result = model.check_connection(ModelSettings("https://example.test/v1", "m", "k"))
    assert result == {"ok": False, "message": "HTTP 429: " + "e" * 2000}
    assert stream.sent * len(chunk) <= model.MAX_ERROR_BYTES


@pytest.fixture
def environment_proxy(monkeypatch):
    """A local HTTP proxy set in HTTP_PROXY. It records the request targets and sends the answer in `answer`."""
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    import threading

    state = {"targets": [], "answer": (200, json.dumps(OK_CHAT).encode())}

    class Proxy(BaseHTTPRequestHandler):
        def do_POST(self):
            self.rfile.read(int(self.headers.get("Content-Length", 0)))
            state["targets"].append(self.path)
            status, body = state["answer"]
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Proxy)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    for name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY"):
        monkeypatch.delenv(name, raising=False)
        monkeypatch.delenv(name.lower(), raising=False)
    monkeypatch.setenv("HTTP_PROXY", f"http://127.0.0.1:{server.server_address[1]}")
    yield state
    server.shutdown()
    server.server_close()


def test_model_calls_use_the_proxy_of_the_environment(environment_proxy):
    call = make_model_call(ModelSettings("http://model.test/v1", "m", "k"))
    assert call({}, {"messages": [], "tools": []}, 30)["message"]["content"] == "ok"
    assert environment_proxy["targets"] == ["http://model.test/v1/chat/completions"]


def test_the_error_body_limit_applies_through_the_proxy(environment_proxy, monkeypatch):
    monkeypatch.setattr(model, "MAX_ERROR_BYTES", 10)
    environment_proxy["answer"] = (400, b"0123456789ABCDEF")
    with pytest.raises(RuntimeError, match="HTTP 400: 0123456789$"):
        make_model_call(ModelSettings("http://model.test/v1", "m", "k"))({}, {"messages": [], "tools": []}, 30)
    assert len(environment_proxy["targets"]) == 1


def test_no_proxy_hosts_do_not_use_the_proxy(environment_proxy, monkeypatch):
    monkeypatch.setenv("NO_PROXY", "model.test")
    result = model.check_connection(ModelSettings("http://model.test/v1", "m", "k"), timeout=10)
    assert result["ok"] is False and environment_proxy["targets"] == []


def test_a_failed_tool_call_reaches_the_model_with_its_error_text():
    from drawing2cad_mcp.local_model_client import response_messages
    from drawing_demo.agent.model import to_openai

    error = {"code": "INVALID_ARGUMENTS", "target": "/references/0/source_region/2",
             "message": "source_region is [left, top, right, bottom] as fractions 0..1 of the displayed page."}
    raw = {"isError": True, "structuredContent": {"error": error}, "content": [{"type": "text", "text": json.dumps({"error": error})}]}
    call = {"id": "call-1", "function": {"name": "pdf_calibrate", "arguments": {}}}
    messages = [{"role": "system", "content": "s"}, {"role": "assistant", "content": "", "tool_calls": [call]},
                *response_messages("pdf_calibrate", raw, 4000)]
    tool = next(message for message in to_openai(messages) if message["role"] == "tool")
    assert "Tool error INVALID_ARGUMENTS at /references/0/source_region/2" in tool["content"]
