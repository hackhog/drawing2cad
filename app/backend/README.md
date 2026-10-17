# drawing-demo backend

This service supplies the demo HTTP API ([ADR 0012](../../docs/adr/0012-demo-app-as-frontend-and-backend-container.md)).
It uses `drawing2cad_mcp.pdf.PdfService` for drawing analysis and page rendering.
It derives review flags and converts uploaded STEP files to GLB for display.
The frontend container serves the UI and forwards `/api` requests to this service.
The backend does not serve static UI files or an MCP protocol endpoint.

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
| `POST` | `/api/extract` | Drawing data, `page_png`, `page_px_per_mm`, review flags, and provenance |
| `POST` | `/api/model` | GLB with media type `model/gltf-binary`, generated through `cascadio` |

Both upload endpoints accept multipart form data in the `file` field.
The PDF upload limit is 20 MiB. The STEP upload limit is 50 MiB.
Errors use status 413 for excess size, 415 for an incorrect format, and 422 for processing failures.
A disagreement between the analysis and render source hashes also returns status 422.

The API retains no uploaded files after the request.
It uses one temporary source file for analysis and rendering, compares the source hashes, and removes all request artifacts.
Returned provenance contains hashes without temporary server paths.

The analysis uses page 1 of the BCT/NX profile.
It supplies candidate text and sheet geometry, not verified part dimensions or general OCR.
See [ADR 0013](../../docs/adr/0013-vector-analysis-in-mcp.md) for the analysis limits.
The STEP conversion is for display only. It does not verify AP242, editable construction, or semantic PMI.

## Structure

- `src/drawing_demo/api.py`: upload processing, shared PDF service calls, and STEP display conversion.
- `src/drawing_demo/review.py`: review flags from service results.
- `Dockerfile`: Python runtime with the MCP package and Poppler.

The Docker build context is the repository root because the MCP package is a path dependency.
The image excludes input drawings and local configuration.
In Compose, the backend has no published host port.
The frontend reaches the API through the Compose network.
