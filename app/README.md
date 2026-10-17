# drawing-demo

Demo user interface for Drawing2CAD ([ADR 0006](../docs/adr/0006-demo-as-one-container-docker-compose.md)).
Upload drawing PDFs, look at the result of the extractor (`../extractor`) as an interactive drawing, and examine the review flags.

## Build and run

With Docker (recommended, from the repository root):

```bash
docker compose up --build    # → http://localhost:8000
```

Without Docker, with [uv](https://docs.astral.sh/uv/) and Node.js 22.12 or later:

```bash
cd app/web
npm ci && npm run build      # React UI → ../src/drawing_demo/static/ (type check included)
cd ..
uv sync --locked
uv run pytest                # sample tests are skipped if the sample drawings are missing
uv run drawing-demo          # → http://127.0.0.1:8000
```

The API and its tests work also without the UI build. Then only the UI is missing.
For UI development: `uv run drawing-demo` in one terminal, `cd web && npm run dev` in a second terminal
(Vite with hot reload, sends `/api` to port 8000).

The app does not need an API key, a login, or a network connection at runtime.

## User interface

A light dashboard in an app window ([ADR 0008](../docs/adr/0008-demo-ui-light-dashboard.md)) with a guided sequence for the pitch
([ADR 0007](../docs/adr/0007-demo-ui-guided-sequence-and-batch-upload.md)):
**1 Drawing → 2 Recognized → 3 Review → 4 3D model**. The UI is React + TypeScript
([ADR 0010](../docs/adr/0010-demo-ui-in-react-with-3d-viewer.md)).
The UI text is German, because the pitch audience is German.

- **Sidebar:** opens the overview and each uploaded drawing.
- **Overview page** (start page): tiles for the full batch (*drawings*, *explained* as number or gauge, *texts read*,
  *to review*) and a table with one row for each PDF (status, explained, views, texts, to review, duration).
  The table updates while the PDFs are read. Click a row to open the drawing.
- **Drawing page:** the sheet with the tabs of the sequence, and the review list on the right. The header shows the key numbers.
  - **1 Drawing:** the original sheet.
  - **2 Recognized:** the sheet in light gray, with all strokes as SVG in the class colors (the same as the extractor overlay PNG).
    Recognized views show as numbered frames (3D image marked). Read texts show as boxes (text on hover).
    You can show and hide each class. Hatching is off at the start.
  - **3 Review:** locations that a person must examine: unclear strokes (grouped by position),
    characters that were not read with certainty (`?`), missing views. Click an item to zoom to the location.
    In step 3, the first item is selected.
  - **4 3D model:** drag a STEP file from the pipeline to the area, or click it. The server changes it to GLB,
    the browser shows it in 3D (drag turns, wheel zooms, right drag moves). Each drawing keeps its model.
- **Batch upload:** select or drag several PDFs at once, also later. The browser sends them to `/api/extract`,
  with a maximum of 2 at the same time. Each PDF shows *waiting / reading / done / n to review / error*.
- **Toasts:** each drawing shows a short message when it is read, with the duration and the number of open locations.

The mouse wheel zooms, drag moves the sheet, double-click shows the full sheet.
The font (Plus Jakarta Sans) is in `web/src/assets/` (SIL OFL 1.1, license text in `web/public/fonts/`). The app does not use a CDN.

## Demo drawing with unclear locations

The 9 samples have no open locations. To show "marked, not guessed", `scripts/make_demo_drawing.py` makes a copy of
Flansch with three defects. The extractor gives exactly three review flags for this drawing:

```bash
uv run python scripts/make_demo_drawing.py ../resources/Drawing2CAD/Flansch/Flansch_dwg.pdf ../output/demo/Flansch-Demo_dwg.pdf
```

The result goes to the ignored `output/` directory.

## API

| Method | Path | Response |
|---|---|---|
| `GET` | `/api/health` | `{"status": "ok", "extractor_schema": 2}` |
| `POST` | `/api/extract` (multipart, field `file`, max. 20 MB) | `drawing` (extractor JSON), `page_png` (data URI), `page_px_per_mm`, `review` (flags) |
| `POST` | `/api/model` (multipart, field `file`, STEP, max. 50 MB) | GLB (`model/gltf-binary`), meshed with OpenCASCADE (`cascadio`) |

Errors: 413 too large, 415 not a PDF or not a STEP file, 422 drawing or STEP cannot be read (the extractor is made for the BCT template).

## Structure

- `src/drawing_demo/api.py`: FastAPI. Processes the PDF in a temporary directory, changes STEP to GLB, and serves the built UI.
- `src/drawing_demo/review.py`: review flags from the extractor JSON.
- `web/`: React UI (Vite, TypeScript). `src/App.tsx` (pages and steps), `src/components/` (sidebar, overview,
  sheet viewer, review list, 3D viewer), `src/lib/` (API types, upload queue, geometry).
- `src/drawing_demo/static/`: build output of `web/`, not in Git.
- `Dockerfile`: two stages (Node builds the UI, Python runs the app). The build context is the repository root,
  because the extractor is a path dependency.

## Status (17.10.2026)

- All 9 samples work through the UI and the API. The result is the same as the extractor CLI (test).
- Clean build in a fresh copy without sample data tested (Docker and uv).
- 3D view of a STEP file in tab 4 (React, ADR 0010). Not included yet: direct connection to the result of the MCP server.
