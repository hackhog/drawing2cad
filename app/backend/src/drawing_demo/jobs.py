"""Web-adapter records of agent runs (ADR 0018).

A record holds the job state, the agent trace, and the ID of the domain part run. It copies no domain data:
part state, artifacts, and the agent report stay in the domain service.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import threading
from typing import Any
from uuid import uuid4

from .service import checked_id, not_found


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def write_json(path: Path, data: Any) -> None:
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, path)


class JobStore:
    """Agent run records below one directory. Run IDs are generated and never select another path."""

    def __init__(self, root: Path):
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def add(self, source_id: str, agent: dict[str, str | None] | None = None) -> dict[str, Any]:
        """Create a queued run. `agent` records the model, its reasoning effort, and the skill and MCP versions that execute it."""
        run_id = "run_" + uuid4().hex
        directory = self.root / run_id
        (directory / "trace").mkdir(parents=True)
        record = {
            "run_id": run_id,
            "source_id": source_id,
            "agent": agent,
            # The agent must use this prefix for its part runs; drive() rejects other run IDs.
            "part_prefix": "web-" + run_id.removeprefix("run_"),
            "part_run_id": None,
            "phase": "queued",
            "failed_phase": None,
            "job": {"job_id": run_id, "status": "queued", "progress": 0, "started_at": now(), "finished_at": None},
            "error": None,
        }
        write_json(directory / "run.json", record)
        return record

    def get(self, run_id: str) -> dict[str, Any]:
        path = self.root / checked_id(run_id, "run") / "run.json"
        if not path.is_file():
            raise not_found(run_id)
        return json.loads(path.read_text(encoding="utf-8"))

    def directory(self, run_id: str) -> Path:
        self.get(run_id)
        return self.root / run_id

    def update(self, run_id: str, **changes: Any) -> dict[str, Any]:
        with self._lock:
            record = self.get(run_id)
            for key, value in changes.items():
                record[key] = {**record["job"], **value} if key == "job" else value
            write_json(self.root / run_id / "run.json", record)
            return record

    def list(self, source_id: str | None = None) -> list[dict[str, Any]]:
        records = [json.loads(p.read_text(encoding="utf-8")) for p in self.root.glob("run_*/run.json")]
        if source_id is not None:
            records = [r for r in records if r["source_id"] == source_id]
        return sorted(records, key=lambda r: r["job"]["started_at"])

    def remove(self, source_id: str) -> None:
        """Delete the records and traces of all runs of a source."""
        with self._lock:
            for run in self.list(source_id):
                shutil.rmtree(self.root / checked_id(run["run_id"], "run"))

    def files(self, run_id: str) -> dict[str, Path]:
        """The record and the agent trace of a run, by path relative to its directory."""
        directory = self.directory(run_id)
        return {file.relative_to(directory).as_posix(): file
                for file in sorted(directory.rglob("*")) if file.is_file() and not file.is_symlink() and file.suffix != ".tmp"}

    def fail_interrupted(self) -> None:
        """A restart ends unfinished background jobs; record that instead of a run that waits forever."""
        for run in self.list():
            if run["job"]["status"] in ("queued", "running"):
                self.update(run["run_id"], phase="failed", failed_phase=run["phase"],
                            job={"status": "failed", "finished_at": now()}, error={
                    "code": "RUN_INTERRUPTED", "message": "The server was restarted during the run.",
                    "field": None, "recovery": "Start the run again."})
