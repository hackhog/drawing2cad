# drawing-demo

This demo uses the PDF service from `drawing2cad-mcp`.
Upload a drawing PDF to examine its vector analysis and review flags.
The app imports `PdfService` in the same process. It does not duplicate PDF analysis or expose an MCP protocol endpoint.

## Build and run

From the repository root, run:

```bash
docker compose up --build
```

Open `http://localhost:8000`.
The image contains the app, the MCP package, and Poppler.
It excludes source drawings and local configuration.
The container runs with a read-only file system. Temporary uploads and render artifacts use `/tmp`.

For a local installation, use Python 3.12 or later, uv, Node.js 22.12 or later, and Poppler:

```bash
cd app/web
npm ci
npm run build
cd ..
uv sync --locked
uv run pytest
uv run drawing-demo
```

Put `pdftoppm` on `PATH`, or set `DRAWING2CAD_PDFTOPPM` to its executable path.
Without a UI build, the API remains available.
For UI development, start the API and run `npm run dev` in `web/`.
Vite forwards `/api` requests to port 8000.

After an MCP source change, refresh the non-editable dependency:

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

The app supplies each upload to `PdfService.extract_drawing` and `PdfService.render_page`.
Both operations use one temporary source file.
The app compares their source hashes before it returns a result.
It removes the source file and render artifacts when the request ends.
The response includes source and render hashes without temporary server paths.

The current analysis uses the first PDF page and the BCT/NX drawing profile.
Pages must be unrotated, with matching CropBox and MediaBox coordinates.
The MediaBox origin must be zero, and `/UserUnit` must be 1.
Its stroke classes, outline-glyph templates, and view grouping are heuristic evidence.
It does not provide general OCR, complete dimension interpretation, or a verified CAD model.
Review all unclear data before drawing or CAD work.

The app uses Poppler at 102 DPI for the page image.
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

- `src/drawing_demo/api.py`: upload limits, shared PDF service calls, STEP display conversion, and static UI routes.
- `src/drawing_demo/review.py`: review flags derived from drawing data.
- `web/`: React and TypeScript UI.
- `src/drawing_demo/static/`: ignored UI build output.
- `Dockerfile`: Node.js build stage and Python runtime stage.

Run `uv run pytest` for API and review tests.
Sample-based tests are skipped when their inputs are absent.
Synthetic tests verify the shared service boundary, hash agreement, and temporary-file cleanup.
Run `npm run build --prefix web` for the frontend type check and build.
Run `docker compose build` for the container build.
These commands describe the test procedure. They do not assert a completed test run.
