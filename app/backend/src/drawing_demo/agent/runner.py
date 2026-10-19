"""Run one bounded drawing2cad agent conversation for each web run (ADR 0018).

The agent uses only the tools of the backend's own `/mcp` endpoint through `drive()`, with the uploaded source ID
as its only input. The runner records progress from the trace and stores the final agent report as a run note.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
import json
import logging
from pathlib import Path
import re
from typing import Any, Callable

from drawing2cad_mcp.local_model_client import Trace, drive, skill_references, skill_text
import httpx2
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from ..jobs import JobStore, now
from ..service import DomainBackend, ServiceError
from .mapping import phase_for
from .model import ModelSettings, make_model_call
from .profiles import ProfileStore

log = logging.getLogger(__name__)
# The `metadata.version` field in the YAML front matter of SKILL.md.
SKILL_VERSION = re.compile(r'^---\n.*?^\s+version:\s*"?([^"\n]+?)"?\s*$.*?^---$', re.MULTILINE | re.DOTALL)

# Bounds for one run. The spike used 25 tool calls and about 6 minutes for a small part.
LIMITS = {"step_budget": 45, "max_turns": 60, "model_timeout_seconds": 300, "total_timeout_seconds": 2400,
          "call_timeout_seconds": 240, "max_tool_text_chars": 80000}
MAX_NOTE_CHARS = 65536


def iterations(turns: int, tool_requests: int, **counts: int) -> dict[str, int]:
    """Model turns and tool requests of the agent loop so far, with the tool request budget.

    The final summary adds the actual MCP calls and the requests that the loop blocked before execution.
    """
    return {"model_turns": turns, "tool_requests": tool_requests, "step_budget": LIMITS["step_budget"], **counts}


class ProgressTrace(Trace):
    """The trace of `drive()`, plus a callback for each tool request and response."""

    def __init__(self, output: Path, on_event: Callable[[str, dict[str, Any]], None]):
        super().__init__(output)
        self.on_event = on_event

    def write(self, kind, data):
        reference = super().write(kind, data)
        if kind in ("tool-request", "tool-response"):
            self.on_event(kind, data)
        return reference


class AgentRunner:
    """Execute runs one at a time in a background thread. Further runs wait as `queued`.

    A new run uses the active profile of the store; a later selection does not change queued or running runs.
    """

    def __init__(self, backend: DomainBackend, jobs: JobStore, profiles: ProfileStore, skill_path: Path,
                 mcp_url: str, token: str | None = None):
        self.backend = backend
        self.jobs = jobs
        self.profiles = profiles
        self.skill_path = skill_path
        self.mcp_url = mcp_url
        self.token = token
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="agent")

    @property
    def settings(self) -> ModelSettings | None:
        """The endpoint of the active profile, or None when no profile is active."""
        return self.profiles.get(self.profiles.active)

    @property
    def skill_version(self) -> str | None:
        """The version of the skill that new runs receive, or None when the skill has no version."""
        if not self.skill_path.is_file():
            return None
        match = SKILL_VERSION.match(self.skill_path.read_text(encoding="utf-8"))
        return match.group(1) if match else None

    @property
    def available(self) -> bool:
        return self.settings is not None and self.skill_path.is_file()

    def submit(self, run_id: str, settings: ModelSettings) -> None:
        self.executor.submit(self._execute, run_id, settings)

    def close(self) -> None:
        self.executor.shutdown(wait=False, cancel_futures=True)

    def _execute(self, run_id: str, settings: ModelSettings) -> None:
        try:
            asyncio.run(self._run(run_id, settings))
        except Exception as error:  # The run record must show every failure; the thread must not die silently.
            log.exception("Agent run %s failed", run_id)
            self._fail(run_id, "AGENT_FAILED", f"{type(error).__name__}: {error}"[:2000],
                       "Start the run again. If the error persists, check the server logs.")

    def _fail(self, run_id: str, code: str, message: str, recovery: str, field: str | None = None) -> None:
        # Keep the phase in which the run failed, so the UI does not show later phases as completed.
        self.jobs.update(run_id, phase="failed", failed_phase=self.jobs.get(run_id)["phase"],
                         job={"status": "failed", "finished_at": now()},
                         error={"code": code, "message": message, "field": field, "recovery": recovery})

    @asynccontextmanager
    async def session(self) -> AsyncIterator[ClientSession]:
        """An MCP session with the mounted endpoint of this backend."""
        headers = {"Authorization": f"Bearer {self.token}"} if self.token else {}
        async with httpx2.AsyncClient(headers=headers, timeout=LIMITS["call_timeout_seconds"], trust_env=False) as client:
            async with streamable_http_client(self.mcp_url, http_client=client) as streams:
                async with ClientSession(*streams, read_timeout_seconds=LIMITS["call_timeout_seconds"]) as session:
                    await session.initialize()
                    yield session

    async def _run(self, run_id: str, settings: ModelSettings) -> None:
        run = self.jobs.get(run_id)
        source = self.backend.call("source_get", source_id=run["source_id"])
        plan = {"model": settings.model, "source_id": source["source_id"], "source_sha256": source["sha256"],
                "run_prefix": run["part_prefix"], **LIMITS}
        self.jobs.update(run_id, phase="analyzing", job={"status": "running", "started_at": now()})
        requested: dict[str, Any] = {}

        def on_event(kind: str, data: dict[str, Any]) -> None:
            name = data.get("name")
            if kind == "tool-request":
                requested["arguments"] = data.get("arguments") if isinstance(data.get("arguments"), dict) else {}
                current = self.jobs.get(run_id)
                self.jobs.update(run_id, phase=phase_for(name, current["phase"]),
                                 iterations=iterations(data.get("turn", 0), data.get("request_number", 0)),
                                 job={"progress": min(0.95, data.get("request_number", 0) / LIMITS["step_budget"])})
            elif name == "part_create" and not data.get("response", {}).get("isError", True):
                # Only a part run that the service created holds a result.
                self.jobs.update(run_id, part_run_id=requested["arguments"].get("run_id"))

        directory = self.jobs.directory(run_id)
        trace = ProgressTrace(directory / "trace", on_event)
        async with self.session() as session:
            catalog = (await session.list_tools()).model_dump(mode="json", by_alias=True)["tools"]
            summary = await drive(session, catalog, plan, skill_text(self.skill_path, domain=True), trace,
                                  model_call=make_model_call(settings), references=skill_references(self.skill_path))
        (directory / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        self.finish(run_id, summary)

    def finish(self, run_id: str, summary: dict[str, Any]) -> None:
        """Store the agent report as a note of the part run and set the final job state from the domain part state."""
        # The last model turn answers without a tool request; only the summary counts it.
        part_run = self.jobs.update(run_id, iterations=iterations(
            summary.get("model_turns", 0), summary.get("tool_requests", 0), mcp_calls=summary.get("mcp_calls", 0),
            blocked_requests=summary.get("blocked_requests", 0)))["part_run_id"]
        report = summary.get("final_text") or ""
        if part_run is not None and report:
            self.store_report(part_run, report)
        error = summary.get("error") or {}
        if error:
            # The conversation did not end, for example after a rate limit. A part built before stays readable,
            # but the run is not a finished result. Show the actual message, not a generic one.
            self._fail(run_id, "AGENT_FAILED", f"{error.get('type', 'Error')}: {error.get('message', '')}"[:4000],
                       "Check the model endpoint and DRAWING2CAD_AGENT_*, then start the run again.")
            return
        stalled = summary.get("no_progress")
        if summary.get("status") == "no_progress" and stalled:
            # The loop stopped a repeated failed request. Report the tool, field, and count, also when no part exists.
            at = f" at {stalled['target']}" if stalled.get("target") else ""
            self._fail(run_id, "AGENT_NO_PROGRESS",
                       f"The agent sent the same failed {stalled['tool']} request {stalled['repeat_count']} times "
                       f"({stalled['code']}{at}): {stalled['message']}"[:4000],
                       "Look at the trace. Start the run again with a model that corrects tool arguments.",
                       field=stalled.get("target"))
            return
        out_of_time = summary.get("status") == "time_budget_reached"
        if part_run is None:
            if out_of_time:
                self._fail(run_id, "AGENT_TIME_BUDGET", self._time_budget_message(summary),
                           "Start the run again, or use a faster model endpoint.")
                return
            self._fail(run_id, "AGENT_NO_PART", f"The agent created no part (status: {summary.get('status')}).",
                       "Check the drawing and start the run again.")
            return
        part = self.backend.call("part_read", run_id=part_run)["part"]
        built = (part.get("build") or {}).get("status") == "pass"
        if part.get("release") or (built and not out_of_time):
            # A built model without release is a finished run; its review shows why the release is blocked.
            self.jobs.update(run_id, phase="done", error=None, job={"status": "succeeded", "progress": 1, "finished_at": now()})
        elif out_of_time:
            # The time ended before a release. A model built before stays readable, but the run is not a finished result.
            self._fail(run_id, "AGENT_TIME_BUDGET", self._time_budget_message(summary, built),
                       "Start the run again, or use a faster model endpoint.")
        else:
            # The complete report is the run note; the error names only the result.
            self._fail(run_id, "AGENT_NO_MODEL", f"The agent built no valid model (status: {summary.get('status')}).",
                       "Look at the report and open review items in the Review tab; clarify the drawing and start the run again.")

    @staticmethod
    def _time_budget_message(summary: dict[str, Any], built: bool = False) -> str:
        detail = summary.get("time_budget") or {}
        phase = {"model_inference": " during model inference", "tool_call": " during a tool call"}.get(detail.get("phase"), "")
        limit = LIMITS["total_timeout_seconds"]
        result = "released the STEP model; the built model stays readable" if built else "built a valid model"
        text = f"The run used its time budget of {limit} seconds{phase} before the agent {result}."
        return f"{text} Last error: {detail['message']}"[:4000] if detail.get("message") else text

    def store_report(self, part_run: str, report: str) -> None:
        """Replace the run note with the report. The note has its own revision; the first note uses revision zero."""
        try:
            revision = self.backend.call("notes_read", run_id=part_run)["revision"]
        except ServiceError as error:
            if error.detail["code"] != "NOT_FOUND":
                raise
            revision = 0
        self.backend.call("notes_update", run_id=part_run, expected_revision=revision, text=report[:MAX_NOTE_CHARS])
