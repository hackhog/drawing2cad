# Work instructions for drawing-demo

Demo app. Decisions: [ADR 0006](../docs/adr/0006-demo-as-one-container-docker-compose.md),
[ADR 0007](../docs/adr/0007-demo-ui-guided-sequence-and-batch-upload.md), [ADR 0008](../docs/adr/0008-demo-ui-light-dashboard.md),
[ADR 0010](../docs/adr/0010-demo-ui-in-react-with-3d-viewer.md), [ADR 0012](../docs/adr/0012-demo-app-as-frontend-and-backend-container.md).

## Rules

- Stateless: keep uploaded PDFs only in a temporary directory during the request. Do not save or log them (customer drawings).
- No geometry logic in the app. The extractor decides what the drawing means. The app only shows the result and derives review flags.
- Two parts, two containers: `frontend/` (React, served by nginx) and `backend/` (FastAPI, API only, no static files).
  The frontend talks to the backend only through relative `/api/...` paths. Do not add a backend URL to the UI code.
- Frontend: React + TypeScript in `frontend/`, built with Vite into `frontend/dist/` (not in Git). No CDN, no external
  scripts or fonts. It must work offline and on the jury computer. Install npm packages only with exact versions.
- three.js and react-three-fiber only in the lazy-loaded `ModelViewer.tsx`, so that the overview stays small.
- SVG coordinates are the sheet millimeters of the extractor (y down). Class colors are the same as in `extractor/.../render.py`.
- The backend image contains only `extractor/` and `app/backend/` (`../.dockerignore`). The frontend image contains only
  the UI build. No image contains input data.
- The extractor is installed in `backend/` as a *non-editable* path dependency. After a change in `../extractor`, run
  `uv sync --reinstall-package drawing-extractor` first. If you do not, the app tests use the old copy (Docker always builds from the source).
- After a change: `cd backend && uv run pytest`, `cd frontend && npm run build` (includes the type check), `docker compose up --build`,
  and upload a sample in the browser (also open tab 4 with a STEP file).
