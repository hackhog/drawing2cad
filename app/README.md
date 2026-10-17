# drawing-demo

This demo uses the PDF service from `drawing2cad-mcp`.
Upload a drawing PDF to examine its vector analysis and review flags.
The API imports `PdfService` in the same process. It does not duplicate PDF analysis or expose an MCP protocol endpoint.

The app has two parts, each with its own container ([ADR 0012](../docs/adr/0012-demo-app-as-frontend-and-backend-container.md)):

| Part | Contents | Container |
|---|---|---|
| [frontend/](frontend/README.md) | React and TypeScript UI, review sequence, and 3D viewer | nginx serves the UI and forwards `/api` requests |
| [backend/](backend/README.md) | FastAPI, shared PDF service, review flags, and STEP-to-GLB display conversion | Python, accessible through the Compose network |

The browser connects to the frontend at `127.0.0.1:8000`.
The frontend forwards `/api` requests to `backend:8000`.
The backend uses the MCP package as a Python dependency.

## Build and run

From the repository root, run:

```bash
docker compose up --build
```

Open `http://localhost:8000`.
If a Compose project with the former single `app` service still runs, add `--remove-orphans` once.
The backend image includes the MCP package and Poppler.
Neither image includes source drawings or local configuration.
Both containers use a read-only file system. Temporary uploads and render artifacts use `/tmp`.

For a local installation, use Python 3.12 or later, uv, Node.js 22.12 or later, and Poppler.
Put `pdftoppm` on `PATH`, or set `DRAWING2CAD_PDFTOPPM` to its executable path.

Start the API in one terminal:

```bash
cd app/backend
uv sync --locked
uv run drawing-demo
```

Start the UI in another terminal:

```bash
cd app/frontend
npm ci
npm run dev
```

Open `http://localhost:5173` for UI development.
Vite forwards `/api` requests to port 8000.
After an MCP source change, refresh the non-editable dependency from `app/backend/`:

```bash
uv sync --reinstall-package drawing2cad-mcp
```

## User interface

The interface has four steps: **Drawing, Recognized, Review, and 3D model**.
UI text remains in German.
See [ADR 0007](../docs/adr/0007-demo-ui-guided-sequence-and-batch-upload.md) and
[ADR 0010](../docs/adr/0010-demo-ui-in-react-with-3d-viewer.md) for the design history.

- The overview shows each uploaded drawing and its status.
- The drawing view shows the original page and the existing stroke classes.
- The review view marks unclear strokes, unrecognized text characters, and missing views.
- The model view converts an uploaded STEP file to GLB for display.
- Batch upload sends a maximum of two PDFs at the same time.

Use the mouse wheel to zoom. Drag to move the sheet. Double-click to show the full sheet.
Click a review item to move to its location.
The UI includes its font and libraries. It does not use a CDN.

## PDF processing

The API supplies each upload to `PdfService.extract_drawing` and `PdfService.render_page`.
Both operations use one temporary source file.
The API compares their source hashes before it returns a result.
It removes the source file and render artifacts when the request ends.
The response includes source and render hashes without temporary server paths.

The current analysis uses the first PDF page and the BCT/NX drawing profile.
Pages must be unrotated, with matching CropBox and MediaBox coordinates.
The MediaBox origin must be zero, and `/UserUnit` must be 1.
Its stroke classes, outline-glyph templates, and view grouping are heuristic evidence.
It does not provide general OCR, complete dimension interpretation, or a verified CAD model.
Review all unclear data before drawing or CAD work.

The API uses Poppler at 102 DPI for the page image.
The response gives the image scale in pixels per millimeter.
PDF size, rendering time, and image pixel limits apply through the shared service.
The PDF upload limit is 20 MiB. The STEP upload limit is 50 MiB.

## API

| Method | Path | Response |
|---|---|---|
| `GET` | `/api/health` | Status and MCP package version |
| `POST` | `/api/extract` | Drawing data, `page_png`, `page_px_per_mm`, review flags, and provenance |
| `POST` | `/api/model` | GLB with media type `model/gltf-binary` |

Both upload endpoints accept multipart form data in the `file` field.
Errors use status 413 for excess size, 415 for an incorrect format, and 422 for processing failures.
A PDF hash mismatch also returns status 422.
The existing drawing response remains compatible with the React viewer.

The STEP viewer uses `cascadio` for display conversion only.
It does not create STEP data or verify AP242, editable construction, or semantic PMI.
The demo does not include a headless FreeCAD worker.
Use the drawing-first workflow and separate CAD validation for model production.

## Structure and validation

- `backend/src/drawing_demo/api.py`: upload limits, shared PDF service calls, and STEP display conversion.
- `backend/src/drawing_demo/review.py`: review flags derived from drawing data.
- `backend/Dockerfile`: Python runtime with the MCP package and Poppler.
- `frontend/`: React and TypeScript UI, nginx configuration, and frontend Dockerfile.
- `frontend/dist/`: ignored UI build output.

Run `uv run pytest` in `backend/` for API and review tests.
Sample-based tests are skipped when their inputs are absent.
Synthetic tests verify the shared service boundary, hash agreement, and temporary-file cleanup.
Run `npm run build` in `frontend/` for the type check and build.
Run `docker compose build` at the repository root for both container builds.
These commands describe the test procedure. They do not assert a completed test run.
