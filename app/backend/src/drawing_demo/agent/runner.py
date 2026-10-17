"""Run one bounded drawing2cad agent conversation for each web run (ADR 0016).

The agent uses only the drawing2cad MCP tools through `drive()`. The runner starts the MCP server as a
stdio subprocess, records progress from the trace, and afterwards reads the part state through the same session.
"""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
import json
import logging
from pathlib import Path
import sys
from typing import Any, Callable

import cascadio
from drawing2cad_mcp.local_model_client import Trace, drive
from drawing2cad_mcp.part_schema import part_validate
from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

from ..store import Store, now
from .mapping import part_view, phase_for, review_view
from .model import ModelSettings, make_model_call

log = logging.getLogger(__name__)

# Bounds for one run. The spike used 25 tool calls and about 6 minutes for a small part.
LIMITS = {"step_budget": 45, "max_turns": 60, "model_timeout_seconds": 300, "total_timeout_seconds": 2400,
          "call_timeout_seconds": 240, "max_tool_text_chars": 80000}
MAX_STEP_BYTES = 100 * 1024 * 1024

MCP_CONFIG = """[pdf]
allowed_roots = [{sources}]
output_root = {output}
timeout_seconds = 90

[server]
transport = "stdio"

[cad]
enabled = true
timeout_seconds = 90
memory_mb = 3072
concurrency = 1
allow_build_code = false
max_tool_calls = {budget}
"""


def part_state(result: dict[str, Any]) -> dict[str, Any] | None:
    """The part state of a serialized `part_read` result, or None for an error. Field names follow drive()."""
    if result.get("isError", result.get("is_error")):
        return None
    data = result.get("structuredContent", result.get("structured_content")) or {}
    return data.get("part") or None


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

    def __init__(self, store: Store, settings: ModelSettings | None, skill_path: Path):
        self.store = store
        self.settings = settings
        self.skill_path = skill_path
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="agent")

    @property
    def available(self) -> bool:
        return self.settings is not None and self.skill_path.is_file()

    def submit(self, run_id: str) -> None:
        self.executor.submit(self._execute, run_id)

    def _execute(self, run_id: str) -> None:
        try:
            asyncio.run(self._run(run_id))
        except Exception as error:  # The run record must show every failure; the thread must not die silently.
            log.exception("Agent run %s failed", run_id)
            self._fail(run_id, "AGENT_FAILED", f"{type(error).__name__}: {error}"[:2000],
                       "Lauf erneut starten. Bleibt der Fehler, die Server-Protokolle prüfen.")

    def _fail(self, run_id: str, code: str, message: str, recovery: str) -> None:
        self.store.update_run(run_id, phase="failed", job={"status": "failed", "finished_at": now()},
                              error={"code": code, "message": message, "field": None, "recovery": recovery})

    async def _run(self, run_id: str) -> None:
        assert self.settings is not None
        run = self.store.run(run_id)
        source = self.store.source(run["source_id"])
        pdf = self.store.source_pdf(source["source_id"])
        directory = self.store.run_dir(run_id)
        config = directory / "mcp.toml"
        config.write_text(MCP_CONFIG.format(sources=json.dumps(str(self.store.sources)), output=json.dumps(str(self.store.mcp)),
                                            budget=LIMITS["step_budget"]), encoding="utf-8")
        # The part run ID must start with this prefix; drive() rejects other IDs.
        prefix = "web-" + run_id.removeprefix("run_")
        plan = {"model": self.settings.model, "source_path": str(pdf), "run_prefix": prefix, **LIMITS}
        self.store.update_run(run_id, phase="analyzing", job={"status": "running", "started_at": now()})

        part_runs: list[str] = []

        def on_event(kind: str, data: dict[str, Any]) -> None:
            if kind == "tool-request":
                name = data.get("name")
                arguments = data.get("arguments") if isinstance(data.get("arguments"), dict) else {}
                if name == "part_create" and isinstance(arguments.get("run_id"), str):
                    part_runs.append(arguments["run_id"])
                current = self.store.run(run_id)
                self.store.update_run(run_id, phase=phase_for(name, current["phase"]),
                                      job={"progress": min(0.95, data.get("request_number", 0) / LIMITS["step_budget"])})

        trace = ProgressTrace(directory / "trace", on_event)
        server = StdioServerParameters(command=sys.executable, args=["-m", "drawing2cad_mcp", "--config", str(config)])
        with (directory / "mcp-stderr.log").open("w", encoding="utf-8") as errors:
            async with stdio_client(server, errlog=errors) as streams:
                async with ClientSession(*streams, read_timeout_seconds=LIMITS["call_timeout_seconds"]) as session:
                    await session.initialize()
                    catalog = (await session.list_tools()).model_dump(mode="json", by_alias=True)["tools"]
                    summary = await drive(session, catalog, plan, self.skill_path.read_text(encoding="utf-8"), trace,
                                          model_call=make_model_call(self.settings))
                    state = None
                    for part_run in reversed(part_runs):  # The last part run that exists holds the result.
                        result = await session.call_tool("part_read", {"run_id": part_run})
                        state = part_state(result.model_dump(mode="json", by_alias=True))
                        if state:
                            break
        (directory / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        self._collect(run_id, source, summary, state)

    def _collect(self, run_id: str, source: dict[str, Any], summary: dict[str, Any], state: dict[str, Any] | None) -> None:
        """Turn the MCP state into the run record: part, review, and STEP/GLB artifacts."""
        if state is None:
            error = summary.get("error") or {}
            if error:  # For example, the model endpoint rejected the request. Show its message, not a generic one.
                self._fail(run_id, "AGENT_FAILED", f"{error.get('type', 'Error')}: {error.get('message', '')}"[:4000],
                           "Modell-Endpunkt und DRAWING2CAD_AGENT_* prüfen, dann Lauf erneut starten.")
            else:
                self._fail(run_id, "AGENT_NO_PART", f"Der Agent hat kein Teil angelegt (Status: {summary.get('status')}).",
                           "Zeichnung prüfen und Lauf erneut starten.")
            return
        analysis = self.store.analysis(source["source_id"])
        sheet = tuple(analysis["drawing"]["sheet_size_mm"])
        release = state.get("release")
        build = state.get("build") or {}
        review_items = part_validate(state["description"]).get("review_items", [])
        review = review_view(state, review_items, sheet, released=bool(release))
        artifacts = []
        step = self._step_bytes(release["path"], release["sha256"]) if release else None
        diagnostic = False
        if step is None and build.get("status") == "pass" and build.get("candidate_path"):
            step = self._step_bytes(build["candidate_path"], build["candidate_sha256"])
            diagnostic = step is not None
        base = Path(source["filename"]).stem
        revision = state.get("revision", 1)
        if step is not None:
            suffix = "diagnose" if diagnostic else "freigegeben"
            artifacts.append(self.store.add_artifact(run_id, "step", "model/step", f"{base}-r{revision}-{suffix}.step", step,
                                                     source["sha256"], revision))
            try:
                glb = cascadio.load(step, tol_linear=0.05, tol_angular=0.3)
                artifacts.append(self.store.add_artifact(run_id, "model_preview", "model/gltf-binary", f"{base}-r{revision}.glb",
                                                         glb, source["sha256"], revision))
            except Exception:
                log.exception("GLB conversion failed for run %s", run_id)
        # A model without release is a finished run with release state "blocked"; only a run without model failed.
        error = None if step is not None else {
            "code": "AGENT_NO_MODEL", "field": None,
            "message": (summary.get("final_text") or "Der Agent hat kein gültiges Modell gebaut.")[:4000],
            "recovery": "Offene Prüfpunkte ansehen; Zeichnung klären und Lauf erneut starten."}
        self.store.update_run(run_id, phase="done" if step is not None else "failed", part=part_view(state), review=review,
                              artifacts=artifacts, error=error, agent_report=(summary.get("final_text") or "")[:8000],
                              job={"status": "succeeded" if step is not None else "failed", "progress": 1, "finished_at": now()})

    def _step_bytes(self, path: str, expected_sha256: str) -> bytes | None:
        """Read a STEP file of the MCP store, if it lies inside the store and still has its recorded hash."""
        file = Path(path)
        try:
            resolved = file.resolve(strict=True)
        except OSError:
            return None
        if not resolved.is_relative_to(self.store.mcp) or file.is_symlink() or resolved.stat().st_size > MAX_STEP_BYTES:
            return None
        data = resolved.read_bytes()
        return data if sha256(data).hexdigest() == expected_sha256 else None
