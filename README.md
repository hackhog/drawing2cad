# drawing2cad

Convert technical PDF drawings into an editable part description and validated STEP through one MCP interface.
The M1 Docker image includes PDF tools, build123d, OCP/OpenCascade, and an isolated CAD worker.
The skill uses domain tools and remains independent of the CAD backend.

## M1 Docker start

From the repository root:

```bash
docker compose -f compose.mcp.yaml build
docker compose -f compose.mcp.yaml run --rm -T mcp
```

The second command starts an MCP stdio process.
Connect an MCP client to its stdin/stdout; it is not a browser endpoint.
The container has no network.
It reads permitted sources under `/inputs` and stores generated data under `/data`.

Set `DRAWING2CAD_INPUT_DIR` to the permitted input directory before starting.
The default input mount is `./resources`, read-only.
The named `cad-data` volume preserves output.
M1 uses server-side paths. It does not yet implement the production PDF-upload contract.

Call `drawing2cad_status`, `cad_capabilities`, and `cad_worker_probe` before CAD work.
The worker requires the supported Linux sandbox.
A host without that sandbox cannot silently execute CAD without isolation.
See the [MCP guide](drawing2cad-mcp/README.md) for tools, configuration, and tests.

## Delivery milestones

| Milestone | Deliverables and limits |
|---|---|
| M1 metric prototype | Editable JSON part description, validated STEP candidate, review list, coverage report, manifest, and trace. |
| M2 complete service | PDF uploads, source/artifact IDs, one Python MCP/API application, React/shadcn/TanStack interface, and a dimensioned technical drawing. |
| M3 AP242 | STEP-only construction reconstruction, driving parameter edits through adapters, semantic PMI, and graphical PMI. |

M2 and M3 remain required follow-up milestones.
The JSON description is the editable source for the declarative M1 path.
A free-code fallback also requires its exact recorded inline payload. JSON alone does not replay that construction.
It does not prove editable construction or semantic PMI inside STEP.
The technical drawing and 3D model can be created in either order.
Their final revisions must agree.

[ADR 0014](docs/adr/0014-headless-build123d-metric-prototype.md) defines the backend decision, sandbox boundary, evaluation set, and acceptance criteria.
A server-side geometry pass is separate from independent STEP analysis and an NX opening test.
Missing tests remain `not_tested`.

## Architecture

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/diagrams/drawing2cad-overview.dark.svg">
  <img alt="Drawing2CAD: M1 service and delivery milestones" src="docs/diagrams/drawing2cad-overview.light.svg">
</picture>

[Open the generated browser diagram](docs/diagrams/drawing2cad-overview.html) locally for theme, zoom, and SVG downloads.
Its source is [drawing2cad-overview.json](docs/diagrams/drawing2cad-overview.json).
After a source change, run `npm run build --prefix tools/diagrams`.
CI verifies exact generated output with `npm run check --prefix tools/diagrams`.
The renderer is part of the repository; it needs no machine-local archify installation.

## Existing demo

```bash
docker compose up --build
```

Open `http://localhost:8000`.
The existing demo has separate frontend and backend containers.
It supports temporary PDF analysis and uploaded STEP display.
It does not implement the M2 persistent upload, artifact, or unified application contract.
See [app/README.md](app/README.md).

## Project structure

| Path | Contents |
|---|---|
| [drawing2cad-mcp/](drawing2cad-mcp/README.md) | Python MCP, PDF tools, part service, worker, and tests. |
| [compose.mcp.yaml](compose.mcp.yaml) | M1 hardened Docker service with stdio transport. |
| [Streamable HTTP guide](drawing2cad-mcp/STREAMABLE_HTTP.md) | HTTP transport, authentication, LiteLLM, and deployment limits. |
| [skills/drawing2cad/](skills/drawing2cad/SKILL.md) | Reusable skill and focused references. |
| [app/](app/README.md) | Existing development demo. |
| [docs/adr/](docs/adr/README.md) | Architecture decisions and staged acceptance scope. |
| [docs/diagrams/](docs/diagrams/drawing2cad-overview.json) | Versioned diagram source and generated HTML/SVG. |
| `tools/diagrams/` | Portable diagram generator and parity tests. |
| [litellm-mcp.example.json](drawing2cad-mcp/litellm-mcp.example.json) | Streamable HTTP registration example. |
| [litellm-stdio.example.json](drawing2cad-mcp/litellm-stdio.example.json) | Optional stdio registration example. |
| `resources/` | Original drawings and CAD references; construction roles are assigned per run. |
| `output/` | Ignored generated models, drawings, previews, traces, and reports. |

## Agent workflow

Load the complete [drawing2cad skill](skills/drawing2cad/SKILL.md) in the client.
MCP registration supplies tools; it does not install the skill.
Use the live catalog and capability results before construction.

Inspect the authorized PDF, record dimensions and assumptions, build through the MCP, and validate measured geometry.
Export a temporary STEP candidate and re-import it in a fresh worker.
Keep original resources unchanged.
Do not use a verification STEP as an unreported construction input.

The legacy FreeCAD proxy and inline adapters are deprecated for new production runs.
The current skill does not depend on a FreeCAD GUI or arbitrary inline FreeCAD code.

## Documentation and version control

Use technical English in accordance with ASD-STE100 for project documentation, comments, docstrings, and tool descriptions.
Use the [language guide](skills/drawing2cad/references/documentation-language.md).
Do not claim full conformity without the required review.

Keep source code, tests, dependency files, example configurations, maintained references, and original resources in Git.
Put generated artifacts in ignored output directories.
Do not commit environments, caches, credentials, or machine-specific configuration.
`.gitattributes` preserves original resource and STEP bytes for stable source hashes.
