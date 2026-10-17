# drawing-demo backend

This service supplies the web API ([ADR 0012](../../docs/adr/0012-demo-app-as-frontend-and-backend-container.md), [ADR 0018](../../docs/adr/0018-agent-runner-in-the-web-backend.md)).
It creates one shared domain service (`drawing2cad_mcp.server.Application`, domain profile) for the process.
Web routes call this service. The backend also mounts its MCP endpoint at `/mcp` for agent runs.
It derives review flags and converts STEP files to GLB for display.
The frontend container serves the UI and forwards only `/api` requests to this service.
The `/mcp` endpoint accepts loopback hosts only. The backend does not serve static UI files.

## Build, test, and run

Use Python 3.12 or later, [uv](https://docs.astral.sh/uv/), and Poppler:

```bash
cd app/backend
uv sync --locked
uv run pytest
uv run drawing-demo
```

Put `pdftoppm` on `PATH`, or set `DRAWING2CAD_PDFTOPPM` to its executable path.
The health endpoint is `http://127.0.0.1:8000/api/health`.
Sample-based tests are skipped when their source drawings are absent.

The MCP package is a non-editable path dependency.
After a change in `../../drawing2cad-mcp`, run:

```bash
uv sync --reinstall-package drawing2cad-mcp
```

## API

| Method | Path | Response |
|---|---|---|
| `GET` | `/api/health` | Status and `drawing2cad_mcp_version` |
| `GET` | `/api/capabilities` | Available functions; `runs` is true only with a configured model endpoint |
| `POST` | `/api/sources` | Upload a PDF (multipart field `file`) to the domain service; returns the source record |
| `GET` | `/api/sources`, `/api/sources/{id}` | Source records: opaque ID, filename, size, SHA-256 |
| `GET` | `/api/sources/{id}/analysis` | Drawing data, `page_png`, `page_px_per_mm`, review flags, and provenance |
| `GET`/`POST` | `/api/sources/{id}/runs` | List runs / queue an agent run (503 without model endpoint) |
| `DELETE` | `/api/sources/{id}` | Delete a source with its web run records (409 `RUN_ACTIVE` while a run is active) |
| `GET` | `/api/runs/{id}` | Phase, job, part, review, artifacts, and the agent report |
| `GET`/`PUT` | `/api/runs/{id}/note` | Read / replace the run note; `PUT` takes `expected_revision` and `text` (409 on a stale revision or an active run) |
| `GET` | `/api/runs/{id}/files`, `/api/runs/{id}/archive` | Run record and agent trace, as single files or a ZIP archive |
| `GET` | `/api/artifacts/{id}/content` | Artifact content by opaque ID, verified against its SHA-256 |
| `POST` | `/api/model` | GLB for a STEP file that the user supplies (display only) |

The PDF upload limit is 20 MiB. The STEP upload limit is 50 MiB.
Errors use status 413 for excess size, 415 for an incorrect format, 422 for processing failures, and 404 for unknown or malformed IDs.
Structured errors have `code`, `message`, `field`, and `recovery` in `detail`. A domain error keeps its code.
A disagreement between the analysis and render source hashes returns status 422.

The domain store is in the data directory (`DRAWING2CAD_DATA_DIR`, default `.data`).
The backend keeps the analysis of up to 32 sources in memory, so a page is not rendered again for each request.
Returned records contain hashes and opaque IDs, never server paths.

The analysis uses page 1 of the BCT/NX profile.
It supplies candidate text and sheet geometry, not verified part dimensions or general OCR.
See [ADR 0013](../../docs/adr/0013-vector-analysis-in-mcp.md) for the analysis limits.
The STEP conversion is for display only. It does not verify AP242, editable construction, or semantic PMI.

## Agent runs

See [ADR 0018](../../docs/adr/0018-agent-runner-in-the-web-backend.md).
A run executes one bounded agent conversation (`drive()` from `drawing2cad_mcp.local_model_client`) in a background thread.
The agent connects to the mounted `/mcp` endpoint and can call only its permitted tools, with the uploaded source ID as its only input.
The runner stores the final agent report as the first text of the note of the part run. Users can change this note later.
The run view shows the report from the agent trace (`summary.json`), so a changed note does not change the report.
Part state, review, and artifacts come from the domain service for each request.
A built model without release is a finished run with release state `blocked`. Only a released STEP is an artifact.

| Variable | Required | Meaning |
|---|---|---|
| `DRAWING2CAD_AGENT_BASE_URL` | for runs | OpenAI-compatible base URL, for example `https://<resource>.cognitiveservices.azure.com/openai/v1` |
| `DRAWING2CAD_AGENT_MODEL` | for runs | Model or deployment name; it must support function tools on the selected API |
| `DRAWING2CAD_AGENT_API` | no | `chat` (Chat Completions, default) or `responses` (Responses API, for example for `gpt-6.1-sol`) |
| `DRAWING2CAD_AGENT_API_KEY` | for runs | API key; never in Git |
| `DRAWING2CAD_AGENT_API_KEY_HEADER` | no | `Authorization` (Bearer, default) or `api-key` (Azure AI Foundry) |
| `DRAWING2CAD_AGENT_REASONING_EFFORT` | no | Sent as `reasoning_effort` (Chat Completions) or `reasoning.effort` (Responses API) |
| `DRAWING2CAD_DATA_DIR` | no | Data directory; `/data` in the container |
| `DRAWING2CAD_SKILL_PATH` | no | Skill file for the agent; the image sets it |
| `DRAWING2CAD_MCP_URL` | no | MCP endpoint for agent runs; default `http://127.0.0.1:$PORT/mcp` |
| `DRAWING2CAD_HTTP_TOKEN` | no | Bearer token for `/mcp`; the runner sends it |
| `DRAWING2CAD_CAD_ENABLED` | no | `1` (default) enables CAD operations of the domain service |

CAD execution requires the Linux sandbox of the MCP worker. Use Docker Compose for agent runs on macOS or Windows.
Tests use a scripted model and do not call a model endpoint.

## Structure

- `src/drawing_demo/api.py`: HTTP routes, analysis through the domain service, and STEP display conversion.
- `src/drawing_demo/service.py`: the domain service of the process, its MCP endpoint, uploads, and verified artifact reads.
- `src/drawing_demo/jobs.py`: web run records (job state, agent trace, domain part run ID).
- `src/drawing_demo/agent/`: model adapter (`model.py`), runner (`runner.py`), and mapping of domain results to the contract (`mapping.py`).
- `src/drawing_demo/review.py`: review flags from service results.
- `Dockerfile`: Python runtime with the MCP package, build123d, the sandbox libraries, Poppler, and the agent skill.

The Docker build context is the repository root because the MCP package is a path dependency.
The image excludes input drawings and local configuration.
In Compose, the backend has no published host port.
The frontend reaches the API through the Compose network.
