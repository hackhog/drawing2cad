# drawing-demo

This demo uses the PDF service from `drawing2cad-mcp`.
Upload a drawing PDF to examine its vector analysis and review flags.
The API uses one shared domain service of `drawing2cad-mcp` in the same process ([ADR 0018](../docs/adr/0018-agent-runner-in-the-web-backend.md)).
It does not duplicate PDF analysis. It mounts the MCP endpoint of the same service at `/mcp` for its agent runs.

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

The UI uses React, TanStack Router, TanStack Query, and shadcn ([ADR 0015](../docs/adr/0015-web-ui-on-tanstack-shadcn-with-service-adapter.md)).
UI text is English ([ADR 0022](../docs/adr/0022-ui-text-in-english.md)). See [frontend/README.md](frontend/README.md) for routes, service adapters, and the structure.

- The overview shows each uploaded drawing, its upload progress, and its status.
- The drawing page has the four steps **Drawing, Recognized, Review, and 3D model** ([ADR 0007](../docs/adr/0007-demo-ui-guided-sequence-and-batch-upload.md)).
- The review step marks unclear strokes, unrecognized text characters, and missing views.
- The model step converts an uploaded STEP file to GLB for display.
- The run page shows job state, parameters and operations, review data, the agent report, results, and the run note.
  Users can change the run note. Parameter edits show as unavailable; `npm run dev:fixture` shows them with simulated data.
- Batch upload sends a maximum of two PDFs at the same time.

Use the mouse wheel to zoom. Drag to move the sheet. Double-click to show the full sheet.
Click a review item to move to its location.
The UI includes its font and libraries. It does not use a CDN.

## PDF processing

The API transfers each upload to the domain service in chunks. The domain service stores the source with its SHA-256.
The analysis uses the domain operations `drawing_extract` and `pdf_render_page` on the stored source.
The API compares their source hashes and rejects a result if they differ.
The stored source stays in the data directory until a user deletes it; agent runs read it there.
Responses include source and render hashes and opaque IDs, without server paths.

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

## API and agent runs

See [backend/README.md](backend/README.md) for the endpoints and configuration.
The browser uploads PDFs to `/api/sources`. The backend transfers each source to the shared domain service.
"Lauf starten" queues an agent run ([ADR 0018](../docs/adr/0018-agent-runner-in-the-web-backend.md)):
the agent builds the model only through the MCP endpoint of the same service, and step 4 shows the released model.
Runs need a model endpoint. Copy `.env.example` in the repository root to `.env` and fill in the values; without `.env`, runs show as unavailable.
Docker Compose also takes `DRAWING2CAD_AGENT_API_KEY` from the shell, so the key can stay in a password manager instead of `.env`.

## Structure and validation

- `backend/src/drawing_demo/api.py`: web routes on the shared domain service, and STEP display conversion.
- `backend/src/drawing_demo/service.py`: the one domain service of the backend and its mounted MCP endpoint.
- `backend/src/drawing_demo/review.py`: review flags derived from drawing data.
- `backend/Dockerfile`: Python runtime with the MCP package and Poppler.
- `frontend/`: React and TypeScript UI, nginx configuration, and frontend Dockerfile.
- `frontend/dist/`: ignored UI build output.

Run `uv run pytest` in `backend/` for API and review tests.
Sample-based tests are skipped when their inputs are absent.
Synthetic tests verify the shared service boundary, path-free records, and one agent run through the mounted MCP endpoint.
Run `npm test` and `npm run build` in `frontend/` for the unit tests, the type check, and the build.
Run `docker compose build` at the repository root for both container builds.
These commands describe the test procedure. They do not assert a completed test run.
