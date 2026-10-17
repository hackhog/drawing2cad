# drawing-demo backend

This service supplies the web API ([ADR 0012](../../docs/adr/0012-demo-app-as-frontend-and-backend-container.md), [ADR 0016](../../docs/adr/0016-agent-runner-in-the-web-backend.md)).
It uses `drawing2cad_mcp.pdf.PdfService` for drawing analysis and page rendering.
It derives review flags and converts uploaded STEP files to GLB for display.
The frontend container serves the UI and forwards `/api` requests to this service.
The backend does not serve static UI files or an MCP protocol endpoint. It starts the MCP server for agent runs.

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
| `POST` | `/api/sources` | Store a PDF (multipart field `file`) and its analysis; returns the source record |
| `GET` | `/api/sources`, `/api/sources/{id}` | Source records: opaque ID, filename, size, SHA-256 |
| `DELETE` | `/api/sources/{id}` | Remove a source and its runs (409 while a run is active) |
| `GET` | `/api/sources/{id}/analysis` | Drawing data, `page_png`, `page_px_per_mm`, review flags, and provenance |
| `GET`/`POST` | `/api/sources/{id}/runs` | List runs / queue an agent run (503 without model endpoint) |
| `GET` | `/api/runs/{id}` | Phase, job, part, review, artifacts, and the agent report |
| `GET` | `/api/artifacts/{id}/content` | STEP or GLB content by opaque artifact ID |
| `POST` | `/api/model` | GLB for a STEP file that the user supplies (display only) |

The PDF upload limit is 20 MiB. The STEP upload limit is 50 MiB.
Errors use status 413 for excess size, 415 for an incorrect format, 422 for processing failures, and 404 for unknown or malformed IDs.
Structured errors have `code`, `message`, `field`, and `recovery` in `detail`.
A disagreement between the analysis and render source hashes returns status 422.

Uploaded sources stay in the data directory (`DRAWING2CAD_DATA_DIR`, default `.data`) until a user deletes them.
Analysis and rendering use temporary files that are removed after the request.
Returned records contain hashes and opaque IDs, never server paths.

The analysis uses page 1 of the BCT/NX profile.
It supplies candidate text and sheet geometry, not verified part dimensions or general OCR.
See [ADR 0013](../../docs/adr/0013-vector-analysis-in-mcp.md) for the analysis limits.
The STEP conversion is for display only. It does not verify AP242, editable construction, or semantic PMI.

## Agent runs

See [ADR 0016](../../docs/adr/0016-agent-runner-in-the-web-backend.md).
A run executes one bounded agent conversation (`drive()` from `drawing2cad_mcp.local_model_client`) in a background thread.
The backend starts `python -m drawing2cad_mcp` as a stdio subprocess; the agent can call only its permitted MCP tools.
After the conversation, the runner reads the part state with `part_read`, stores the released or diagnostic STEP, and converts it to GLB.
A model without release is a finished run with release state `blocked`. The UI marks it as a diagnostic model.

| Variable | Required | Meaning |
|---|---|---|
| `DRAWING2CAD_AGENT_BASE_URL` | for runs | OpenAI-compatible base URL, for example `https://<resource>.cognitiveservices.azure.com/openai/v1` |
| `DRAWING2CAD_AGENT_MODEL` | for runs | Model or deployment name; it must support function tools on Chat Completions |
| `DRAWING2CAD_AGENT_API_KEY` | for runs | API key; never in Git |
| `DRAWING2CAD_AGENT_API_KEY_HEADER` | no | `Authorization` (Bearer, default) or `api-key` (Azure AI Foundry) |
| `DRAWING2CAD_AGENT_REASONING_EFFORT` | no | Sent as `reasoning_effort` |
| `DRAWING2CAD_DATA_DIR` | no | Data directory; `/data` in the container |
| `DRAWING2CAD_SKILL_PATH` | no | Skill file for the agent; the image sets it |

CAD execution requires the Linux sandbox of the MCP worker. Use Docker Compose for agent runs on macOS or Windows.
Tests use a mocked model and do not call a model endpoint.

## Structure

- `src/drawing_demo/api.py`: HTTP routes, PDF analysis through the shared service, and STEP display conversion.
- `src/drawing_demo/store.py`: interim store for sources and run records (replaced by #24).
- `src/drawing_demo/agent/`: model adapter (`model.py`), runner (`runner.py`), and mapping of MCP results to the contract (`mapping.py`).
- `src/drawing_demo/review.py`: review flags from service results.
- `Dockerfile`: Python runtime with the MCP package, build123d, the sandbox libraries, Poppler, and the agent skill.

The Docker build context is the repository root because the MCP package is a path dependency.
The image excludes input drawings and local configuration.
In Compose, the backend has no published host port.
The frontend reaches the API through the Compose network.
