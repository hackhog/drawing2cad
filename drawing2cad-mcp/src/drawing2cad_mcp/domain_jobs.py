"""Persistent jobs for the MCP and web adapters.

One service holds an operating-system lock while it dispatches jobs. The lock
ends when the process exits. A new service marks unfinished active jobs as
interrupted. It resumes queued jobs only; it never repeats uncertain effects.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import logging
import os
from pathlib import Path
import sqlite3
import stat
import threading
from typing import Any, Callable, Iterator
import uuid

from .domain_store import AccessContext, DomainError, DomainStore


TERMINAL_STATES = frozenset({"succeeded", "failed", "cancelled", "interrupted"})
DEFAULT_OPERATIONS = ("build_from_description", "build_code", "drawing_render", "export_step")
MAX_ARGUMENT_BYTES = 262_144
MAX_RESULT_BYTES = 1_048_576


LOG = logging.getLogger(__name__)


class JobCancelled(Exception):
    """The dispatcher confirms that it stopped without unreported effects."""


class JobFailed(DomainError):
    """The operation ran and failed its checks. Its public report stays in the job result."""

    def __init__(self, code: str, message: str, result: dict[str, Any]):
        super().__init__(code, message)
        self.result = result


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _encode(value: Any, limit: int, code: str) -> str:
    try:
        text = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
        size = len(text.encode("utf-8"))
    except (TypeError, ValueError, RecursionError, UnicodeError):
        raise DomainError(code, "The value must contain finite JSON data.") from None
    if size > limit:
        raise DomainError(code, "The JSON data exceed the size limit.")
    return text


class JobService:
    """Run bounded synchronous dispatchers outside the transport event loop.

    The caller must supply an authenticated context. The dispatcher must verify
    ownership and the expected revision before it starts an operation. Results
    must contain public identifiers, not host paths. Start and close this service
    in the server lifespan. Close waits for active dispatchers to return.
    """

    def __init__(
        self,
        root: Path | str,
        dispatcher: Callable[[AccessContext, str, dict[str, Any], threading.Event], dict[str, Any]],
        concurrency: int = 1,
        operations: tuple[str, ...] = DEFAULT_OPERATIONS,
        max_pending: int = 128,
    ) -> None:
        if type(concurrency) is not int or not 1 <= concurrency <= 16:
            raise ValueError("Job concurrency must be an integer from 1 to 16.")
        if not operations or any(not isinstance(item, str) or not item for item in operations):
            raise ValueError("At least one operation is required.")
        if type(max_pending) is not int or not 1 <= max_pending <= 4096:
            raise ValueError("The pending job limit must be an integer from 1 to 4096.")
        self.root = Path(os.path.abspath(root))
        DomainStore._check_path(self.root)
        self.root.mkdir(parents=True, exist_ok=True)
        self._database = self.root / "jobs.sqlite3"
        self._dispatcher = dispatcher
        self._concurrency = concurrency
        self._operations = frozenset(operations)
        self._max_pending = max_pending
        self._lifecycle = threading.RLock()
        self._active_lock = threading.Lock()
        self._active: dict[str, threading.Event] = {}
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._workers: list[threading.Thread] = []
        self._monitor: threading.Thread | None = None
        self._lock_file: Any = None
        with self._connection() as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.executescript("""
                CREATE TABLE IF NOT EXISTS jobs (
                    job_id TEXT PRIMARY KEY,
                    owner TEXT NOT NULL,
                    operation TEXT NOT NULL,
                    arguments TEXT NOT NULL,
                    request_hash TEXT NOT NULL,
                    idempotency_key TEXT NOT NULL,
                    run_id TEXT NOT NULL,
                    expected_revision INTEGER NOT NULL,
                    state TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    started_at TEXT,
                    finished_at TEXT,
                    cancellation_requested_at TEXT,
                    result TEXT,
                    error TEXT,
                    UNIQUE(owner, idempotency_key)
                );
                CREATE INDEX IF NOT EXISTS jobs_queue ON jobs(state, created_at, job_id);
                CREATE INDEX IF NOT EXISTS jobs_owner ON jobs(owner, created_at, job_id);
            """)

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        self._check_storage_files()
        connection = sqlite3.connect(self._database, timeout=10, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout=10000")
        try:
            yield connection
        finally:
            connection.close()

    def _check_storage_files(self) -> None:
        for name in ("jobs.lock", "jobs.sqlite3", "jobs.sqlite3-wal", "jobs.sqlite3-shm", "jobs.sqlite3-journal"):
            path = self.root / name
            DomainStore._check_path(path)
            try:
                metadata = path.stat()
            except FileNotFoundError:
                continue
            if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
                raise DomainError("UNSAFE_PATH", "Job storage must use regular files without extra links.")

    @staticmethod
    def _subject(context: AccessContext) -> str:
        subject = context.subject
        if not isinstance(subject, str) or not subject or len(subject) > 512:
            raise DomainError("INVALID_CONTEXT", "A valid subject is required.")
        return subject

    @staticmethod
    def _public(row: sqlite3.Row) -> dict[str, Any]:
        value = {key: row[key] for key in (
            "job_id", "operation", "run_id", "expected_revision", "state",
            "created_at", "updated_at", "started_at", "finished_at", "cancellation_requested_at",
        )}
        value["arguments"] = json.loads(row["arguments"])
        value["result"] = json.loads(row["result"]) if row["result"] else None
        value["error"] = json.loads(row["error"]) if row["error"] else None
        return value

    def submit(
        self,
        context: AccessContext,
        operation: str,
        arguments: dict[str, Any],
        idempotency_key: str,
    ) -> dict[str, Any]:
        owner = self._subject(context)
        if not isinstance(operation, str) or operation not in self._operations:
            raise DomainError("JOB_OPERATION_UNSUPPORTED", "The job operation is not supported.")
        if not isinstance(arguments, dict):
            raise DomainError("JOB_ARGUMENTS_INVALID", "Job arguments must be a JSON object.")
        run_id = arguments.get("run_id")
        revision = arguments.get("expected_revision")
        if not isinstance(run_id, str) or not run_id or len(run_id) > 128:
            raise DomainError("JOB_ARGUMENTS_INVALID", "A run identifier is required.")
        if type(revision) is not int or not 1 <= revision <= 2**63 - 1:
            raise DomainError("JOB_ARGUMENTS_INVALID", "A positive expected revision is required.")
        if not isinstance(idempotency_key, str) or not 1 <= len(idempotency_key) <= 128:
            raise DomainError("JOB_IDEMPOTENCY_INVALID", "An idempotency key of 1 to 128 characters is required.")
        encoded = _encode(arguments, MAX_ARGUMENT_BYTES, "JOB_ARGUMENTS_INVALID")
        digest = hashlib.sha256((operation + "\n" + encoded).encode("utf-8")).hexdigest()
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("SELECT * FROM jobs WHERE owner=? AND idempotency_key=?", (owner, idempotency_key)).fetchone()
            if row:
                if row["request_hash"] != digest:
                    raise DomainError("JOB_IDEMPOTENCY_CONFLICT", "This key is assigned to a different job request.")
                connection.commit()
                return self._public(row)
            pending = connection.execute(
                "SELECT count(*) FROM jobs WHERE state IN ('queued','running','cancel_requested')"
            ).fetchone()[0]
            if pending >= self._max_pending:
                raise DomainError("JOB_QUEUE_FULL", "The job queue is full. Wait for a job to finish before you submit another request.")
            identifier, timestamp = "job_" + uuid.uuid4().hex, _now()
            connection.execute(
                "INSERT INTO jobs (job_id,owner,operation,arguments,request_hash,idempotency_key,run_id,expected_revision,state,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (identifier, owner, operation, encoded, digest, idempotency_key, run_id, revision, "queued", timestamp, timestamp),
            )
            row = connection.execute("SELECT * FROM jobs WHERE job_id=?", (identifier,)).fetchone()
            connection.commit()
        self._wake.set()
        return self._public(row)

    def get(self, context: AccessContext, job_id: str) -> dict[str, Any]:
        with self._connection() as connection:
            row = connection.execute("SELECT * FROM jobs WHERE job_id=? AND owner=?", (job_id, self._subject(context))).fetchone()
        if row is None:
            raise DomainError("JOB_NOT_FOUND", "The job does not exist or is not accessible.")
        return self._public(row)

    def list(self, context: AccessContext, *, limit: int = 50, run_id: str | None = None) -> list[dict[str, Any]]:
        if type(limit) is not int or not 1 <= limit <= 100:
            raise DomainError("JOB_LIST_LIMIT_INVALID", "The list limit must be an integer from 1 to 100.")
        with self._connection() as connection:
            if run_id is None:
                rows = connection.execute("SELECT * FROM jobs WHERE owner=? ORDER BY created_at DESC,job_id DESC LIMIT ?", (self._subject(context), limit)).fetchall()
            else:
                rows = connection.execute("SELECT * FROM jobs WHERE owner=? AND run_id=? ORDER BY created_at DESC,job_id DESC LIMIT ?", (self._subject(context), run_id, limit)).fetchall()
        return [self._public(row) for row in rows]

    def cancel(self, context: AccessContext, job_id: str) -> dict[str, Any]:
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("SELECT * FROM jobs WHERE job_id=? AND owner=?", (job_id, self._subject(context))).fetchone()
            if row is None:
                raise DomainError("JOB_NOT_FOUND", "The job does not exist or is not accessible.")
            timestamp = _now()
            if row["state"] == "queued":
                connection.execute("UPDATE jobs SET state='cancelled',updated_at=?,finished_at=?,cancellation_requested_at=? WHERE job_id=?", (timestamp, timestamp, timestamp, job_id))
            elif row["state"] == "running":
                connection.execute("UPDATE jobs SET state='cancel_requested',updated_at=?,cancellation_requested_at=? WHERE job_id=?", (timestamp, timestamp, job_id))
            row = connection.execute("SELECT * FROM jobs WHERE job_id=?", (job_id,)).fetchone()
            connection.commit()
        if row["state"] == "cancel_requested":
            with self._active_lock:
                if job_id in self._active:
                    self._active[job_id].set()
        self._wake.set()
        return self._public(row)

    def _acquire_process_lock(self) -> None:
        self._check_storage_files()
        lock_file = (self.root / "jobs.lock").open("a+b")
        try:
            if os.name == "nt":
                import msvcrt

                lock_file.seek(0, 2)
                if lock_file.tell() == 0:
                    lock_file.write(b"\0")
                    lock_file.flush()
                lock_file.seek(0)
                msvcrt.locking(lock_file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            lock_file.close()
            raise DomainError("JOB_SERVICE_BUSY", "Another job service is active for this store.") from None
        self._lock_file = lock_file

    def _release_process_lock(self) -> None:
        if self._lock_file is not None:
            if os.name == "nt":
                import msvcrt

                self._lock_file.seek(0)
                msvcrt.locking(self._lock_file.fileno(), msvcrt.LK_UNLCK, 1)
            self._lock_file.close()
            self._lock_file = None

    def start(self) -> None:
        with self._lifecycle:
            if self._lock_file is not None:
                return
            self._acquire_process_lock()
            try:
                with self._connection() as connection:
                    timestamp = _now()
                    error = json.dumps({"code": "JOB_INTERRUPTED", "message": "The service stopped before the outcome was recorded. Inspect the run before you submit a new job."})
                    connection.execute("UPDATE jobs SET state='interrupted',updated_at=?,finished_at=?,error=? WHERE state IN ('running','cancel_requested')", (timestamp, timestamp, error))
                self._stop.clear()
                self._workers = [threading.Thread(target=self._work, name=f"drawing2cad-job-{index}", daemon=True) for index in range(self._concurrency)]
                self._monitor = threading.Thread(target=self._monitor_cancellations, name="drawing2cad-job-cancellation", daemon=True)
                for worker in self._workers:
                    worker.start()
                self._monitor.start()
            except BaseException:
                self._stop.set()
                self._wake.set()
                for worker in self._workers:
                    if worker.is_alive():
                        worker.join()
                self._release_process_lock()
                raise

    def close(self) -> None:
        with self._lifecycle:
            self._stop.set()
            self._wake.set()
            for worker in self._workers:
                worker.join()
            if self._monitor is not None:
                self._monitor.join()
            self._workers = []
            self._monitor = None
            self._release_process_lock()

    def _claim(self) -> sqlite3.Row | None:
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("SELECT * FROM jobs WHERE state='queued' ORDER BY created_at,job_id LIMIT 1").fetchone()
            if row is not None:
                timestamp = _now()
                connection.execute("UPDATE jobs SET state='running',started_at=?,updated_at=? WHERE job_id=? AND state='queued'", (timestamp, timestamp, row["job_id"]))
            connection.commit()
        return row

    def _finish(self, job_id: str, state: str, *, result: str | None = None, error: dict[str, Any] | None = None) -> None:
        try:
            encoded_error = _encode(error, 16_384, "JOB_ERROR_INVALID") if error else None
        except DomainError:
            encoded_error = json.dumps({"code": "JOB_EXECUTION_FAILED", "message": "The job failed. Its error details exceeded the public error limits."})
        with self._connection() as connection:
            timestamp = _now()
            connection.execute(
                "UPDATE jobs SET state=?,updated_at=?,finished_at=?,result=?,error=? WHERE job_id=? AND state IN ('running','cancel_requested')",
                (state, timestamp, timestamp, result, encoded_error, job_id),
            )

    def _work(self) -> None:
        while not self._stop.is_set():
            row = self._claim()
            if row is None:
                self._wake.wait(0.1)
                self._wake.clear()
                continue
            job_id = row["job_id"]
            event = threading.Event()
            with self._active_lock:
                self._active[job_id] = event
            try:
                with self._connection() as connection:
                    state = connection.execute("SELECT state FROM jobs WHERE job_id=?", (job_id,)).fetchone()[0]
                if state == "cancel_requested":
                    self._finish(job_id, "cancelled")
                    continue
                if row["operation"] not in self._operations:
                    self._finish(job_id, "failed", error={"code": "JOB_OPERATION_UNSUPPORTED", "message": "The stored operation is not supported by this service."})
                    continue
                result = self._dispatcher(AccessContext(row["owner"]), row["operation"], json.loads(row["arguments"]), event)
                if not isinstance(result, dict):
                    raise DomainError("JOB_RESULT_INVALID", "The job result must be a JSON object.")
                encoded = _encode(result, MAX_RESULT_BYTES, "JOB_RESULT_INVALID")
                self._finish(job_id, "succeeded", result=encoded)
            except JobCancelled:
                self._finish(job_id, "cancelled")
            except JobFailed as error:
                try:
                    report = _encode(error.result, MAX_RESULT_BYTES, "JOB_RESULT_INVALID")
                except DomainError:
                    report = None
                self._finish(job_id, "failed", result=report, error=error.to_dict())
            except DomainError as error:
                # Domain errors are public contract errors. Other exception text
                # can contain host paths, credentials, or worker tracebacks.
                self._finish(job_id, "failed", error=error.to_dict())
            except BaseException:
                LOG.exception("Job %s (%s) failed", job_id, row["operation"])
                self._finish(job_id, "failed", error={"code": "JOB_EXECUTION_FAILED", "message": "The job failed. Inspect the run state before you retry."})
            finally:
                with self._active_lock:
                    self._active.pop(job_id, None)

    def _monitor_cancellations(self) -> None:
        while not self._stop.is_set() or any(worker.is_alive() for worker in self._workers):
            with self._connection() as connection:
                identifiers = connection.execute("SELECT job_id FROM jobs WHERE state='cancel_requested'").fetchall()
            with self._active_lock:
                for row in identifiers:
                    if row[0] in self._active:
                        self._active[row[0]].set()
            self._wake.wait(0.05)
            self._wake.clear()
