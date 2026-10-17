# drawing-demo frontend

React UI of the demo app ([ADR 0010](../../docs/adr/0010-demo-ui-in-react-with-3d-viewer.md),
[ADR 0012](../../docs/adr/0012-demo-app-as-frontend-and-backend-container.md),
[ADR 0015](../../docs/adr/0015-web-ui-on-tanstack-shadcn-with-service-adapter.md)).
In the container, nginx serves the build and sends `/api` to the backend (`../backend`).

## Build and run

With Node.js 22.12 or later:

```bash
cd app/frontend
npm ci
npm test                     # unit tests (vitest)
npm run build                # type check + Vite build → dist/ (not in Git)
npm run dev                  # Vite with hot reload; sends /api to http://127.0.0.1:8000 (start the backend first)
npm run dev:fixture          # simulated service, no backend necessary (see "Service adapters")
```

Install npm packages only with exact versions (`package-lock.json`).
CI (`.github/workflows/frontend.yml`) runs the tests, the build, an offline check of `dist/`, and the image build.

## Stack

- React 19 and TypeScript, built with Vite.
- TanStack Router (code-based routes in `src/router.tsx`) and TanStack Query (all server data, `src/lib/queries.ts`).
- Tailwind CSS 4 and shadcn components in `src/components/ui/` (added with the shadcn CLI, configuration in `components.json`).
- three.js and react-three-fiber only in the lazy-loaded `ModelViewer.tsx`.

The UI includes its font and libraries. It does not use a CDN.

## Service adapters

All components use the `WebApi` interface in `src/lib/webApi.ts`. The Vite mode selects the adapter:

| Vite mode | Adapter | Behavior |
|---|---|---|
| `development`, `production` | `httpApi.ts` | Web backend: stored sources, analysis, agent runs, artifacts, and STEP display. Parameter edits and notes show as unavailable. |
| `fixture` (`npm run dev:fixture`) | `fixtureApi.ts` | Simulated service with synthetic data (`fixtures.ts`). A banner and a "Simuliert" badge mark all results. |

The fixture adapter imitates job phases, revisions, stale artifacts, revision conflicts, and unknown IDs.
An uploaded filename that contains `fail` simulates a failed STEP re-import.
The fixture does not analyze the uploaded PDF, and its results are not acceptance evidence.

`src/lib/contract.ts` holds provisional types for the shared contract of #24.
When #24 publishes its schemas, update these types and the HTTP adapter.

## User interface

A light dashboard that fills the browser window ([ADR 0008](../../docs/adr/0008-demo-ui-light-dashboard.md)).
The UI text is German, because the pitch audience is German.

| Route | View |
|---|---|
| `/` | Overview: tiles for all drawings, a table with one row for each source or upload (upload progress, status, explained share, views, texts, items to review, size). |
| `/sources/$sourceId?step=1…4` | Guided sequence (ADR 0007): **1 Drawing → 2 Recognized → 3 Review → 4 3D model**, the review list, and the CAD runs of the drawing. |
| `/runs/$runId?tab=…` | CAD run: job phases and errors; tabs for parameters and operations, review (release state, assumptions, uncertainty markers, validation), results (downloads and previews), and notes. |

- **Batch upload:** select or drag several PDFs. A maximum of 2 uploads run at the same time. Each upload shows its progress.
- **Parameter edits:** a change sends the expected revision. Results of an older revision show as stale until the service releases new results.
- **Downloads:** only for artifacts of a released run with the current revision.
- **Errors:** failed uploads, unknown IDs, failed jobs, and unavailable capabilities show a message with a recovery action.

The mouse wheel zooms, drag moves the sheet, double-click shows the full sheet.
The font (Plus Jakarta Sans) is in `src/assets/` (SIL OFL 1.1, license text in `public/fonts/`).

## Structure

- `src/main.tsx`, `src/router.tsx`: entry point, routes, application shell.
- `src/pages/`: overview, drawing (source), and run pages.
- `src/components/`: sidebar, sheet viewer, review list, 3D viewer, run panels (`run/`), shadcn components (`ui/`).
- `src/lib/`: service interface and adapters, provisional contract types, queries, upload queue, release presentation, geometry.
- `src/lib/__tests__/`: unit tests.
- `nginx.conf`: serves `dist/`, sends `/api/` to `backend:8000`, uploads up to 50 MB, returns `index.html` for client routes.
- `Dockerfile`: two stages (Node builds the UI, nginx without root serves it on port 8080). The build context is this directory.
