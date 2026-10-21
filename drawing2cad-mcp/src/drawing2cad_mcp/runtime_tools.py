"""System tools of the domain core and its restricted worker.

The MCP image and the backend image get these tools from one shared runtime stage (deployment/Dockerfile, ADR 0035).
A process in such an image sets DRAWING2CAD_REQUIRE_RUNTIME_TOOLS=1 and refuses to start when a tool is missing,
so a missing tool shows before a run, not during it. Run `python -m drawing2cad_mcp.runtime_tools` to see the report.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from typing import Any

REQUIRE_ENV = "DRAWING2CAD_REQUIRE_RUNTIME_TOOLS"
# The tool, and the domain operation that needs it.
PURPOSES = {
    "poppler": "drawing_verify renders the final PDF with Poppler pdftoppm.",
    "tesseract": "drawing_verify reads drawing texts with Tesseract and its eng and deu language data.",
    "stepcode": "The AP242 release checks read STEP files with the independent STEPcode reader.",
}


def _run(command: list[str], expected: set[int]) -> tuple[bool, str]:
    """Start a program once. Only an expected exit code passes. A signal, a load failure, or another exit code fails."""
    try:
        result = subprocess.run(command, capture_output=True, timeout=20, check=False)
    except (OSError, subprocess.TimeoutExpired) as error:
        return False, type(error).__name__
    output = (result.stdout + result.stderr).decode("utf-8", errors="replace").strip()
    if result.returncode not in expected or "error while loading shared libraries" in output:
        return False, f"exit code {result.returncode}: " + output[:300]
    return True, output.splitlines()[0][:200] if output else f"exit code {result.returncode}"


def _probe(name: str, capability: dict[str, Any]) -> dict[str, Any]:
    """Run the tool once outside the sandbox. The check runs at image build and at process start, not in a worker."""
    from .adapters import poppler, stepcode, tesseract

    if not capability.get("available"):
        return {"ok": False, "detail": "not installed"}
    if name == "poppler":
        ok, detail = _run([str(poppler.BINARY), "-v"], {0})
    elif name == "stepcode":
        # Without arguments, the reader prints its usage and exits with EX_USAGE (64).
        ok, detail = _run([str(stepcode.BINARY)], {64})
    else:
        # Initialize each language on its own. Tesseract starts with "eng+deu" when only one of the two languages loads.
        try:
            for language in tesseract.LANGUAGES.split("+"):
                reader = tesseract.Ocr(language)
                reader.close()
            ok, detail = True, f"initialized {tesseract.LANGUAGES} one by one"
        except (OSError, ValueError) as error:
            ok, detail = False, str(error)[:300]
    return {"ok": ok, "detail": detail}


def report(probe: bool = True) -> dict[str, Any]:
    """The capability report of each system tool. With probe, each installed tool also runs once."""
    from .adapters import poppler, stepcode, tesseract

    tools = {"poppler": poppler.capabilities(), "tesseract": tesseract.capabilities(), "stepcode": stepcode.capabilities()}
    if probe:
        for name, capability in tools.items():
            capability["probe"] = _probe(name, capability)
            capability["available"] = bool(capability.get("available")) and capability["probe"]["ok"]
    return tools


def missing(tools: dict[str, Any] | None = None) -> list[str]:
    tools = report() if tools is None else tools
    return sorted(name for name, capability in tools.items() if not capability.get("available"))


def require() -> None:
    """Raise when a system tool is missing. The message names each missing tool and its purpose."""
    absent = missing()
    if absent:
        raise RuntimeError("Missing system tools of the drawing2cad runtime: "
                           + "; ".join(f"{name} ({PURPOSES[name]})" for name in absent)
                           + " Build the image from the runtime stage of deployment/Dockerfile.")


def require_if_configured() -> None:
    """Require the tools in an image that sets DRAWING2CAD_REQUIRE_RUNTIME_TOOLS=1. Other environments skip the check."""
    if os.environ.get(REQUIRE_ENV) == "1":
        require()


def main() -> None:
    tools = report()
    print(json.dumps(tools, indent=2, sort_keys=True))
    absent = missing(tools)
    if absent:
        print("Missing system tools: " + ", ".join(absent), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
