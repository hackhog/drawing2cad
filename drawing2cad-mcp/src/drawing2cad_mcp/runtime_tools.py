"""System tools of the domain core and its restricted worker.

The MCP image and the backend image get these tools from one shared runtime stage (deployment/Dockerfile, ADR 0035).
A process in such an image sets DRAWING2CAD_REQUIRE_RUNTIME_TOOLS=1 and refuses to start when a tool is missing,
so a missing tool shows before a run, not during it. Run `python -m drawing2cad_mcp.runtime_tools` to see the report.
"""

from __future__ import annotations

import json
import os
import sys
from typing import Any

REQUIRE_ENV = "DRAWING2CAD_REQUIRE_RUNTIME_TOOLS"
# The tool, and the domain operation that needs it.
PURPOSES = {
    "poppler": "drawing_verify renders the final PDF with Poppler pdftoppm.",
    "tesseract": "drawing_verify reads drawing texts with Tesseract and its eng and deu language data.",
    "stepcode": "The AP242 release checks read STEP files with the independent STEPcode reader.",
}


def report() -> dict[str, Any]:
    """The capability report of each system tool. It does not run a tool."""
    from .adapters import poppler, stepcode, tesseract

    return {"poppler": poppler.capabilities(), "tesseract": tesseract.capabilities(), "stepcode": stepcode.capabilities()}


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
