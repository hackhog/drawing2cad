# 35. Shared runtime base for the MCP and backend images

Date: 2026-10-21

## Status

The MCP transport description below is replaced by [ADR 0040](0040-streamable-http-as-the-only-mcp-transport.md).
Accepted. Changes the image build of [ADR 0027](0027-container-images-on-ghcr-for-version-tags.md). The publication rules of ADR 0027 stay valid.
Implemented in `deployment/Dockerfile`, `drawing2cad-mcp/src/drawing2cad_mcp/runtime_tools.py`, the Compose files, and the workflows.

## Context

The same domain core (`DomainService` and the restricted build123d worker) runs in two images:

- the MCP image, a standalone MCP server for external MCP clients (stdio and Streamable HTTP),
- the backend image, the web API with the agent runner and its MCP endpoint (ADR 0018).

Each image had its own Dockerfile with its own list of system packages. A Python dependency does not supply its system packages,
so each new system tool had to be added to both files by hand. The drawing verification (ADR 0032) added Tesseract only to the MCP image.
In the web stack, `drawing_verify` then failed in each run. The backend image also had no STEPcode reader and used an unpinned base image.

## Decision

### One runtime definition

- `deployment/Dockerfile` is the one Dockerfile of the MCP image and the backend image. Its stage `runtime` contains Python (base image pinned by digest),
  Poetry, the system packages of the CAD worker, Poppler, Tesseract 5 with `eng` and `deu`, and the STEPcode reader built in the stage `stepcode-build`.
- A system tool of the domain core is added to the stage `runtime`, and only there.
- The targets `mcp`, `mcp-test`, and `backend` start from `runtime`. They differ only in their application layer, user, entry point, and data volume.
- The former files `drawing2cad-mcp/Dockerfile` and `app/backend/Dockerfile` are removed. The frontend image keeps its own Dockerfile, because it has no domain core.

A shared stage in one file was selected, not a backend image `FROM` the published MCP image. With a shared stage, a local build and a release build
need no image in a registry, the build order of ADR 0027 does not change, and the MCP image does not contain the backend.

### Separate images, entry points, and data

- The MCP server stays usable without the web backend and the web UI. Its image does not contain backend code.
- The backend and the web UI stay optional components.
- The final images, their entry points, and their data volumes stay separate: `cad-data` for the MCP server and `backend-data` for the backend.
  A run on one entry point is not visible on the other entry point. A shared volume is not part of this decision.

### Tool check

- `drawing2cad_mcp.runtime_tools` reports Poppler, Tesseract with its language data, and the STEPcode reader, and names the domain operation that needs each tool.
  It runs each installed tool once: `pdftoppm -v` must exit with 0, the STEPcode reader without arguments must exit with its usage code 64,
  and Tesseract must initialize with `eng` and with `deu`, each language on its own. A signal, a load failure, or another exit code does not pass.
- The image build runs `python -m drawing2cad_mcp.runtime_tools` in the targets `mcp` and `backend`. A missing tool stops the build, so CI fails.
- The stage `runtime` sets `DRAWING2CAD_REQUIRE_RUNTIME_TOOLS=1`. In an image, the MCP server and the backend refuse to start when a tool is missing.
  A development installation outside an image does not set the variable and does not need the tools.
- The MCP and backend workflows run the tool check in the built image. Both workflows start for a change of `deployment/Dockerfile`.

### Publication

- The release workflow builds the targets `mcp` and `backend` of `deployment/Dockerfile`. Version tags, platforms, and image names of ADR 0027 do not change.

## Consequences

- A tool added for one entry point is present for the other entry point.
- The backend image is larger. It now contains Tesseract and the STEPcode reader, which its domain operations need.
- The build of the backend image compiles the STEPcode reader once more, unless the build cache has the stage `stepcode-build`.

## Tests

- `drawing2cad-mcp/tests/test_runtime_tools.py`: the report names missing tools and their purposes; the start check runs only with
  `DRAWING2CAD_REQUIRE_RUNTIME_TOOLS=1`; in the test image, each tool is present.
- The workflows build the targets `mcp-test`, `mcp`, and `backend` and run the tool check in the `mcp` and `backend` images.
- The local stack runs `drawing_verify` in a web run without the Tesseract error.
