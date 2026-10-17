# Work instructions for drawing-demo

This app uses the shared `drawing2cad-mcp` PDF service.
See [ADR 0006](../docs/adr/0006-demo-as-one-container-docker-compose.md) and
[ADR 0010](../docs/adr/0010-demo-ui-in-react-with-3d-viewer.md) for the UI design history.

## Rules

- Keep uploaded PDFs and render artifacts in a temporary directory during the request. Do not retain or log customer drawings.
- Use `drawing2cad_mcp.pdf.PdfService` for PDF analysis and page rendering. Do not add geometry analysis to the app.
- Compare the source hashes from analysis and rendering. Reject a result if the hashes differ.
- The app can derive review flags from service results. Keep unclear strokes and unrecognized text characters visible.
- Keep the browser response compatible unless you also update its types and consumers.
- Use React and TypeScript in `web/`. Vite builds the UI into ignored `src/drawing_demo/static/`.
- Do not use a CDN, external scripts, or external fonts. The UI must work offline. Install npm packages with exact versions.
- Keep three.js and react-three-fiber in the lazy-loaded `ModelViewer.tsx` module.
- SVG coordinates use sheet millimeters, with the Y axis down. Keep the established UI class colors.
- The Docker image includes `drawing2cad-mcp/` and `app/`. It must not include input data or local configuration.
- The MCP package is a non-editable path dependency. After an MCP change, run `uv sync --reinstall-package drawing2cad-mcp`.
- After a change, run `uv run pytest` and `npm run build --prefix web`. Also test the container when Docker is available.
- Test PDF upload and the STEP viewer in the browser when browser access is available. Report tests that could not run.

The demo uses the first PDF page and the built-in BCT/NX analysis profile.
This profile does not provide general OCR or a complete dimension interpretation.
The demo is not a headless FreeCAD worker and does not expose the MCP protocol endpoint.
