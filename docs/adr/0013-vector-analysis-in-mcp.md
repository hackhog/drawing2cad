# 13. Keep drawing analysis inside the MCP package

Date: 2026-10-17

## Status

Accepted. Replaces the separate extractor package and its CLI.
Supersedes the packaging and execution decisions in [ADR 0003](0003-vector-extractor-as-fact-base.md) and [ADR 0009](0009-drawing-extract-as-mcp-tool.md).
Updates the module location in [ADR 0004](0004-text-by-glyph-templates.md) and the demo dependency in [ADR 0006](0006-demo-as-one-container-docker-compose.md).
Amends the backend dependency in [ADR 0012](0012-demo-app-as-frontend-and-backend-container.md). The two-container design remains unchanged.
Their original observations remain historical evidence. They are not new test results.

The later [ADR 0014](0014-headless-build123d-metric-prototype.md) replaces the drawing-first order and selects the M1 CAD backend.
The extraction observations below remain historical evidence.
ADR 0014 also removes the FreeCAD proxy. Its tools and configuration described below are no longer available.

## Context

The MCP already exposed the former extractor through `drawing_extract`.
However, installation required a second package, and the demo called that package directly.
The two entry points had different path checks, source metadata, and rendering code.

The required output sequence is a dimensioned technical drawing, an editable 3D model, and then STEP AP242.
Only analysis that supports these outputs is necessary.
Colored overlay exports and complete JSON-file exports are outside this change.

## Feature comparison

| Capability | MCP before consolidation | Former standalone extractor | Decision |
|---|---|---|---|
| PDF metadata and native text | Available, with source hash | No dedicated interface | Keep MCP tools |
| Page images and detail images | Poppler, bounded PNG previews, artifact hashes | CLI created a colored page overlay | Keep MCP image tools; do not migrate the overlay |
| Lines, arcs, circles, and stroke classes | Optional `drawing_extract` dependency | Built-in analysis library | Move the library into the MCP package |
| Views and text from glyph outlines | Available through the optional package | Deterministic grouping and glyph templates | Retain through `drawing_extract` |
| Compact results and class filters | `include_strokes` and `stroke_kinds` | CLI always wrote the full result | Keep the existing MCP parameters |
| Full JSON-file export and batch CLI | No export tool | One JSON file per input | Remove the CLI; do not add an export tool |
| Source identity and permitted roots | Bounded snapshot, SHA-256, resolved path checks | Direct filesystem reads | Use the MCP PDF service for both clients |
| Analysis isolation and timeout | Worker thread; no analysis timeout | Direct process execution | Use a separate request process with a timeout |
| FreeCAD tools and MCP transport | FreeCAD proxy, stdio, Streamable HTTP | None | Keep the MCP interface |
| Drawing authoring and semantic AP242 | Require separate verified CAD adapters | Not supplied | Keep the drawing-first workflow and adapter tests |

## Decision

1. Keep analysis code in `drawing2cad_mcp.vector`.
2. Include PyMuPDF 1.28.2 as a required dependency of MCP version 0.3.0.
3. Keep Python 3.11 as the minimum supported version.
4. Keep the existing `drawing_extract(path, include_strokes=false, stroke_kinds=null)` interface.
5. Report built-in analysis status through `drawing2cad_status.drawing_analysis`.
6. Remove the standalone package, CLI, installation instructions, and template-building scripts.
7. Keep the analysis regression tests with the MCP tests. Keep their source evidence outside the skill package.
8. Use `PdfService` from the demo backend API. Do not register a second MCP server.

The MCP still supplies six local tools and dynamically discovered `freecad_*` tools.
It supplies no new overlay or JSON-file export tool.
The demo retains its browser display and review flags. It does not host the MCP endpoint.

Each analysis request runs the versioned worker module in a separate process.
This follows the [PyMuPDF process guidance](https://pymupdf.readthedocs.io/en/latest/recipes-multiprocessing.html).
PyMuPDF does not support simultaneous use from multiple threads in one process.
The service passes a source snapshot to the worker and applies `pdf.timeout_seconds`.
Temporary input and response files are implementation data, not delivered artifacts.
This worker contains versioned server code. It creates no executable helper file for a model run.

## Limits and verification

The current profile covers page 1 of BCT A3 landscape drawings from Siemens NX.
The service rejects unsupported page transforms before vector analysis.
Other drawing layouts can still produce incorrect classifications. A matching sheet size is not sufficient evidence of compatibility.

Sheet coordinates describe the drawing, not the part. They do not apply the drawing scale.
Glyph text can contain `?` or incorrect known characters.
The frame and title block are excluded. Read their scale and manufacturing data from verified image observations.
Use the existing page and crop tools to examine critical dimensions and all unclear details.

The analysis cannot prove dimension associations, editable CAD construction, semantic PMI, or STEP-only reconstruction.
Create and review the controlling dimensioned drawing before the 3D build.
Test each CAD and AP242 capability separately through a verified adapter.

Tests must cover source identity, compact and filtered results, supported samples, rejected transforms, timeout behavior, and process isolation.
The demo tests must verify that it calls the same PDF service and preserves its browser response.
Run reports belong in ignored output directories. Do not treat this decision as a test report.

## Consequences

One package supplies PDF preparation and vector analysis to agents and the demo API.
Clients retain the existing MCP extraction call and the same transport configuration.
Each analysis call has process-start overhead. The isolation avoids shared PyMuPDF state between concurrent requests.
All installations now include PyMuPDF, including deployments that only need native text or FreeCAD tools.
No additional capability for headless CAD operation follows from this consolidation.
