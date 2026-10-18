"""One disposable, restricted CAD operation. Input and result use JSON on pipes."""

from __future__ import annotations

import json
from copy import deepcopy
import os
from pathlib import Path
import sys

from .sandbox import SandboxError, restrict

PREFIX = "D2C_RESULT:"


def execute(request: dict) -> dict:
    directory = Path(request["work_dir"]).resolve(strict=True)
    scope = restrict(directory, memory_mb=request["memory_mb"], cpu_seconds=request["cpu_seconds"],
                     concurrent_workers=request["concurrent_workers"])
    operation = request["operation"]
    if operation == "probe":
        import socket
        results = []
        for name, action in (
            ("network_denial", lambda: socket.socket(socket.AF_INET, socket.SOCK_STREAM)),
            ("outside_write_denial", lambda: Path(request["forbidden_file"]).write_text("changed", encoding="utf-8")),
            ("outside_read_denial", lambda: Path(request["forbidden_file"]).read_bytes()),
            ("outside_metadata_denial", lambda: os.chmod(request["forbidden_file"], 0o777)),
            ("process_creation_denial", os.fork),
            ("session_escape_denial", os.setsid),
        ):
            try:
                value = action()
                if hasattr(value, "close"):
                    value.close()
                results.append({"check": name, "status": "fail"})
            except PermissionError:
                results.append({"check": name, "status": "pass"})
            except OSError as error:
                results.append({"check": name, "status": "fail", "error": str(error)})
        (directory / "allowed.txt").write_text("allowed", encoding="utf-8")
        results.append({"check": "job_write", "status": "pass"})
        return {"status": "pass" if all(row["status"] == "pass" for row in results) else "fail", "checks": results, "sandbox": scope}
    if operation == "probe_timeout":
        while True:
            pass
    if operation == "probe_memory":
        chunks = []
        while True:
            chunks.append(bytearray(16 * 1024 * 1024))
    if operation == "probe_crash":
        os._exit(77)
    if operation == "probe_logs":
        sys.stdout.write("x" * (512 * 1024))
        sys.stdout.flush()
        return {"status": "pass"}
    if operation == "build":
        from .cad_kernel import build
        result = build(request["description"], directory,
                       export_profile=request.get("export_profile", "ap214"), pmi=request.get("pmi"))
    elif operation == "reconstruct_step":
        from .adapters.ap242 import reconstruct_step
        result = reconstruct_step(directory / "input.step", directory,
                                  parameter_changes=request.get("parameter_changes"))
    elif operation == "analyze_ap242":
        from .adapters.stepcode import exec_stepcode
        exec_stepcode(directory, scope)
        raise RuntimeError("The independent analyzer did not replace its restricted worker.")
    elif operation == "ap242_visual":
        from .adapters.ap242_visual import render_ap242_inspection
        result = render_ap242_inspection(directory / "input.step", directory)
    elif operation == "drawing":
        from .drafting import render_drawing
        result = render_drawing(request["drawing_spec"], request["description"], request["revision"], directory)
    elif operation == "validate":
        from .cad_validation import validate_step
        result = validate_step(directory / "input.step", request["description"])
    elif operation == "projection_check":
        from .projection import check
        result = check(directory / "input.step", directory / "input.pdf", request["page"], request["views"], directory)
    elif operation == "build_code":
        import build123d
        from .cad_kernel import export_shape
        namespace = {"build123d": build123d, "description": deepcopy(request["description"]),
                     "__builtins__": __builtins__}
        exec(compile(request["code"], "<sandboxed-build-code>", "exec"), namespace, namespace)
        shape = namespace.get("result")
        if not isinstance(shape, build123d.Shape):
            raise ValueError("build_code must assign a build123d Shape to result.")
        result = export_shape(shape, request["description"], directory)
    else:
        raise ValueError("Unknown worker operation.")
    return {**result, "sandbox": scope}


def main() -> None:
    try:
        raw = sys.stdin.buffer.read(2 * 1024 * 1024 + 1)
        if len(raw) > 2 * 1024 * 1024:
            raise ValueError("Worker input exceeds 2 MiB.")
        request = json.loads(raw)
        result = execute(request)
    except MemoryError:
        result = {"status": "fail", "error": {"code": "WORKER_MEMORY_LIMIT", "message": "Worker memory limit reached."}}
    except SandboxError as error:
        result = {"status": "fail", "error": {"code": "SANDBOX_UNAVAILABLE", "message": str(error)}}
    except Exception as error:
        from .cad_kernel import CadBuildError

        result = {"status": "fail", "error": {"code": getattr(error, "code", "CAD_OPERATION_FAILED"),
                                               "message": str(error)[:2000],
                                               "feature_id": getattr(error, "feature_id", None)},
                  "checks": getattr(error, "checks", [])}
        if isinstance(error, CadBuildError) and error.details is not None:
            result["error"]["details"] = error.details
    sys.stdout.write(PREFIX + json.dumps(result, allow_nan=False) + "\n")
    sys.stdout.flush()


if __name__ == "__main__":
    main()
