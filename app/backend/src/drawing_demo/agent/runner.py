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
from typing import Any, Callable

from drawing2cad_mcp.local_model_client import Trace, drive
import httpx2
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from ..jobs import JobStore, now
from ..service import DomainBackend, ServiceError
from .mapping import phase_for
from .model import ModelSettings, make_model_call

log = logging.getLogger(__name__)

# Bounds for one run. The spike used 25 tool calls and about 6 minutes for a small part.
LIMITS = {"step_budget": 45, "max_turns": 60, "model_timeout_seconds": 300, "total_timeout_seconds": 2400,
          "call_timeout_seconds": 240, "max_tool_text_chars": 80000}
MAX_NOTE_CHARS = 65536


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
    """Execute runs one at a time in a background thread. Further runs wait as `queued`."""

    def __init__(self, backend: DomainBackend, jobs: JobStore, settings: ModelSettings | None, skill_path: Path,
                 mcp_url: str, token: str | None = None):
        self.backend = backend
        self.jobs = jobs
        self.settings = settings
        self.skill_path = skill_path
        self.mcp_url = mcp_url
        self.token = token
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="agent")

    @property
    def available(self) -> bool:
        return self.settings is not None and self.skill_path.is_file()

    def submit(self, run_id: str) -> None:
        self.executor.submit(self._execute, run_id)

    def close(self) -> None:
        self.executor.shutdown(wait=False, cancel_futures=True)

    def _execute(self, run_id: str) -> None:
        try:
            asyncio.run(self._run(run_id))
        except Exception as error:  # The run record must show every failure; the thread must not die silently.
            log.exception("Agent run %s failed", run_id)
            self._fail(run_id, "AGENT_FAILED", f"{type(error).__name__}: {error}"[:2000],
                       "Lauf erneut starten. Bleibt der Fehler, die Server-Protokolle prüfen.")

    def _fail(self, run_id: str, code: str, message: str, recovery: str) -> None:
        # Keep the phase in which the run failed, so the UI does not show later phases as completed.
        self.jobs.update(run_id, phase="failed", failed_phase=self.jobs.get(run_id)["phase"],
                         job={"status": "failed", "finished_at": now()},
                         error={"code": code, "message": message, "field": None, "recovery": recovery})

    @asynccontextmanager
    async def session(self) -> AsyncIterator[ClientSession]:
        """An MCP session with the mounted endpoint of this backend."""
        headers = {"Authorization": f"Bearer {self.token}"} if self.token else {}
        async with httpx2.AsyncClient(headers=headers, timeout=LIMITS["call_timeout_seconds"], trust_env=False) as client:
            async with streamable_http_client(self.mcp_url, http_client=client) as streams:
                async with ClientSession(*streams, read_timeout_seconds=LIMITS["call_timeout_seconds"]) as session:
                    await session.initialize()
                    yield session

    async def _run(self, run_id: str) -> None:
        assert self.settings is not None
        run = self.jobs.get(run_id)
        source = self.backend.call("source_get", source_id=run["source_id"])
        plan = {"model": self.settings.model, "source_id": source["source_id"], "source_sha256": source["sha256"],
                "run_prefix": run["part_prefix"], **LIMITS}
        self.jobs.update(run_id, phase="analyzing", job={"status": "running", "started_at": now()})
        requested: dict[str, Any] = {}

        def on_event(kind: str, data: dict[str, Any]) -> None:
            name = data.get("name")
            if kind == "tool-request":
                requested["arguments"] = data.get("arguments") if isinstance(data.get("arguments"), dict) else {}
                current = self.jobs.get(run_id)
                self.jobs.update(run_id, phase=phase_for(name, current["phase"]),
                                 job={"progress": min(0.95, data.get("request_number", 0) / LIMITS["step_budget"])})
            elif name == "part_create" and not data.get("response", {}).get("isError", True):
                # Only a part run that the service created holds a result.
                self.jobs.update(run_id, part_run_id=requested["arguments"].get("run_id"))

        directory = self.jobs.directory(run_id)
        trace = ProgressTrace(directory / "trace", on_event)
        async with self.session() as session:
            catalog = (await session.list_tools()).model_dump(mode="json", by_alias=True)["tools"]
            summary = await drive(session, catalog, plan, self.skill_path.read_text(encoding="utf-8"), trace,
                                  model_call=make_model_call(self.settings))
        (directory / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        self.finish(run_id, summary)

    def finish(self, run_id: str, summary: dict[str, Any]) -> None:
        """Store the agent report as a note of the part run and set the final job state from the domain part state."""
        part_run = self.jobs.get(run_id)["part_run_id"]
        if part_run is None:
            error = summary.get("error") or {}
            if error:  # For example, the model endpoint rejected the request. Show its message, not a generic one.
                self._fail(run_id, "AGENT_FAILED", f"{error.get('type', 'Error')}: {error.get('message', '')}"[:4000],
                           "Modell-Endpunkt und DRAWING2CAD_AGENT_* prüfen, dann Lauf erneut starten.")
            else:
                self._fail(run_id, "AGENT_NO_PART", f"Der Agent hat kein Teil angelegt (Status: {summary.get('status')}).",
                           "Zeichnung prüfen und Lauf erneut starten.")
            return
        report = summary.get("final_text") or ""
        if report:
            self.store_report(part_run, report)
        part = self.backend.call("part_read", run_id=part_run)["part"]
        if part.get("release") or (part.get("build") or {}).get("status") == "pass":
            # A built model without release is a finished run; its review shows why the release is blocked.
            self.jobs.update(run_id, phase="done", error=None, job={"status": "succeeded", "progress": 1, "finished_at": now()})
        else:
            # The complete report is the run note; the error names only the result.
            self._fail(run_id, "AGENT_NO_MODEL", f"Der Agent hat kein gültiges Modell gebaut (Status: {summary.get('status')}).",
                       "Bericht und offene Prüfpunkte im Reiter Prüfung ansehen; Zeichnung klären und Lauf erneut starten.")

    def store_report(self, part_run: str, report: str) -> None:
        """Replace the run note with the report. The note has its own revision; the first note uses revision zero."""
        try:
            revision = self.backend.call("notes_read", run_id=part_run)["revision"]
        except ServiceError as error:
            if error.detail["code"] != "NOT_FOUND":
                raise
            revision = 0
        self.backend.call("notes_update", run_id=part_run, expected_revision=revision, text=report[:MAX_NOTE_CHARS])
