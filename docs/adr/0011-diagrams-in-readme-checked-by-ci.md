# 11. Architecture diagram from a versioned source, as an image in the README, checked by CI

Date: 2026-10-17

## Status

Proposed. Uses the procedure of the Fleet Monitor project (its ADR 0028).

## Context

The README had no architecture image. Readers (team, jury, and the AI that evaluates code and architecture) had to
find the relation between demo app, extractor, MCP server, FreeCAD and STEP in several READMEs.

archify makes interactive HTML diagrams from a typed JSON file, with source links to file and line for each component.
GitHub does not show HTML. archify is a locally installed skill, not an npm package. Thus, a CI runner cannot make
the HTML from the JSON. The HTML has a built-in export (SVG light and dark) that runs headless and gives
byte-identical files.

If the HTML or SVG is changed by hand, it does not agree with the source any more. Nobody sees this without a check.

## Decision

1. **Versioned source:** `docs/diagrams/<name>.json` is the only source. Do not edit the HTML or the SVGs by hand.
2. **Local build:** `npm run diagrams --prefix tools/diagrams`. For each JSON: `archify finalize` gives the HTML,
   then the export dialog of the viewer gives the light and dark SVG (Playwright with the local Google Chrome),
   then `docs/diagrams/diagrams.lock.json` records the SHA-256 of JSON, HTML and SVGs.
   archify evidence goes to `.archify/`. Delivery receipts with local paths (`*.delivery*.json`) are ignored by Git.
3. **README** shows `drawing2cad-overview` with `<picture>` (light or dark, as the GitHub theme) and links the HTML.
4. **CI only checks** (`.github/workflows/diagrams.yml`, only for changes in `docs/diagrams/` or `tools/diagrams/`):
   JSON and HTML must agree with the lock file, and the SVG export of the committed HTML must be identical
   to the committed SVGs. If not, the job fails with the command to run.
5. Rule in `AGENTS.md`: if the architecture changes (new component, new interface), update the overview in the same PR.

## Consequences

**Positive:**
- The README shows a current architecture image. Each component in the HTML links to its source lines.
- A diagram that is old or changed by hand cannot go to `main` without notice.
- `tools/diagrams/` is a separate package. The app build (`docker compose up --build`) does not use it.

**Negative:**
- The CI does not check that the content is complete. Only a person sees that a new component is missing.
  For this, the rule in `AGENTS.md`.
- To build diagrams, you need the archify skill (path with `ARCHIFY_BIN`) and Google Chrome.
  Team members without archify can change the JSON, but the CI then asks for a build by someone with archify.
- An archify update can change HTML and SVG without a change of the source. Then run the build once and commit.
- The source links point to a fixed commit (`meta.repository.revision`). After large code changes, update the revision
  and the line numbers.
