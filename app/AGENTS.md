# Work instructions for drawing-demo

This app uses the shared `drawing2cad-mcp` PDF service.
See [ADR 0012](../docs/adr/0012-demo-app-as-frontend-and-backend-container.md) for the separate frontend and backend containers.
See [ADR 0013](../docs/adr/0013-vector-analysis-in-mcp.md) for the shared analysis service.
The UI design history is in [ADR 0007](../docs/adr/0007-demo-ui-guided-sequence-and-batch-upload.md),
[ADR 0008](../docs/adr/0008-demo-ui-light-dashboard.md), and [ADR 0010](../docs/adr/0010-demo-ui-in-react-with-3d-viewer.md).

## Rules

- Store uploaded PDFs only through the shared domain service, in the configured data directory (`DRAWING2CAD_DATA_DIR`, a Docker volume) ([ADR 0017](../docs/adr/0017-agent-runner-in-the-web-backend.md)). Do not log customer drawings or commit the data directory.
- Use one `drawing2cad_mcp.server.Application` for each backend process. Call its domain service for sources, analysis, rendering, and artifacts. Do not add geometry analysis, storage, or release rules to the app.
- Compare the source hashes from analysis and rendering. Reject a result if the hashes differ.
- The app can derive review flags from service results. Keep unclear strokes and unrecognized text characters visible.
- Keep the browser response compatible unless you also update its types and consumers.
- Keep two containers: `frontend/` supplies the React UI through nginx; `backend/` supplies the FastAPI API without static files.
- Use root-relative `/api/...` paths in the UI. Do not add a backend URL to the UI code.
- Use React and TypeScript in `frontend/`. Vite builds the UI into ignored `frontend/dist/`.
- Use TanStack Router for views and TanStack Query for all server data ([ADR 0015](../docs/adr/0015-web-ui-on-tanstack-shadcn-with-service-adapter.md)).
- Use shadcn components in `frontend/src/components/ui/` and Tailwind classes. Do not add a second component library.
- Components call the service only through the `WebApi` interface in `frontend/src/lib/webApi.ts`.
  Do not add storage, CAD, drawing, or validation rules to components.
- Mark simulated data as simulated. Fixture results are not acceptance evidence.
- Do not use a CDN, external scripts, or external fonts. The UI must work offline. Install npm packages with exact versions.
- Keep three.js and react-three-fiber in the lazy-loaded `ModelViewer.tsx` module.
- SVG coordinates use sheet millimeters, with the Y axis down. Keep the established UI class colors.
- The backend image includes `drawing2cad-mcp/` and `app/backend/`. The frontend image contains the UI build.
- Do not include input data or local configuration in either image.
- The MCP package is a non-editable path dependency. After an MCP change, run `uv sync --reinstall-package drawing2cad-mcp` in `backend/`.
- After a change, run `uv run pytest` in `backend/`, and `npm test` and `npm run build` in `frontend/`.
- Test both containers with Docker Compose when Docker is available.
- Test PDF upload and the STEP viewer in the browser when browser access is available. Report tests that could not run.

The demo uses the first PDF page and the built-in BCT/NX analysis profile.
This profile does not provide general OCR or a complete dimension interpretation.
Agent runs build models only through the MCP endpoint that the backend mounts at `/mcp` ([ADR 0017](../docs/adr/0017-agent-runner-in-the-web-backend.md)).
The model endpoint is optional runtime configuration (`.env`, never in Git). Tests use a scripted model; do not call a real model in tests.
The web run records in `backend/src/drawing_demo/jobs.py` hold only job state, the agent trace, and the domain part run ID.
