# Work instructions for drawing-demo

Demo app. Decisions: [ADR 0006](../docs/adr/0006-demo-as-one-container-docker-compose.md),
[ADR 0007](../docs/adr/0007-demo-ui-guided-sequence-and-batch-upload.md), [ADR 0008](../docs/adr/0008-demo-ui-light-dashboard.md).

## Rules

- Stateless: keep uploaded PDFs only in a temporary directory during the request. Do not save or log them (customer drawings).
- No geometry logic in the app. The extractor decides what the drawing means. The app only shows the result and derives review flags.
- Frontend without a build chain and without external scripts or fonts. It must work offline and on the jury computer.
- SVG coordinates are the sheet millimeters of the extractor (y down). Class colors are the same as in `extractor/.../render.py`.
- To show or hide SVG elements, use `toggleAttribute("hidden")`, not `.hidden` (SVG elements do not have this property).
- The Docker image contains only `extractor/` and `app/` (`../.dockerignore`). It never contains input data.
- The extractor is installed as a *non-editable* path dependency. After a change in `../extractor`, run
  `uv sync --reinstall-package drawing-extractor` first. If you do not, the app tests use the old copy (Docker always builds from the source).
- After a change: `uv run pytest`, `docker compose up --build`, and upload a sample in the browser.
