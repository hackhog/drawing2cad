"""Replace a restricted worker with the fixed independent STEPcode reader."""

from hashlib import sha256
import json
import os
from pathlib import Path

BINARY = Path("/usr/local/bin/drawing2cad-stepcode")
SOURCE_REVISION = "24783b448511b8f6bce2829286a3f00015430236"
SCHEMA_SHA256 = "32ced62e799a50cc857966ab6702adcbc5b0da00be290f232dcea275652059cf"


def capabilities() -> dict:
    """Report installation separately from a successful analysis."""
    return {"available": BINARY.is_file() and os.access(BINARY, os.X_OK),
            "analyzer": "STEPcode", "source_revision": SOURCE_REVISION,
            "schema_sha256": SCHEMA_SHA256, "profile": "drawing2cad.stepcode/1",
            "full_express_validation": "not_supported",
            "exact_edition_conformance": "not_tested",
            "independent_geometry_correctness": "not_supported"}


def exec_stepcode(directory: Path, scope: dict) -> None:
    """Keep Landlock, seccomp, and resource limits across execve."""
    if scope.get("profile") != "linux-landlock-seccomp-v1":
        raise ValueError("The independent analyzer requires the restricted worker profile.")
    if not capabilities()["available"]:
        raise ValueError("The independent STEPcode analyzer is not installed.")
    path = directory / "input.step"
    with path.open("rb") as stream:
        raw = stream.read(32 * 1024 * 1024 + 1)
    if len(raw) > 32 * 1024 * 1024:
        raise ValueError("The independent analyzer input exceeds 32 MiB.")
    os.execv(str(BINARY), [str(BINARY), str(path), json.dumps(scope, allow_nan=False), sha256(raw).hexdigest()])
