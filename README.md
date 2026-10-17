# drawing2cad

This project supplies tools and a reproducible agent workflow to reconstruct CAD models from technical PDF drawings.
The Python MCP prepares PDFs and gives access to the existing FreeCAD MCP through one interface.
The skill specifies model construction, source evidence, unresolved dimensions, and tests of CAD and STEP outputs.

## Quick start: demo UI

```bash
docker compose up --build    # → http://localhost:8000, then upload drawing PDFs from resources/Drawing2CAD/
```

This needs only Docker. It does not need a key, a login, or a network connection at runtime.
Details: [app/README.md](app/README.md).

## Project structure

| Path | Contents |
|---|---|
| [drawing2cad-mcp/](drawing2cad-mcp/README.md) | Python server, installation, configuration, and tests |
| [skills/drawing2cad/](skills/drawing2cad/SKILL.md) | Skill, workflow, adapter instructions, and references |
| [extractor/](extractor/README.md) | Deterministic vector extractor: PDF → classified strokes, views, and read texts (JSON) |
| [app/](app/README.md) | Demo UI (FastAPI + React): upload PDFs, guided review of the extractor result, 3D model view |
| [docs/adr/](docs/adr/README.md) | Architecture decision records for extractor and demo UI |
| `compose.yaml` | Local start of the demo UI with Docker Compose |
| `resources/` | Original drawings and CAD references for verification |
| `output/` | Locally generated models, drawings, preview images, and test reports |
| `tmp/` | Local temporary data |

## Start

Use the [MCP documentation](drawing2cad-mcp/README.md#installation) for Python, Poppler, FreeCAD, and test commands.
Copy [drawing2cad-mcp.example.toml](drawing2cad-mcp/drawing2cad-mcp.example.toml) to `drawing2cad-mcp.local.toml`.
Set the configuration values for your computer.

The MCP supplies PDF metadata, text, page images, detail images, and FreeCAD tools.
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
