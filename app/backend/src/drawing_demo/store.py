"""Interim file store for sources and run records (ADR 0016).

The shared services of #24 replace this store. Part revisions, builds, and releases stay in the MCP store.
Records use the provisional contract fields of app/frontend/src/lib/contract.ts. IDs are opaque and never paths.
"""

from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import threading
from typing import Any

ID_PATTERN = re.compile(r"^(src|run|art)_[a-f0-9]{16}$")


class NotFound(LookupError):
    """An ID is unknown or malformed. The API maps it to 404."""


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_id(prefix: str) -> str:
    return f"{prefix}_{secrets.token_hex(8)}"


def _write_json(path: Path, data: Any) -> None:
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, path)


def _checked(identifier: str, prefix: str) -> str:
    # Reject anything that is not a generated ID, so that an ID can never select another path.
    if not ID_PATTERN.match(identifier) or not identifier.startswith(prefix + "_"):
        raise NotFound(identifier)
    return identifier


class Store:
    """Sources, analyses, and run records below one data directory."""

    def __init__(self, root: Path):
        self.root = root.resolve()
        self.sources = self.root / "sources"
        self.runs = self.root / "runs"
        self.mcp = self.root / "mcp"
        for directory in (self.sources, self.runs, self.mcp):
            directory.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    # Sources -----------------------------------------------------------------

    def add_source(self, filename: str, pdf: bytes, analysis: dict[str, Any]) -> dict[str, Any]:
        source_id = new_id("src")
        directory = self.sources / source_id
        directory.mkdir()
        (directory / "source.pdf").write_bytes(pdf)
        record = {
            "source_id": source_id,
            "filename": Path(filename or "upload.pdf").name,
            "media_type": "application/pdf",
            "byte_count": len(pdf),
            "sha256": sha256(pdf).hexdigest(),
            "upload_state": "complete",
            "created_at": now(),
        }
        _write_json(directory / "analysis.json", analysis)
        _write_json(directory / "source.json", record)
        return record

    def list_sources(self) -> list[dict[str, Any]]:
        records = [json.loads(p.read_text(encoding="utf-8")) for p in self.sources.glob("src_*/source.json")]
        return sorted(records, key=lambda r: r["created_at"])

    def source(self, source_id: str) -> dict[str, Any]:
        path = self.sources / _checked(source_id, "src") / "source.json"
        if not path.is_file():
            raise NotFound(source_id)
        return json.loads(path.read_text(encoding="utf-8"))

    def source_pdf(self, source_id: str) -> Path:
        self.source(source_id)
        return self.sources / source_id / "source.pdf"

    def analysis(self, source_id: str) -> dict[str, Any]:
        self.source(source_id)
        return json.loads((self.sources / source_id / "analysis.json").read_text(encoding="utf-8"))

    def delete_source(self, source_id: str) -> None:
        self.source(source_id)
        if any(r["source_id"] == source_id and r["job"]["status"] in ("queued", "running") for r in self.list_runs()):
            raise ValueError("A run of this source is still active.")
        for run in self.list_runs(source_id):
            shutil.rmtree(self.runs / run["run_id"], ignore_errors=True)
        shutil.rmtree(self.sources / source_id)

    # Runs --------------------------------------------------------------------

    def add_run(self, source_id: str) -> dict[str, Any]:
        self.source(source_id)
        run_id = new_id("run")
        directory = self.runs / run_id
        directory.mkdir()
        (directory / "trace").mkdir()
        record = {
            "run_id": run_id,
            "source_id": source_id,
            "phase": "queued",
            "job": {"job_id": run_id + "-job", "status": "queued", "progress": 0, "started_at": now(), "finished_at": None},
            "part": None,
            "artifacts": [],
            "review": None,
            "error": None,
            "simulated": False,
        }
        _write_json(directory / "run.json", record)
        return record

    def run(self, run_id: str) -> dict[str, Any]:
        path = self.runs / _checked(run_id, "run") / "run.json"
        if not path.is_file():
            raise NotFound(run_id)
        return json.loads(path.read_text(encoding="utf-8"))

    def run_dir(self, run_id: str) -> Path:
        self.run(run_id)
        return self.runs / run_id

    def update_run(self, run_id: str, **changes: Any) -> dict[str, Any]:
        with self._lock:
            record = self.run(run_id)
            for key, value in changes.items():
                if key == "job":
                    record["job"] = {**record["job"], **value}
                else:
                    record[key] = value
            _write_json(self.runs / run_id / "run.json", record)
            return record

    def list_runs(self, source_id: str | None = None) -> list[dict[str, Any]]:
        records = [json.loads(p.read_text(encoding="utf-8")) for p in self.runs.glob("run_*/run.json")]
        if source_id is not None:
            records = [r for r in records if r["source_id"] == source_id]
        return sorted(records, key=lambda r: r["job"]["started_at"])

    def run_files(self, run_id: str) -> dict[str, Path]:
        """All files of a run by display path: the run record and trace (`lauf/`), and the MCP part runs (`cad/`)."""
        roots = [("lauf", self.run_dir(run_id))]
        part_runs = self.mcp / "cad" / "runs"
        roots += [(f"cad/{d.name}", d) for d in sorted(part_runs.glob("web-" + run_id.removeprefix("run_") + "-*")) if d.is_dir()]
        return {f"{label}/{file.relative_to(root).as_posix()}": file
                for label, root in roots for file in sorted(root.rglob("*")) if file.is_file() and not file.is_symlink()}

    def add_artifact(self, run_id: str, role: str, media_type: str, filename: str, data: bytes,
                     source_sha256: str, model_revision: int) -> dict[str, Any]:
        artifact_id = new_id("art")
        (self.run_dir(run_id) / "artifacts").mkdir(exist_ok=True)
        (self.runs / run_id / "artifacts" / artifact_id).write_bytes(data)
        return {
            "artifact_id": artifact_id, "role": role, "media_type": media_type, "filename": filename,
            "sha256": sha256(data).hexdigest(), "byte_count": len(data),
            "source_sha256": source_sha256, "model_revision": model_revision,
        }

    def artifact(self, artifact_id: str) -> tuple[dict[str, Any], Path]:
        _checked(artifact_id, "art")
        for run in self.list_runs():
            for artifact in run["artifacts"]:
                if artifact["artifact_id"] == artifact_id:
                    return artifact, self.runs / run["run_id"] / "artifacts" / artifact_id
        raise NotFound(artifact_id)

    def fail_interrupted_runs(self) -> None:
        """A restart ends unfinished background jobs; record that instead of a run that waits forever."""
        for run in self.list_runs():
            if run["job"]["status"] in ("queued", "running"):
                self.update_run(run["run_id"], phase="failed", job={"status": "failed", "finished_at": now()}, error={
                    "code": "RUN_INTERRUPTED", "message": "Der Server wurde während des Laufs neu gestartet.",
                    "field": None, "recovery": "Lauf erneut starten."})
