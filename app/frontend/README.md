# drawing-demo frontend

React UI of the demo app ([ADR 0010](../../docs/adr/0010-demo-ui-in-react-with-3d-viewer.md),
[ADR 0012](../../docs/adr/0012-demo-app-as-frontend-and-backend-container.md)).
In the container, nginx serves the build and sends `/api` to the backend (`../backend`).

## Build and run

With Node.js 22.12 or later:

```bash
cd app/frontend
npm ci
npm run build                # type check + Vite build → dist/ (not in Git)
npm run dev                  # Vite with hot reload; sends /api to http://127.0.0.1:8000 (start the backend first)
```

Install npm packages only with exact versions (`package-lock.json`).

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
The font (Plus Jakarta Sans) is in `src/assets/` (SIL OFL 1.1, license text in `public/fonts/`). The app does not use a CDN.

## Structure

- `src/App.tsx`: pages and steps.
- `src/components/`: sidebar, overview, sheet viewer, review list, 3D viewer (`ModelViewer.tsx`, lazy-loaded with three.js).
- `src/lib/`: API types and calls (`api.ts`), upload queue, geometry.
- `nginx.conf`: serves `dist/`, sends `/api/` to `backend:8000`, uploads up to 50 MB.
- `Dockerfile`: two stages (Node builds the UI, nginx without root serves it on port 8080). The build context is this directory.
