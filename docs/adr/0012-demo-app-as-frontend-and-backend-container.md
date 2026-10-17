# 12. Demo app as a frontend container and a backend container

Date: 2026-10-17

## Status

Proposed. Supersedes ADR 0006 in the part "one container". Amends ADR 0010 (the UI build no longer goes into the Python package).
The other parts of ADR 0006 stay valid: local start with Docker Compose, no Kubernetes, Azure optional and never necessary.

## Context

ADR 0010 put the React UI in `app/web/`. Vite wrote the build output into the Python package (`app/src/drawing_demo/static/`),
and FastAPI served it. One Dockerfile built Node and Python into one image.

Thus, frontend and backend were in one directory and depended on each other:

- The Python package contained the UI build. The backend Dockerfile needed Node.
- The API tests had a test that passed or was skipped, dependent on a local UI build.
- More team members work on the UI and on the API at the same time. A clear limit between the two parts makes the
  responsibilities and the review of a change easier.

Compared options:

- **A:** separate directories, but one image. FastAPI continues to serve the UI.
- **B:** separate directories and two containers. nginx serves the UI and sends `/api` to the backend.

## Decision

Option B.

- `app/frontend/`: React + TypeScript (Vite). The build output is `dist/` (not in Git). The image builds the UI
  with `node:24.21.0-slim` and serves it with `nginxinc/nginx-unprivileged:1.30.6-alpine` on port 8080 (no root).
  `nginx.conf` sends `/api/` to `backend:8000` and permits uploads up to 50 MB (the STEP limit of the API).
  nginx finds the backend at run time through the Docker DNS. Thus, a new start of the backend does not need a new start of the frontend.
- `app/backend/`: FastAPI with the extractor. It is only the API. It does not serve static files.
  The image has no Node. The build context stays the repository root, because the extractor is a path dependency.
- `compose.yaml` has two services. Only `frontend` has a published port (`127.0.0.1:8000`). `backend` is only in the
  internal Compose network. `frontend` starts after the health check of `backend` is good. Both containers are read-only with a `tmpfs` on `/tmp`.
- The UI calls the API with relative paths. Thus, the UI code does not change. For development, `npm run dev` sends `/api`
  to `uv run drawing-demo` as before.

## Consequences

**Positive:**
- Each part has its own directory, Dockerfile, README, and dependencies. A change in the UI does not change the Python package.
- The backend image is smaller and has no Node build stage. The frontend image has no Python.
- The API is not open to the host. Only nginx is accessible.
- `docker compose up --build` stays the only command to build and start. The URL stays `http://localhost:8000`.

**Negative:**
- One more container and one more configuration file (`nginx.conf`).
- Without Docker, two processes are necessary for the full UI (`uv run drawing-demo` and `npm run dev`).
- A Compose project that ran with the old service `app` must be started once with `--remove-orphans`.

**Neutral:**
- The API, the UI function, and the look do not change (ADR 0007, 0008, 0010).
- For Azure (ADR 0006, optional), the two services map to two Container Apps or to one Container App with two containers.
