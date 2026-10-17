# 15. Web UI on TanStack Router, TanStack Query, and shadcn, with a replaceable service adapter

Date: 2026-10-17

## Status

Proposed. Amends [ADR 0010](0010-demo-ui-in-react-with-3d-viewer.md) (UI structure and styling)
and [ADR 0008](0008-demo-ui-light-dashboard.md) (the look stays; the CSS implementation changes).
[ADR 0007](0007-demo-ui-guided-sequence-and-batch-upload.md) and [ADR 0012](0012-demo-app-as-frontend-and-backend-container.md) stay valid.

## Context

The M2 web service requires a browser interface: source management, upload progress, job state,
parameter changes with expected revisions, review data, run notes, and artifact downloads.
It specifies React, shadcn, TanStack Router, and TanStack Query.

The previous UI kept all state in `useState` and had one page with a hand-written page switch.
It had no addressable views, no server-state cache, and no polling for long jobs.

The shared service contract belongs to the M2 MCP services. At the time of this decision, it was not available.
The current backend supplies only `/api/extract` (drawing analysis) and `/api/model` (STEP to GLB for display).

## Decision

- **Routing:** TanStack Router with code-based routes: `/` (overview), `/sources/$sourceId` (guided sequence),
  and `/runs/$runId` (job, parameters, review, results, notes). Search parameters hold the step and the tab.
  Route loaders fill the query cache. A `NOT_FOUND` from the service becomes the not-found view.
- **Server state:** TanStack Query for all service data. Run queries poll only while the job is active.
  Mutations send the expected revision; a `REVISION_CONFLICT` shows a reload action.
- **Styling:** Tailwind CSS 4 with shadcn components that are copied into `src/components/ui/`.
  The theme tokens keep the colors, font, and layout of ADR 0008. The SVG layers of the sheet viewer keep a small CSS block in sheet millimeters.
- **Service adapter:** components use only the `WebApi` interface (`src/lib/webApi.ts`). Two adapters exist:
  - `legacy` (default): the current endpoints. Sources live in browser memory, and the UI reports runs, notes, and downloads as unavailable.
  - `fixture` (`npm run dev:fixture`): a simulated service with synthetic data for UI work before the shared services exist.
    Every run has `simulated: true`, and the UI shows a banner. Simulated results are not acceptance evidence.
- **Provisional types:** `src/lib/contract.ts` holds the frontend view of the contract. When the shared services publish their schemas,
  the types follow the schemas, and a third adapter for the real HTTP API replaces `legacy`.
- **Release presentation:** the service owns the release gate. The UI offers a download only if the run is released and the artifact
  has the current part revision. It shows stale and blocked artifacts as such.
- **Upload:** XMLHttpRequest, because `fetch` does not report upload progress. A maximum of two uploads run at the same time (ADR 0007).
- **Paths:** the API and asset paths are root-relative (`/api/...`, Vite `base: "/"`), so that a reload of a deep route loads the same assets.

## Consequences

**Positive:**
- Each view has an address. A reload or a shared link opens the same run and tab.
- The UI for runs, parameters, review, and notes exists before the shared services. Integration replaces one adapter.
- Unit tests (`npm test`, vitest) cover the fixture behavior that the UI depends on and the HTTP error mapping.

**Negative:**
- More dependencies (TanStack, Radix, Tailwind, lucide). All versions are exact.
- The app cannot run behind a path prefix without a router `basepath` and a Vite `base` change.
- In `legacy` mode, sources do not survive a page reload, because the current backend stores nothing.
- The fixture adapter imitates the contract. It can hide differences from the final shared schemas until integration.
