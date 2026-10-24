"""Condense the agent trace of a run into the steps of the run timeline (ADR 0038).

The trace of `drive()` holds one JSON file for each event, named `<sequence>-<kind>.json`. This module only presents
these events; it adds no CAD, drawing, or release rule. Model requests repeat the complete conversation with all
images, so the timeline never reads them.
"""

from __future__ import annotations

import json
from pathlib import Path
import re
from typing import Any

from .mapping import PHASE_BY_TOOL

EVENT_FILE = re.compile(r"(?P<sequence>\d{3,})-(?P<kind>[a-z-]+)\.json")
# Event kinds of the timeline. Model requests, the conversation, and the summary are not steps.
STEP_KINDS = {"skill-references", "model-response", "tool-request", "tool-response", "corrective-instruction", "continuation"}
# Bounds for the step list, which the UI polls during a run, and for the details of one step.
PREVIEW_CHARS = 280
DETAIL_CHARS = 20000
MAX_IMAGES = 4


def _short(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[:limit] + f"\n… ({len(text) - limit:,} more characters)"


def _json_text(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=1, default=str)


def _events(trace: Path, kinds: set[str]) -> list[dict[str, Any]]:
    """The trace events of the given kinds, in sequence order. A file that is still being written is skipped."""
    names = sorted((m for f in trace.glob("*.json") if (m := EVENT_FILE.fullmatch(f.name)) and m["kind"] in kinds),
                   key=lambda m: int(m["sequence"]))
    events = []
    for match in names:
        try:
            events.append(json.loads((trace / match.string).read_text(encoding="utf-8")))
        except (OSError, ValueError):
            continue
    return events


def _response_text(response: dict[str, Any]) -> str:
    return "\n".join(item.get("text", "") for item in response.get("content", []) if item.get("type") == "text")


def problem(response: dict[str, Any]) -> dict[str, Any] | None:
    """Code, target, and message of a failed tool response, else None.

    The most specific code wins: a service error, then a build error, then the first validation defect.
    """
    if not response.get("isError"):
        return None
    data = response.get("structuredContent") or {}
    if not isinstance(data, dict):
        data = {}
    if not data:
        try:
            parsed = json.loads(_response_text(response))
            data = parsed if isinstance(parsed, dict) else {}
        except ValueError:
            pass
    error = data.get("error") if isinstance(data.get("error"), dict) else {}
    build = data.get("build") if isinstance(data.get("build"), dict) else {}
    build_error = build.get("error") if isinstance(build.get("error"), dict) else {}
    defects = [d for d in data.get("defects") or [] if isinstance(d, dict)]
    failed_checks = [c for c in build.get("checks") or [] if isinstance(c, dict) and c.get("status") == "fail"]
    feature = data.get("feature_id") or build_error.get("feature_id")
    if response.get("client_rejected"):
        code, target, message = "CLIENT_REJECTED", None, _response_text(response)
    elif error or build_error:
        error = error or build_error
        code, target, message = error.get("code"), error.get("target") or error.get("field") or feature, error.get("message")
        if failed_checks:  # A generic build failure names its first failed check.
            first = failed_checks[0]
            target = target or first.get("feature_id")
            message = f"{message} First failed check: {json.dumps(first, ensure_ascii=False, default=str)}"
    elif defects:
        first = defects[0]
        code, target = first.get("code"), first.get("pointer") or first.get("id")
        message = "; ".join(str(d.get("message", "")) for d in defects[:3])
    elif failed_checks:
        first = failed_checks[0]
        code, target, message = f"CHECK_{str(first.get('check', 'failed')).upper()}", first.get("feature_id"), _json_text(first)
    else:
        code, target, message = "TOOL_ERROR", None, _response_text(response)
    return {"code": str(code or "TOOL_ERROR"), "target": target, "message": _short(str(message or ""), 600)}


def _model_step(event: dict[str, Any]) -> dict[str, Any]:
    response = event.get("response") or {}
    message = response.get("message") or {}
    return {"kind": "model", "turn": event.get("turn"), "seconds": event.get("duration_seconds"),
            "prompt_tokens": response.get("prompt_eval_count"), "output_tokens": response.get("eval_count"),
            "text": _short(message.get("content") or "", PREVIEW_CHARS),
            "tool_calls": [call.get("function", {}).get("name") for call in message.get("tool_calls") or []]}


def _tool_step(request: dict[str, Any], response: dict[str, Any] | None) -> dict[str, Any]:
    name = request.get("name")
    result = (response or {}).get("response") or {}
    failure = problem(result) if response else None
    return {"kind": "tool", "turn": request.get("turn"), "tool": name, "request_number": request.get("request_number"),
            "phase": PHASE_BY_TOOL.get(name or "", "setup"),
            "status": "no_response" if response is None else "failed" if failure else "ok",
            "seconds": (response or {}).get("duration_seconds"), "problem": failure,
            "arguments": _short(json.dumps(request.get("arguments"), ensure_ascii=False, default=str), PREVIEW_CHARS),
            "images": sum(1 for item in result.get("content", []) if item.get("type") == "image")}


def steps(trace: Path) -> list[dict[str, Any]]:
    """The timeline steps of a trace. A tool step joins a tool request with its response; it uses the request sequence."""
    result: list[dict[str, Any]] = []
    open_request: dict[str, Any] | None = None
    for event in _events(trace, STEP_KINDS):
        kind = event["kind"]
        base = {"sequence": event["sequence"], "at": event.get("at")}
        if kind == "tool-response" and open_request is not None:
            result.append({**base, **_tool_step(open_request, event), "sequence": open_request["sequence"]})
            open_request = None
            continue
        if open_request is not None:  # A request without a response (an interrupted run).
            result.append({"sequence": open_request["sequence"], "at": open_request.get("at"), **_tool_step(open_request, None)})
            open_request = None
        if kind == "tool-request":
            open_request = event
        elif kind == "model-response":
            result.append({**base, **_model_step(event)})
        elif kind == "corrective-instruction":
            failure = event.get("failure") or {}
            result.append({**base, "kind": "correction", "turn": event.get("turn"), "tool": event.get("name"),
                           "code": failure.get("code"), "text": _short(event.get("message", ""), PREVIEW_CHARS)})
        elif kind == "continuation":
            result.append({**base, "kind": "continuation", "turn": event.get("turn"), "count": event.get("count"),
                           "limit": event.get("limit"), "text": _short(event.get("message", ""), PREVIEW_CHARS)})
        elif kind == "skill-references":
            result.append({**base, "kind": "skill", "turn": event.get("turn"), "paths": event.get("paths") or [],
                           "text": event.get("reason") or ""})
    if open_request is not None:
        result.append({"sequence": open_request["sequence"], "at": open_request.get("at"), **_tool_step(open_request, None)})
    return result


def summary(trace: Path) -> dict[str, Any] | None:
    """The final summary of the agent loop without its long fields, or None while the run is active."""
    events = _events(trace, {"summary"})
    if not events:
        return None
    data = events[-1]
    return {key: data.get(key) for key in ("status", "released", "model_turns", "tool_requests", "mcp_calls",
                                           "blocked_requests", "continuations", "model_seconds", "mcp_seconds",
                                           "duration_seconds")}


def step_detail(trace: Path, sequence: int) -> dict[str, Any] | None:
    """Full details of one step: arguments, result text, problem, and up to four images as data URLs."""
    events = {e["sequence"]: e for e in _events(trace, STEP_KINDS)}
    event = events.get(sequence)
    if event is None:
        return None
    kind = event["kind"]
    if kind == "tool-request":
        response = next((e for s, e in sorted(events.items()) if s > sequence and e["kind"] == "tool-response"), None)
        result = (response or {}).get("response") or {}
        images = [f"data:{item.get('mimeType', 'image/png')};base64,{item['data']}"
                  for item in result.get("content", []) if item.get("type") == "image" and item.get("data")][:MAX_IMAGES]
        structured = result.get("structuredContent")
        text = _json_text(structured) if structured else _response_text(result)
        return {"sequence": sequence, "kind": "tool", "tool": event.get("name"),
                "arguments": _short(_json_text(event.get("arguments")), DETAIL_CHARS),
                "result": _short(text, DETAIL_CHARS) if response else None,
                "problem": problem(result) if response else None, "images": images}
    if kind == "model-response":
        message = (event.get("response") or {}).get("message") or {}
        calls = [{"tool": c.get("function", {}).get("name"), "arguments": c.get("function", {}).get("arguments")}
                 for c in message.get("tool_calls") or []]
        return {"sequence": sequence, "kind": "model", "text": _short(message.get("content") or "", DETAIL_CHARS),
                "arguments": _short(_json_text(calls), DETAIL_CHARS) if calls else None, "result": None,
                "problem": None, "images": []}
    if kind == "corrective-instruction":
        return {"sequence": sequence, "kind": "correction", "text": _short(event.get("message", ""), DETAIL_CHARS),
                "arguments": None, "result": None, "problem": event.get("failure"), "images": []}
    if kind == "continuation":
        return {"sequence": sequence, "kind": "continuation", "text": _short(event.get("message", ""), DETAIL_CHARS),
                "arguments": None, "result": None, "problem": None, "images": []}
    if kind == "skill-references":
        return {"sequence": sequence, "kind": "skill", "text": event.get("reason") or "",
                "arguments": _json_text(event.get("paths") or []), "result": None, "problem": None, "images": []}
    return None
