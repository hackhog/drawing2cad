"""Model call for OpenAI-compatible Chat Completions endpoints (ADR 0018).

`drawing2cad_mcp.local_model_client.drive` exchanges messages in the Ollama chat format.
This module translates them to Chat Completions and back, so that Azure AI Foundry, OpenRouter,
OpenAI, or the OpenAI endpoint of Ollama can supply the model. It reads no files and runs no tools.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

MAX_RESPONSE_BYTES = 8 * 1024 * 1024
# A hosted endpoint can fail transiently (spike: one Azure server error; web run: one request without answer).
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


@dataclass(frozen=True)
class ModelSettings:
    base_url: str
    model: str
    api_key: str
    # Azure AI Foundry accepts "api-key"; most other providers use "Authorization: Bearer".
    api_key_header: str = "Authorization"
    # Some models reject function tools with reasoning on Chat Completions (for example, gpt-6.1-sol needs "none").
    reasoning_effort: str | None = None

    @classmethod
    def from_env(cls) -> "ModelSettings | None":
        """Return the configured endpoint, or None if the agent is not configured."""
        base_url = os.environ.get("DRAWING2CAD_AGENT_BASE_URL", "").strip()
        model = os.environ.get("DRAWING2CAD_AGENT_MODEL", "").strip()
        api_key = os.environ.get("DRAWING2CAD_AGENT_API_KEY", "").strip()
        if not (base_url and model and api_key):
            return None
        header = os.environ.get("DRAWING2CAD_AGENT_API_KEY_HEADER", "Authorization").strip() or "Authorization"
        effort = os.environ.get("DRAWING2CAD_AGENT_REASONING_EFFORT", "").strip() or None
        return cls(base_url.rstrip("/"), model, api_key, header, effort)

    def headers(self) -> dict[str, str]:
        value = f"Bearer {self.api_key}" if self.api_key_header.lower() == "authorization" else self.api_key
        return {"Content-Type": "application/json", self.api_key_header: value}


def to_openai(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Translate Ollama-style messages to Chat Completions messages.

    A tool result in the Ollama format has no call ID. `drive` appends results in request order,
    so each result takes the next open ID of the preceding assistant message.
    """
    result: list[dict[str, Any]] = []
    open_ids: list[str] = []
    image_positions = [i for i, m in enumerate(messages) if m.get("images")]
    kept = set(image_positions[-KEPT_IMAGE_MESSAGES:])
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
            result.append({"role": "tool", "tool_call_id": open_ids.pop(0), "content": message.get("content", "")})
        elif message.get("images") and position not in kept:
            result.append({"role": role, "content": f"{message.get('content', '')} {OMITTED_IMAGE_NOTE}"})
        elif message.get("images"):
            parts: list[dict[str, Any]] = [{"type": "text", "text": message.get("content", "")}]
            parts += [{"type": "image_url", "image_url": {"url": "data:image/png;base64," + image}} for image in message["images"]]
            result.append({"role": role, "content": parts})
        else:
            result.append({"role": role, "content": message.get("content", "")})
    return result


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
        text = call.get("function", {}).get("arguments", "{}")
        try:
            arguments: Any = json.loads(text) if text else {}
        except ValueError:
            # Keep invalid JSON visible; drive() rejects non-object arguments with a tool error.
            arguments = text
        calls.append({"id": call["id"], "function": {"name": call["function"]["name"], "arguments": arguments}})
    usage = body.get("usage") or {}
    response: dict[str, Any] = {
        "message": {"role": "assistant", "content": message.get("content") or "", **({"tool_calls": calls} if calls else {})},
        "done_reason": choices[0].get("finish_reason"),
        "prompt_eval_count": usage.get("prompt_tokens"),
        "eval_count": usage.get("completion_tokens"),
    }
    return response


def _retry_after(error: HTTPError) -> float:
    """Seconds to wait after a rate-limit answer: the Retry-After header, else a fixed delay."""
    try:
        return max(RETRY_DELAY_SECONDS, float(error.headers.get("Retry-After", "")))
    except (TypeError, ValueError):
        return 10.0


def make_model_call(settings: ModelSettings):
    """Return a `model_call(plan, payload, timeout)` function for `drive()`."""

    def model_call(plan: dict[str, Any], payload: dict[str, Any], timeout: float) -> dict[str, Any]:
        body = {"model": settings.model, "messages": to_openai(payload["messages"]), "tools": payload["tools"],
                **plan.get("options", {})}
        if settings.reasoning_effort:
            body["reasoning_effort"] = settings.reasoning_effort
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        deadline = time.monotonic() + timeout
        attempt = rate_limits = 0
        while True:
            attempt += 1
            remaining = deadline - time.monotonic()
            try:
                with urlopen(Request(settings.base_url + "/chat/completions", data, settings.headers()),
                             timeout=max(1.0, min(ATTEMPT_TIMEOUT_SECONDS, remaining))) as response:
                    raw = response.read(MAX_RESPONSE_BYTES + 1)
                break
            except HTTPError as error:
                detail = error.read(4096).decode("utf-8", errors="replace")
                wait = RETRY_DELAY_SECONDS
                if error.code == 429:
                    wait = max(_retry_after(error), min(RATE_LIMIT_MAX_WAIT_SECONDS, RATE_LIMIT_STEP_SECONDS * rate_limits))
                    rate_limits += 1
                exhausted = attempt >= ATTEMPTS and error.code != 429
                if error.code not in RETRY_STATUS or exhausted or deadline - time.monotonic() <= wait:
                    raise RuntimeError(f"Model endpoint returned HTTP {error.code}: {detail}") from None
                time.sleep(wait)
                continue
            except (TimeoutError, URLError) as error:
                if attempt >= ATTEMPTS or deadline - time.monotonic() <= RETRY_DELAY_SECONDS:
                    raise RuntimeError(f"Model endpoint did not answer: {error}") from None
            time.sleep(RETRY_DELAY_SECONDS)
        if len(raw) > MAX_RESPONSE_BYTES:
            raise ValueError("The model response exceeds 8 MiB.")
        return from_openai(json.loads(raw))

    return model_call
