"""Model call for OpenAI-compatible Chat Completions and Responses endpoints (ADR 0018).

`drawing2cad_mcp.local_model_client.drive` exchanges messages in the Ollama chat format.
This module translates them to Chat Completions or to the Responses API and back, so that Azure AI Foundry,
OpenRouter, OpenAI, or the OpenAI endpoint of Ollama can supply the model. Some models (for example, gpt-6.1-sol
on Azure AI Foundry) accept function tools with reasoning only through the Responses API.
The official openai SDK is the HTTP transport only. This module keeps the retry policy, the response size limit,
and the translation. It reads no files and runs no tools.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import logging
import os
import re
import time
from typing import Any
from urllib.parse import urlsplit

import httpx2
from openai import APIConnectionError, APIStatusError, Omit, OpenAI

log = logging.getLogger(__name__)

# The SDK has no response size limit. A streamed read stops after this limit.
MAX_RESPONSE_BYTES = 8 * 1024 * 1024
ENV_PREFIX = "DRAWING2CAD_AGENT_"
# A profile name is also part of its variable names, for example Foundry -> DRAWING2CAD_AGENT_FOUNDRY_MODEL.
PROFILE_NAME = re.compile(r"[A-Za-z][A-Za-z0-9]{0,31}")
# The profile of the unprefixed DRAWING2CAD_AGENT_* variables when DRAWING2CAD_AGENT_PROFILES is not set.
DEFAULT_PROFILE = "Standard"
# A hosted endpoint can fail transiently (spike: one Azure server error; web run: one request without answer).
# The SDK retries are off (max_retries=0): they have no turn deadline and do not retry a rate limit until it clears.
ATTEMPTS = 4
RETRY_STATUS = {408, 429, 500, 502, 503, 504}
RETRY_DELAY_SECONDS = 2.0
# A token rate limit (web run: 100k tokens per minute, about 45k per turn) clears within a minute. Retry it until the
# turn deadline, with longer waits after each further rate-limit answer. Other failures keep the ATTEMPTS limit.
RATE_LIMIT_STEP_SECONDS = 15.0
RATE_LIMIT_MAX_WAIT_SECONDS = 60.0
# Normal answers took 2-45 s; a stalled connection must not use the whole call budget in one attempt.
ATTEMPT_TIMEOUT_SECONDS = 120.0
# Each image costs many tokens in every later turn. Older images are replaced by a note; the trace keeps them.
KEPT_IMAGE_MESSAGES = 2
OMITTED_IMAGE_NOTE = "[Earlier image evidence omitted to limit tokens. Request the region again with pdf_crop_region if needed.]"
# Each turn sends the complete conversation. In a web run on Fuss, turn 17 exceeded 100k prompt tokens, which is the
# complete token rate limit of the deployment for one minute, so no retry could succeed. Older large tool results are
# shortened; the most recent results and the schemas stay complete. The trace keeps every complete result.
KEPT_TOOL_RESULTS = 6
SHORTENED_TOOL_CHARS = 2000
COMPLETE_TOOL_RESULTS = {"part_schema", "drawing_schema"}
CHECK_PROMPT = "Answer only with OK. Do not call a tool."
# The connection check offers one tool, because agent runs always send tools.
CHECK_TOOL = {"type": "function", "function": {"name": "noop", "description": "Not used.",
                                               "parameters": {"type": "object", "properties": {}}}}
SHORTENED_TOOL_NOTE = "[Earlier tool result shortened to limit tokens. Call the tool again if you need the complete result.]"


@dataclass(frozen=True)
class ModelSettings:
    base_url: str
    model: str
    api_key: str
    # Azure AI Foundry accepts "api-key"; most other providers use "Authorization: Bearer".
    api_key_header: str = "Authorization"
    # Some models reject function tools with reasoning on Chat Completions (for example, gpt-6.1-sol needs "none").
    reasoning_effort: str | None = None
    # "chat" (Chat Completions) or "responses" (Responses API).
    api: str = "chat"

    @classmethod
    def from_env(cls, prefix: str = ENV_PREFIX) -> "ModelSettings | None":
        """Return the endpoint of the variables with this prefix, or None if it is not configured."""
        base_url = os.environ.get(prefix + "BASE_URL", "").strip()
        model = os.environ.get(prefix + "MODEL", "").strip()
        api_key = os.environ.get(prefix + "API_KEY", "").strip()
        if not (base_url and model and api_key):
            return None
        header = os.environ.get(prefix + "API_KEY_HEADER", "Authorization").strip() or "Authorization"
        effort = os.environ.get(prefix + "REASONING_EFFORT", "").strip() or None
        api = os.environ.get(prefix + "API", "chat").strip() or "chat"
        if api not in ("chat", "responses"):
            raise ValueError(f"{prefix}API must be chat or responses.")
        return cls(base_url.rstrip("/"), model, api_key, header, effort, api)

    def headers(self) -> dict[str, str]:
        value = f"Bearer {self.api_key}" if self.api_key_header.lower() == "authorization" else self.api_key
        return {"Content-Type": "application/json", self.api_key_header: value}


def profiles_from_env() -> dict[str, ModelSettings]:
    """The configured model profiles by name, in configuration order. The first profile is active at start.

    DRAWING2CAD_AGENT_PROFILES lists the names, for example "Foundry,OpenRouter". Each profile reads the
    DRAWING2CAD_AGENT_<NAME>_* variables. Without the list, the unprefixed variables make one profile.
    A profile without endpoint, model, or key is skipped, so that the service starts without keys.
    """
    names = [name.strip() for name in os.environ.get(ENV_PREFIX + "PROFILES", "").split(",") if name.strip()]
    if not names:
        settings = ModelSettings.from_env()
        return {DEFAULT_PROFILE: settings} if settings else {}
    profiles: dict[str, ModelSettings] = {}
    prefixes: set[str] = set()
    for name in names:
        if not PROFILE_NAME.fullmatch(name):
            raise ValueError(f"Profile name {name!r} in {ENV_PREFIX}PROFILES must be a letter and up to 31 letters or digits.")
        prefix = f"{ENV_PREFIX}{name.upper()}_"
        if prefix in prefixes:
            raise ValueError(f"Profile name {name!r} occurs more than once in {ENV_PREFIX}PROFILES.")
        prefixes.add(prefix)
        settings = ModelSettings.from_env(prefix)
        if settings is None:
            log.warning("Model profile %s skipped: %sBASE_URL, %sMODEL, or %sAPI_KEY is missing.", name, prefix, prefix, prefix)
            continue
        profiles[name] = settings
    return profiles


def _token_limits(messages: list[dict[str, Any]]) -> tuple[set[int], set[int]]:
    """Positions of the image messages and tool results that are sent complete."""
    image_positions = [i for i, m in enumerate(messages) if m.get("images")]
    tool_positions = [i for i, m in enumerate(messages) if m["role"] == "tool"]
    return set(image_positions[-KEPT_IMAGE_MESSAGES:]), set(tool_positions[-KEPT_TOOL_RESULTS:])


def _tool_content(message: dict[str, Any], complete: bool) -> str:
    content = message.get("content", "")
    if not complete and message.get("tool_name") not in COMPLETE_TOOL_RESULTS and len(content) > SHORTENED_TOOL_CHARS:
        return f"{content[:SHORTENED_TOOL_CHARS]} {SHORTENED_TOOL_NOTE}"
    return content


def to_openai(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Translate Ollama-style messages to Chat Completions messages.

    A tool result in the Ollama format has no call ID. `drive` appends results in request order,
    so each result takes the next open ID of the preceding assistant message.
    """
    result: list[dict[str, Any]] = []
    open_ids: list[str] = []
    kept, complete_tools = _token_limits(messages)
    for position, message in enumerate(messages):
        role = message["role"]
        if role == "assistant":
            calls = message.get("tool_calls") or []
            open_ids = [call["id"] for call in calls]
            converted: dict[str, Any] = {"role": "assistant", "content": message.get("content") or None}
            if calls:
                converted["tool_calls"] = [{
                    "id": call["id"], "type": "function",
                    "function": {"name": call["function"]["name"], "arguments": _arguments_text(call["function"].get("arguments"))},
                } for call in calls]
            result.append(converted)
        elif role == "tool":
            if not open_ids:
                raise ValueError("A tool result has no open tool call.")
            result.append({"role": "tool", "tool_call_id": open_ids.pop(0),
                           "content": _tool_content(message, position in complete_tools)})
        elif message.get("images") and position not in kept:
            result.append({"role": role, "content": f"{message.get('content', '')} {OMITTED_IMAGE_NOTE}"})
        elif message.get("images"):
            parts: list[dict[str, Any]] = [{"type": "text", "text": message.get("content", "")}]
            parts += [{"type": "image_url", "image_url": {"url": "data:image/png;base64," + image}} for image in message["images"]]
            result.append({"role": role, "content": parts})
        else:
            result.append({"role": role, "content": message.get("content", "")})
    return result


def to_responses(messages: list[dict[str, Any]]) -> tuple[str | None, list[dict[str, Any]]]:
    """Translate Ollama-style messages to Responses API instructions and input items.

    The system message becomes the instructions. Tool calls and results become function_call and
    function_call_output items; results take the open call IDs in request order, as in `to_openai`.
    Requests are stateless (store=false); reasoning items of earlier turns are not sent again.
    """
    instructions: str | None = None
    items: list[dict[str, Any]] = []
    open_ids: list[str] = []
    kept, complete_tools = _token_limits(messages)
    for position, message in enumerate(messages):
        role = message["role"]
        if role == "system" and instructions is None:
            instructions = message.get("content", "")
        elif role == "assistant":
            if message.get("content"):
                items.append({"role": "assistant", "content": message["content"]})
            calls = message.get("tool_calls") or []
            open_ids = [call["id"] for call in calls]
            items += [{"type": "function_call", "call_id": call["id"], "name": call["function"]["name"],
                       "arguments": _arguments_text(call["function"].get("arguments"))} for call in calls]
        elif role == "tool":
            if not open_ids:
                raise ValueError("A tool result has no open tool call.")
            items.append({"type": "function_call_output", "call_id": open_ids.pop(0),
                          "output": _tool_content(message, position in complete_tools)})
        elif message.get("images") and position not in kept:
            items.append({"role": role, "content": f"{message.get('content', '')} {OMITTED_IMAGE_NOTE}"})
        elif message.get("images"):
            parts: list[dict[str, Any]] = [{"type": "input_text", "text": message.get("content", "")}]
            parts += [{"type": "input_image", "image_url": "data:image/png;base64," + image} for image in message["images"]]
            items.append({"role": role, "content": parts})
        else:
            items.append({"role": role, "content": message.get("content", "")})
    return instructions, items


def responses_tools(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Function tools in the Responses format. The MCP schemas are not written for strict validation."""
    return [{"type": "function", "name": tool["function"]["name"], "description": tool["function"].get("description", ""),
             "parameters": tool["function"].get("parameters", {}), "strict": False} for tool in tools]


def _parsed_arguments(text: str) -> Any:
    try:
        return json.loads(text) if text else {}
    except ValueError:
        # Keep invalid JSON visible; drive() rejects non-object arguments with a tool error.
        return text


def from_responses(body: dict[str, Any]) -> dict[str, Any]:
    """Translate a Responses API result to the Ollama response shape that `drive` reads."""
    output = body.get("output")
    if not isinstance(output, list):
        raise ValueError("The model returned no output.")
    texts = [part.get("text", "") for item in output if item.get("type") == "message"
             for part in item.get("content") or [] if part.get("type") == "output_text"]
    calls = [{"id": item["call_id"], "function": {"name": item["name"], "arguments": _parsed_arguments(item.get("arguments", ""))}}
             for item in output if item.get("type") == "function_call"]
    usage = body.get("usage") or {}
    return {
        "message": {"role": "assistant", "content": "".join(texts), **({"tool_calls": calls} if calls else {})},
        "done_reason": (body.get("incomplete_details") or {}).get("reason") or body.get("status"),
        "prompt_eval_count": usage.get("input_tokens"),
        "eval_count": usage.get("output_tokens"),
    }


def _arguments_text(arguments: Any) -> str:
    return arguments if isinstance(arguments, str) else json.dumps(arguments if arguments is not None else {}, ensure_ascii=False)


def from_openai(body: dict[str, Any]) -> dict[str, Any]:
    """Translate a Chat Completions response to the Ollama response shape that `drive` reads."""
    choices = body.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0].get("message"), dict):
        raise ValueError("The model returned no message.")
    message = choices[0]["message"]
    calls = []
    for call in message.get("tool_calls") or []:
        arguments = _parsed_arguments(call.get("function", {}).get("arguments", "{}"))
        calls.append({"id": call["id"], "function": {"name": call["function"]["name"], "arguments": arguments}})
    usage = body.get("usage") or {}
    response: dict[str, Any] = {
        "message": {"role": "assistant", "content": message.get("content") or "", **({"tool_calls": calls} if calls else {})},
        "done_reason": choices[0].get("finish_reason"),
        "prompt_eval_count": usage.get("prompt_tokens"),
        "eval_count": usage.get("completion_tokens"),
    }
    return response


def _retry_after(headers: Any) -> float:
    """Seconds to wait after a rate-limit answer: the Retry-After header, else a fixed delay."""
    try:
        return max(RETRY_DELAY_SECONDS, float(headers.get("Retry-After", "")))
    except (TypeError, ValueError):
        return 10.0


# The keys that the SDK method accepts as named arguments. Other keys (call options and the OpenRouter reasoning
# object) go into extra_body. The SDK merges extra_body into the JSON body without change.
SDK_ARGUMENTS = {
    "/chat/completions": {"model", "messages", "tools", "reasoning_effort"},
    "/responses": {"model", "input", "tools", "store", "instructions", "reasoning"},
}


def client_for(settings: ModelSettings, transport: Any = None) -> OpenAI:
    """An OpenAI SDK client for the endpoint of the profile. The SDK does not retry; `make_model_call` does.

    `transport` replaces the network connection of the SDK, for example with an httpx2.MockTransport in tests.
    """
    return OpenAI(api_key=settings.api_key, base_url=settings.base_url, max_retries=0,
                  http_client=httpx2.Client(transport=transport) if transport is not None else None)


def _auth_headers(settings: ModelSettings) -> dict[str, Any]:
    """Request headers for a key header other than Authorization, for example "api-key" on Azure AI Foundry.

    The SDK always sends "Authorization: Bearer <key>". It accepts the removal of that header only in the request
    headers, not in the client headers.
    """
    if settings.api_key_header.lower() == "authorization":
        return {}
    return {"Authorization": Omit(), settings.api_key_header: settings.api_key}


def _post(client: OpenAI, settings: ModelSettings, path: str, body: dict[str, Any], timeout: float) -> bytes:
    """Send one request through the SDK and return the raw response body, at most MAX_RESPONSE_BYTES + 1 bytes.

    The raw body goes to the existing parsers, so that the SDK models do not change the fields that `drive` reads.
    A streamed read keeps the memory limit for a defective or hostile endpoint.
    """
    resource = client.chat.completions if path == "/chat/completions" else client.responses
    named = {key: value for key, value in body.items() if key in SDK_ARGUMENTS[path]}
    extra = {key: value for key, value in body.items() if key not in SDK_ARGUMENTS[path]}
    with resource.with_streaming_response.create(**named, extra_body=extra or None,
                                                 extra_headers=_auth_headers(settings) or None,
                                                 timeout=timeout) as response:
        raw = bytearray()
        for chunk in response.iter_bytes():
            raw += chunk
            if len(raw) > MAX_RESPONSE_BYTES:
                break
    return bytes(raw[:MAX_RESPONSE_BYTES + 1])


def _parse_limited(parse, raw: bytes) -> dict[str, Any]:
    if len(raw) > MAX_RESPONSE_BYTES:
        raise ValueError("The model response exceeds 8 MiB.")
    return parse(json.loads(raw))


def request_for(settings: ModelSettings, payload: dict[str, Any], options: dict[str, Any] | None = None):
    """Path, response parser, and body of one request for `drive()` messages and tools on the selected API."""
    if settings.api == "responses":
        instructions, items = to_responses(payload["messages"])
        body: dict[str, Any] = {"model": settings.model, "input": items, "tools": responses_tools(payload["tools"]),
                                "store": False, **(options or {})}
        if instructions is not None:
            body["instructions"] = instructions
        if settings.reasoning_effort:
            body["reasoning"] = {"effort": settings.reasoning_effort}
        return "/responses", from_responses, body
    body = {"model": settings.model, "messages": to_openai(payload["messages"]), "tools": payload["tools"], **(options or {})}
    if settings.reasoning_effort:
        # OpenRouter documents only the reasoning object; OpenAI and Azure use reasoning_effort on Chat Completions.
        if urlsplit(settings.base_url).hostname == "openrouter.ai":
            body["reasoning"] = {"effort": settings.reasoning_effort}
        else:
            body["reasoning_effort"] = settings.reasoning_effort
    return "/chat/completions", from_openai, body


def check_connection(settings: ModelSettings, timeout: float = 60.0) -> dict[str, Any]:
    """Send one short request with one function tool, in the format of agent runs, and report the answer or the error.

    It checks the endpoint, the key, the model or deployment name, the API, and function tools with the selected
    reasoning effort. Some models reject this combination. It uses a few tokens.
    """
    path, parse, body = request_for(settings, {"messages": [{"role": "user", "content": CHECK_PROMPT}], "tools": [CHECK_TOOL]})
    started = time.monotonic()
    try:
        parsed = _parse_limited(parse, _post(client_for(settings), settings, path, body, timeout))
    except APIStatusError as error:
        return {"ok": False, "message": f"HTTP {error.status_code}: {error.response.text[:2000]}"}
    except (APIConnectionError, ValueError) as error:
        return {"ok": False, "message": f"{type(error).__name__}: {error}"}
    message = parsed["message"]
    answer = message["content"] or ", ".join(f"Werkzeugaufruf {call['function']['name']}" for call in message.get("tool_calls", []))
    return {"ok": True, "message": answer[:200], "latency_ms": round((time.monotonic() - started) * 1000)}


def make_model_call(settings: ModelSettings):
    """Return a `model_call(plan, payload, timeout)` function for `drive()`."""
    client = client_for(settings)

    def model_call(plan: dict[str, Any], payload: dict[str, Any], timeout: float) -> dict[str, Any]:
        path, parse, body = request_for(settings, payload, plan.get("options"))
        deadline = time.monotonic() + timeout
        attempt = rate_limits = 0
        while True:
            attempt += 1
            remaining = deadline - time.monotonic()
            try:
                raw = _post(client, settings, path, body, max(1.0, min(ATTEMPT_TIMEOUT_SECONDS, remaining)))
                break
            except APIStatusError as error:
                code = error.status_code
                detail = error.response.text[:4096]
                wait = RETRY_DELAY_SECONDS
                if code == 429:
                    wait = max(_retry_after(error.response.headers), min(RATE_LIMIT_MAX_WAIT_SECONDS, RATE_LIMIT_STEP_SECONDS * rate_limits))
                    rate_limits += 1
                exhausted = attempt >= ATTEMPTS and code != 429
                if code not in RETRY_STATUS or exhausted or deadline - time.monotonic() <= wait:
                    raise RuntimeError(f"Model endpoint returned HTTP {code}: {detail}") from None
                time.sleep(wait)
                continue
            except APIConnectionError as error:
                # APITimeoutError is a subclass: a stalled attempt and a failed connection are both retried.
                if attempt >= ATTEMPTS or deadline - time.monotonic() <= RETRY_DELAY_SECONDS:
                    raise RuntimeError(f"Model endpoint did not answer: {error}") from None
            time.sleep(RETRY_DELAY_SECONDS)
        return _parse_limited(parse, raw)

    return model_call
