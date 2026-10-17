# drawing-demo backend

HTTP API of the demo app ([ADR 0012](../../docs/adr/0012-demo-app-as-frontend-and-backend-container.md)).
It reads drawing PDFs with the extractor (`../../extractor`), derives the review flags, and changes STEP to GLB.
It does not serve the UI. The frontend container does this and sends `/api` to this service.

## Build, test, run

With [uv](https://docs.astral.sh/uv/):

```bash
cd app/backend
uv sync --locked
uv run pytest                # sample tests are skipped if the sample drawings are missing
uv run drawing-demo          # → http://127.0.0.1:8000/api/health
```

The extractor is a *non-editable* path dependency. After a change in `../../extractor`, run
`uv sync --reinstall-package drawing-extractor`.

## API

| Method | Path | Response |
|---|---|---|
| `GET` | `/api/health` | `{"status": "ok", "extractor_schema": 2}` |
| `POST` | `/api/extract` (multipart, field `file`, max. 20 MB) | `drawing` (extractor JSON), `page_png` (data URI), `page_px_per_mm`, `review` (flags) |
| `POST` | `/api/model` (multipart, field `file`, STEP, max. 50 MB) | GLB (`model/gltf-binary`), meshed with OpenCASCADE (`cascadio`) |

Errors: 413 too large, 415 not a PDF or not a STEP file, 422 drawing or STEP cannot be read (the extractor is made for the BCT template).
The API keeps no state. Uploaded PDFs are only in a temporary directory during the request.

## Structure

- `src/drawing_demo/api.py`: FastAPI. Processes the PDF in a temporary directory and changes STEP to GLB.
- `src/drawing_demo/review.py`: review flags from the extractor JSON.
- `scripts/make_demo_drawing.py`: makes the demo drawing with unclear locations (see below).
- `Dockerfile`: Python image with the extractor. The build context is the repository root, because the extractor is a path dependency.

## Demo drawing with unclear locations

The original samples have no open locations. To show "marked, not guessed", `scripts/make_demo_drawing.py` makes a copy of
Flansch with three defects. The extractor gives exactly three review flags for this drawing:

```bash
uv run python scripts/make_demo_drawing.py ../../resources/Drawing2CAD/Flansch/Flansch_dwg.pdf ../../output/demo/Flansch-Demo_dwg.pdf
```

The result goes to the ignored `output/` directory.
