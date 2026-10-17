# 10. Demo UI in React with a 3D viewer, STEP to GLB on the server

Date: 2026-10-17

## Status

Proposed. Amends ADR 0008 (tab 4 "3D model" is now active). Replaces the rule "frontend without a build chain" in `app/AGENTS.md`.
ADR 0006 (one container) stays valid.
Amended by [ADR 0012](0012-demo-app-as-frontend-and-backend-container.md): the UI is now in `app/frontend/` and has its own container.

## Context

The UI of ADR 0007/0008 was plain HTML/CSS/JavaScript (approximately 920 lines) without a build chain.
Two new requirements change this:

- Tab 4 "3D model" must show a real 3D model. A 3D viewer with three.js is much easier to write and maintain
  with React and react-three-fiber than with plain JavaScript.
- More team members work on the UI at the same time and know React. Components in separate files give fewer merge conflicts
  than one `app.js`.

The 3D model comes from the pipeline (`drawing2cad-mcp` with FreeCAD) as a STEP file. Browsers cannot show STEP directly.

Compared options for the 3D model:

- **A:** the server changes STEP to GLB. The browser shows only GLB.
- **B:** the browser reads STEP with OpenCASCADE as WebAssembly (`occt-import-js`).
- **C:** only a placeholder viewer now, the model connection later.

## Decision

- The UI is a React + TypeScript project in `app/web/`, built with Vite. All versions are exact (`package-lock.json`).
  The build output goes to `app/src/drawing_demo/static/`. FastAPI serves it as before. The build output is not in Git.
- The Docker image builds the UI in a first stage (`node:24.21.0-slim`). The final image has no Node.
  It is still one container (ADR 0006).
- Function and look of the UI do not change (ADR 0007/0008). The CSS is the same. The page and step attributes are on
  `<div class="shell">` instead of `<body>`.
- Option A for the 3D model: `POST /api/model` takes a STEP file and gives GLB (`cascadio`, OpenCASCADE, approximately 0.03 s
  for each sample). The server does not keep the file. Tab 4 accepts a STEP file by drag and drop or file selection
  and shows it with react-three-fiber (orbit, automatic fit, gray body with CAD edges).
- three.js loads only when tab 4 opens (separate chunk, `React.lazy`).

## Consequences

**Positive:**
- The 3D viewer is a small component (`ModelViewer.tsx`). The UI is in components with types for the API.
- `docker compose up --build` stays the only command to build and start. It needs no key and no account.
- The browser gets only GLB. Thus, the frontend does not need a large WebAssembly file.
- The API tests do not need Node. Without a UI build, the API starts and only the UI is missing (`check_dir=False`).

**Negative:**
- A second tool chain (Node/npm) for local UI work. Local start without Docker: `cd app/web && npm ci && npm run build`,
  then `uv run drawing-demo`. For development: `npm run dev` (Vite with proxy for `/api` to port 8000).
- More dependencies (React, three.js, `cascadio`, `numpy`). The image is larger.
- Tab 4 shows only a STEP file that a person gives. A direct connection to the pipeline result comes later.
- The ground-truth STEP files in `resources/` are only test data for the conversion. They are never an input of the pipeline.
