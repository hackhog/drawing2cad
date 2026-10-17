# drawing-demo

Demo app for Drawing2CAD: upload drawing PDFs, look at the result of the extractor (`../extractor`) as an interactive drawing,
examine the review flags, and look at the 3D model.
It has two parts, each with its own container ([ADR 0012](../docs/adr/0012-demo-app-as-frontend-and-backend-container.md)):

| Part | Contents | Container |
|---|---|---|
| [frontend/](frontend/README.md) | React + TypeScript UI (Vite), the guided sequence and the 3D viewer | nginx: serves the UI on port 8000 of the host, sends `/api` to the backend |
| [backend/](backend/README.md) | FastAPI: `/api/extract` (extractor + review flags), `/api/model` (STEP → GLB) | Python, only in the internal Compose network |

```
browser ──► frontend (nginx :8080, published as 127.0.0.1:8000) ──/api──► backend (FastAPI :8000) ──► extractor
```

## Build and run

With Docker (recommended, from the repository root):

```bash
docker compose up --build    # → http://localhost:8000
```

If a Compose project with the old single service `app` still runs, add `--remove-orphans` once.

Without Docker, with [uv](https://docs.astral.sh/uv/) and Node.js 22.12 or later, in two terminals:

```bash
cd app/backend && uv sync --locked && uv run drawing-demo        # API on http://127.0.0.1:8000
cd app/frontend && npm ci && npm run dev                          # UI on http://localhost:5173, /api goes to port 8000
```

Tests: `cd app/backend && uv run pytest` (sample tests are skipped if the sample drawings are missing),
`cd app/frontend && npm run build` (includes the type check).

The app does not need an API key, a login, or a network connection at runtime.

## Status (17.10.2026)

- All 9 samples work through the UI and the API. The result is the same as the extractor CLI (test).
- Clean build in a fresh copy without sample data tested (Docker and uv).
- 3D view of a STEP file in tab 4 (React, ADR 0010). Not included yet: direct connection to the result of the MCP server.
- Frontend and backend in separate containers (ADR 0012), tested with Docker Compose.
