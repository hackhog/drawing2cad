"""Bounded process supervision for the maintained CAD worker."""

from __future__ import annotations

from dataclasses import dataclass
import json
import math
import os
from pathlib import Path
import selectors
import signal
import subprocess
import sys
import time
import uuid

from .sandbox import available


@dataclass(frozen=True)
class WorkerLimits:
    timeout_seconds: float = 90
    memory_mb: int = 3072
    max_log_bytes: int = 262144


class WorkerRunner:
    """Start a fresh process for each build and each STEP validation."""

    def __init__(self, storage: Path, limits: WorkerLimits | None = None):
        self.storage = Path(storage).resolve()
        self.limits = limits or WorkerLimits()

    @staticmethod
    def capabilities() -> dict:
        return available()

    def run(self, operation: str, *, description: dict | None = None, input_step: Path | None = None,
            code: str | None = None, drawing_spec: dict | None = None, revision: int | None = None,
            timeout: float | None = None, memory_mb: int | None = None,
            export_profile: str = "ap214", pmi: dict | None = None,
            parameter_changes: dict | None = None) -> dict:
        capability = available()
        if not capability["available"]:
            return {"status": "fail", "error": {"code": "SANDBOX_UNAVAILABLE", "message": capability["reason"]}}
        if self.storage.resolve() != self.storage:
            return {"status": "fail", "error": {"code": "STORAGE_PATH_CHANGED", "message": "Worker storage changed its resolved location."}}
        self.storage.mkdir(parents=True, exist_ok=True)
        directory = self.storage / uuid.uuid4().hex
        directory.mkdir(mode=0o700)
        if input_step is not None:
            data = input_step.read_bytes()
            if len(data) > 32 * 1024 * 1024:
                return {"status": "fail", "error": {"code": "STEP_TOO_LARGE", "message": "Candidate exceeds 32 MiB."}}
            (directory / "input.step").write_bytes(data)
        deadline_seconds = timeout if timeout is not None else self.limits.timeout_seconds
        request = {"operation": operation, "work_dir": str(directory), "description": description,
                   "memory_mb": memory_mb if memory_mb is not None else self.limits.memory_mb,
                   "cpu_seconds": max(1, math.ceil(deadline_seconds + 1)), "code": code,
                   "drawing_spec": drawing_spec, "revision": revision,
                   "export_profile": export_profile, "pmi": pmi,
                   "parameter_changes": parameter_changes}
        if operation == "probe":
            forbidden = self.storage / (directory.name + "-outside.txt")
            forbidden.write_text("unchanged", encoding="utf-8")
            request["forbidden_file"] = str(forbidden)
        payload = json.dumps(request, allow_nan=False).encode("utf-8")
        if len(payload) > 2 * 1024 * 1024:
            return {"status": "fail", "error": {"code": "WORKER_INPUT_LIMIT", "message": "Worker input exceeds 2 MiB."}}
        environment = {"PATH": os.defpath, "HOME": str(directory), "TMPDIR": str(directory),
                       "PYTHONNOUSERSITE": "1", "PYTHONDONTWRITEBYTECODE": "1",
                       "OPENBLAS_NUM_THREADS": "1", "OMP_NUM_THREADS": "1", "MKL_NUM_THREADS": "1",
                       "NUMEXPR_NUM_THREADS": "1", "LANG": "C.UTF-8"}
        package_root = str(Path(__file__).resolve().parent.parent)
        # The import path is maintained server code, never a client value.
        command = [sys.executable, "-I", "-u", "-c",
                   "import sys; sys.path.insert(0," + repr(package_root) + "); from drawing2cad_mcp.cad_worker import main; main()"]
        started = time.monotonic()
        process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   cwd=directory, env=environment, close_fds=True, start_new_session=True)
        reason = None
        streams = {"stdout": bytearray(), "stderr": bytearray()}
        try:
            process.stdin.write(payload)
            process.stdin.close()
            with selectors.DefaultSelector() as selector:
                for name in streams:
                    pipe = getattr(process, name)
                    os.set_blocking(pipe.fileno(), False)
                    selector.register(pipe, selectors.EVENT_READ, name)
                while selector.get_map():
                    if time.monotonic() - started > deadline_seconds:
                        reason = "WORKER_TIMEOUT"
                        break
                    for key, _ in selector.select(timeout=0.05):
                        chunk = os.read(key.fileobj.fileno(), 65536)
                        if not chunk:
                            selector.unregister(key.fileobj)
                            continue
                        remaining = self.limits.max_log_bytes - sum(map(len, streams.values()))
                        streams[key.data].extend(chunk[:max(0, remaining)])
                        if len(chunk) > remaining:
                            reason = "WORKER_LOG_LIMIT"
                            break
                    if reason:
                        break
            if reason:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            try:
                process.wait(timeout=max(0.01, deadline_seconds - (time.monotonic() - started)))
            except subprocess.TimeoutExpired:
                reason = "WORKER_TIMEOUT"
                os.killpg(process.pid, signal.SIGKILL)
                process.wait(timeout=5)
        finally:
            # Also stop descendants which closed the inherited output pipes.
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait(timeout=5)
            for name in streams:
                getattr(process, name).close()
        stdout = streams["stdout"].decode("utf-8", errors="replace")
        stderr = streams["stderr"].decode("utf-8", errors="replace")
        record = {"worker_id": directory.name, "work_dir": str(directory), "exit_code": process.returncode,
                  "duration_seconds": time.monotonic() - started, "logs": {"stdout": stdout[-8192:], "stderr": stderr[-8192:]}}
        if reason:
            result = {"status": "fail", "error": {"code": reason, "message": "The worker exceeded its configured limit."}}
        elif process.returncode != 0:
            result = {"status": "fail", "error": {"code": "WORKER_CRASH", "message": f"Worker exited with code {process.returncode}."}}
        else:
            messages = [line[len("D2C_RESULT:"):] for line in stdout.splitlines() if line.startswith("D2C_RESULT:")]
            try:
                if len(messages) != 1:
                    raise ValueError("Expected one structured worker result.")
                def reject_constant(value):
                    raise ValueError("Worker result contains a non-finite number: " + value)
                result = json.loads(messages[0], parse_constant=reject_constant)
                if not isinstance(result, dict) or result.get("status") not in {"pass", "fail", "success", "failed"}:
                    raise ValueError("Invalid worker result status.")
            except (ValueError, TypeError, RecursionError) as error:
                result = {"status": "fail", "error": {"code": "WORKER_PROTOCOL_ERROR", "message": str(error)}}
        record["result"] = result
        # Parent records stay outside the worker-writable directory. A worker
        # must not redirect this write with a symlink or hard link.
        record_path = self.storage / (directory.name + ".json")
        with record_path.open("x", encoding="utf-8") as stream:
            json.dump(record, stream, indent=2, allow_nan=False)
        return {**result, "worker": {key: value for key, value in record.items() if key != "result"}}

    def probe(self) -> dict:
        """Test restrictions and error recovery without executing client code."""
        restrictions = self.run("probe")
        timeout = self.run("probe_timeout", timeout=0.5)
        memory = self.run("probe_memory", timeout=5, memory_mb=128)
        crash = self.run("probe_crash", timeout=5)
        recovery = self.run("probe")
        checks = list(restrictions.get("checks", []))
        for name, result, expected in (("timeout", timeout, "WORKER_TIMEOUT"), ("memory", memory, "WORKER_MEMORY_LIMIT"),
                                        ("crash", crash, "WORKER_CRASH")):
            checks.append({"check": name, "status": "pass" if result.get("error", {}).get("code") == expected else "fail",
                           "observed": result.get("error", {}).get("code"), "worker": result.get("worker", {}).get("worker_id")})
        checks.append({"check": "recovery", "status": "pass" if recovery.get("status") == "pass" else "fail"})
        return {"status": "pass" if restrictions.get("status") == "pass" and all(row["status"] == "pass" for row in checks) else "fail",
                "checks": checks, "restrictions": restrictions.get("sandbox"),
                "workers": [r.get("worker", {}).get("worker_id") for r in (restrictions, timeout, memory, crash, recovery)]}
