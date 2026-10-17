# drawing2cad

This project supplies tools and a reproducible agent workflow to reconstruct CAD models from technical PDF drawings.
The Python MCP prepares PDFs, analyzes drawing vectors, and gives access to the existing FreeCAD MCP through one interface.
Clients can use Streamable HTTP at `/mcp` or the existing stdio transport.
The skill specifies model construction, source evidence, unresolved dimensions, and tests of CAD and STEP outputs.

## Quick start: demo UI

```bash
docker compose up --build    # → http://localhost:8000, then upload drawing PDFs from resources/Drawing2CAD/
```

This needs only Docker. It does not need a key, a login, or a network connection at runtime.
Details: [app/README.md](app/README.md).

## Architecture

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/diagrams/drawing2cad-overview.dark.svg">
  <img alt="Drawing2CAD: system overview" src="docs/diagrams/drawing2cad-overview.light.svg">
</picture>

Interactive version: [`docs/diagrams/drawing2cad-overview.html`](docs/diagrams/drawing2cad-overview.html)
(open it locally in a browser). The image is built from `docs/diagrams/drawing2cad-overview.json`, never by hand.
After a change, run `npm run build --prefix tools/diagrams`. The CI checks the result
([ADR 0011](docs/adr/0011-diagrams-in-readme-checked-by-ci.md)).

## Project structure

| Path | Contents |
|---|---|
| [drawing2cad-mcp/](drawing2cad-mcp/README.md) | Python server, installation, configuration, and tests |
| [Streamable HTTP guide](drawing2cad-mcp/STREAMABLE_HTTP.md) | Installation, authentication, LiteLLM, network setup, and troubleshooting |
| [skills/drawing2cad/](skills/drawing2cad/SKILL.md) | Skill, workflow, adapter instructions, and references |
| [Vector analysis](drawing2cad-mcp/README.md#vector-analysis) | Built-in MCP analysis: classified strokes, views, and text from glyph outlines |
| [app/](app/README.md) | Demo UI: upload PDFs, review MCP analysis, and view a 3D model. Separate [frontend](app/frontend/README.md) and [backend](app/backend/README.md) containers |
| [docs/adr/](docs/adr/README.md) | Architecture decisions, including the MCP and former extractor comparison |
| [docs/diagrams/](docs/diagrams/drawing2cad-overview.json) | Architecture diagram: JSON source, interactive HTML, SVG for this README |
| `tools/diagrams/` | Builds and checks the diagrams (archify, Playwright), not part of the app build |
| `compose.yaml` | Local start of the demo UI with Docker Compose |
| [litellm-mcp.example.json](drawing2cad-mcp/litellm-mcp.example.json) | Streamable HTTP registration body for the LiteLLM management API |
| [litellm-stdio.example.json](drawing2cad-mcp/litellm-stdio.example.json) | Optional stdio registration example for the LiteLLM Admin UI |
| `resources/` | Original drawings and CAD references for verification |
| `output/` | Locally generated models, drawings, preview images, and test reports |
| `tmp/` | Local temporary data |

## Start

Use the [MCP documentation](drawing2cad-mcp/README.md#installation) for Python, Poppler, FreeCAD, and test commands.
Use the [Streamable HTTP guide](drawing2cad-mcp/STREAMABLE_HTTP.md) for the complete HTTP setup procedure.
Copy [drawing2cad-mcp.example.toml](drawing2cad-mcp/drawing2cad-mcp.example.toml) to `drawing2cad-mcp.local.toml`.
Set the configuration values for your computer.

For LiteLLM, use [litellm-mcp.example.json](drawing2cad-mcp/litellm-mcp.example.json).
Follow the [registration procedure](drawing2cad-mcp/README.md#register-with-litellm) to start the HTTP server and register its URL.
Existing stdio clients can keep their configuration. The default transport remains `stdio`.
Load the complete [drawing2cad skill](skills/drawing2cad/SKILL.md), including its references, in the agent that uses the MCP.
MCP registration supplies tools. The agent must also load the skill instructions.

The MCP supplies PDF metadata, text, vector analysis, page images, detail images, and FreeCAD tools.
The demo API uses the same Python PDF service. There is no separate extractor package or CLI.
See [ADR 0013](docs/adr/0013-vector-analysis-in-mcp.md) for the feature comparison and migration decision.
The HTTP transport does not supply a headless CAD worker, web interface, or download service.
Test CAD history, semantic PMI, and exports without a GUI for each adapter and tool version.
A successful STEP export does not prove these properties.

The [work instructions](AGENTS.md) specify this sequence: **dimensioned technical drawing → verified parametric 3D model → STEP**.
Record the drawing revision, model comparison, and export separately.
The [skill](skills/drawing2cad/references/drawing-first.md) specifies the tests for new designs, changes, and imports from STEP alone.

## Documentation

Write all project documentation in technical English in accordance with ASD-STE100.
Use the [documentation language guide](skills/drawing2cad/references/documentation-language.md) for project terms and the review procedure.
Keep original source records and historical test evidence unchanged.

## Version control

Keep source code, tests, dependency files, example configurations, maintained skill references, and original resources in the repository.
The 36 existing resource files have a total size of approximately 13 MiB. The repository does not use Git LFS.

Put generated models, drawings, images, and run reports in `output/`, `outputs/`, `out/`, `artifacts/`, or `tmp/`.
Git ignores these directories at all levels. The files stay available locally.
Git also ignores environments, caches, FreeCAD backups, and machine-specific configurations.
Maintained skill references and regression inputs are part of the source project.

`.gitattributes` sets LF line endings for text files. It preserves the original bytes of resources and STEP files.
This preserves source hashes when you clone the repository.
Git treats PDF, image, and native CAD files as binary files.
The ignore rules do not exclude all CAD models and drawings outside generated output directories.
