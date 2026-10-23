# drawing2cad

Convert uploaded technical PDFs into an editable part description, a dimensioned DXF drawing with a PDF copy, and validated STEP through one MCP interface.
The Docker image includes PDF tools, build123d, OCP/OpenCascade, STEPcode, the drawing adapter, and isolated workers.
The skill uses domain tools and remains independent of the CAD backend.

## Docker start

The `deployment/` directory has two Compose files with the same services ([ADR 0027](docs/adr/0027-container-images-on-ghcr-for-version-tags.md)):

| File | Image source |
|---|---|
| [deployment/compose.yaml](deployment/compose.yaml) | Published images on `ghcr.io/hackhog`. Each version tag publishes them. |
| [deployment/compose.local.yaml](deployment/compose.local.yaml) | Local build from the current source, with local image tags. |

Set `DRAWING2CAD_VERSION` to a version tag, for example `v1.3`, to use the images of that version. Without it, Compose uses `latest`.
Run `pull` with the same file to get a newer `latest` image.
To build from the current source, use `deployment/compose.local.yaml` in the commands below and add `--build` to `up`.
Run all commands from the repository root.
Copy `.env.example` to `.env` before these commands, then set the required values.
The `--env-file .env` option supplies root-file values for Compose interpolation, including image versions and tokens.
The service `env_file` alone does not supply interpolation values. Shell values have priority.
If no `.env` exists, omit `--env-file .env`. The web app can start without an agent endpoint.

### MCP

```bash
docker compose --env-file .env -f deployment/compose.yaml run --rm -T mcp
```

This command starts an MCP stdio process.
Connect an MCP client to its stdin/stdout; it is not a browser endpoint.
The container has no network.
Send PDF bytes through the upload tools. Clients use source, run, job, and artifact IDs.
No source-directory mount or client access to server paths is required.
The named `cad-data` volume preserves uploaded sources, revisions, jobs, notes, and immutable artifacts under `/data`.

For Streamable HTTP, supply `DRAWING2CAD_HTTP_TOKEN` through your secret mechanism, then run:

```bash
docker compose --env-file .env -f deployment/compose.yaml --profile mcp-http up -d mcp-http
```

Connect to `http://127.0.0.1:8765/mcp` with the same bearer token.
The HTTP service exposes only the host loopback interface. It does not include the web interface.

Call `drawing2cad_status`, `cad_capabilities`, and `cad_worker_probe` before CAD work.
The worker requires the supported Linux sandbox.
A host without that sandbox cannot silently execute CAD without isolation.
See the [MCP guide](drawing2cad-mcp/README.md) for tools, configuration, and tests.

## Web app with agent runs

```bash
docker compose --env-file .env -f deployment/compose.yaml up -d                  # published images
docker compose --env-file .env -f deployment/compose.local.yaml up --build -d    # local build
```

Open `http://localhost:8000`.
Upload drawing PDFs, review the analysis, and start a run.
A run lets an agent build the model only through the `drawing2cad-mcp` endpoint of the backend; step 4 shows the released STEP in 3D
([ADR 0018](docs/adr/0018-agent-runner-in-the-web-backend.md)).
If a run ends without release, the page shows its last available model and drawing as not released.
The files retain their build or drawing revision. The page shows the failed phase, reason, and blocking findings.
Runs need an OpenAI-compatible model endpoint.
Copy `.env.example` to `.env` and set the required values.
Run `docker compose --env-file .env -f deployment/compose.yaml up -d`.
Without `.env`, omit `--env-file .env`; the app starts and shows runs as unavailable. See the [app guide](app/README.md).
To keep the key out of `.env`, leave `DRAWING2CAD_AGENT_API_KEY` empty there and pass it from the shell, for example from the macOS Keychain:
`DRAWING2CAD_AGENT_API_KEY=$(security find-generic-password -a <account> -s <service> -w) docker compose --env-file .env -f deployment/compose.yaml up -d`.

## Delivery scopes

| Scope | Deliverables and limits |
|---|---|
| Complete service | Editable JSON description, validated STEP, dimensioned DXF/PDF, accepted verification and review, and a current STEP/PDF pair. Use domain `delivery: "complete_service"`. |
| Explicit STEP-only request | Validated STEP, editable JSON description, review list, coverage, manifest, and trace. No complete-service drawing claim. The local-path profile supports this reduced scope. |
| Optional web clients | HTTP API and React/shadcn/TanStack interface using the shared service. The MCP server works without them. |
| Optional AP242 and PMI | STEP-only construction reconstruction, driving parameter edits through adapters, semantic PMI, and graphical PMI. Each claim requires separate evidence. |

Complete M3 acceptance remains follow-up work. The web app (M2 Web) starts agent builds through the MCP; see "Web app with agent runs".
The initial [AP242 adapter](docs/adr/0017-ap242-application-construction-and-pmi.md)
adds application-specific construction replay and nominal PMI. AP242 builds require
bounded independent STEPcode analysis. Headless PDF/PNG inspection shows the actual
stored PMI strokes, with annotation-plane detail views. Full conformance and the
remaining PMI scope are not complete. Product input is PDF; external STEP
upload is out of scope. Internal re-import tests verify generated STEP output.
CAD-specific export and native feature adapters are outside this adapter.
The JSON description is the editable source for the declarative construction path.
A free-code fallback also requires its exact recorded inline payload. JSON alone does not replay that construction.
It does not prove editable construction or semantic PMI inside STEP.
The technical drawing and 3D model can be created in either order.
Their final revisions must agree.

[ADR 0014](docs/adr/0014-headless-build123d-metric-prototype.md) defines the backend decision, sandbox boundary, evaluation set, and acceptance criteria.
A server-side geometry pass is separate from independent STEP analysis and an optional opening test in a target CAD system.
Missing tests remain `not_tested`.
[ADR 0016](docs/adr/0016-shared-domain-service-and-drawing-delivery.md) defines the M2 service boundary and drawing limits.
The drawing service derives supported views and sections from the validated model and renders native DXF dimensions and PDF.
Complete-service release requires independent PDF verification, accepted review, and a current pair ([ADR 0034](docs/adr/0034-step-and-drawing-released-as-a-verified-pair.md)).
Independent source review is still required. "Test run results" shows the current results of the sample drawings.

## Test run results

Run on 2026-10-18, commit `7670fa0`, MCP image built from that commit.
Each part ran in a separate agent session (`codex exec`, model gpt-6-luna, reasoning medium) with the skill in this repository, at most 60 MCP tool calls, and only the drawing2cad MCP tools.

| Part | Result | Released STEP SHA-256 | Notes | MCP calls |
|---|---|---|---|---|
| Achse | released | `1103dacfab40a8cb00f766cc8e63dc4b3a70bbbee0269716f04f0fd1d9e5b973` | Build and fresh-worker STEP re-import passed. Drawing status `missing`: the drawing validation returned defects, and no drawing was rendered. | 34 |
| Welle | released | `c04c87e83fdfd312ea84babd07ba5eb9e4667d5b7c064245ca6c46d28405848a` | Build and re-import passed; the bounding box, five shaft diameters, and the R2 radius passed. Drawing status `missing`: the drawing render failed. | 40 |
| Splint | not released | – | Build and re-import passed. The projection check failed and showed that the view is 2:1, although the title block shows 1:1. The calibrated repeat did not run because the client lost the MCP connection. | 36 |
| Grundplatte | not released | – | Build and re-import passed. The model omits perimeter walls, edge notches, draft, and radii. The projection check stopped with `WORKER_TIMEOUT`. | 52 |
| Schnittmenge | not released | – | Build and re-import passed. The model omits the R10 root fillets and two section details. Source coverage is incomplete. | 43 |
| Trägerplatte V2 | not released | – | Build and re-import passed. `export_step` returned `COVERAGE_INCOMPLETE`. The drawing failed. | 44 |

The release requires a passed build, a fresh-worker re-import, and complete source coverage. A part that does not meet these conditions is not released; the tool does not guess missing features.
In the previous run with the same model and prompt (commit `efcd1ec`), Achse, Welle, and Splint were not released.
The drawing deliverable is not complete for any part. Independent STEP conformance and target-CAD opening were `not_tested`.

## Architecture

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/diagrams/drawing2cad-overview.dark.svg">
  <img alt="Drawing2CAD: shared headless service and delivery milestones" src="docs/diagrams/drawing2cad-overview.light.svg">
</picture>

[Open the generated browser diagram](docs/diagrams/drawing2cad-overview.html) locally for theme, zoom, and SVG downloads.
Its source is [drawing2cad-overview.json](docs/diagrams/drawing2cad-overview.json).
After a source change, run `npm run build --prefix tools/diagrams`.
CI verifies exact generated output with `npm run check --prefix tools/diagrams`.
The renderer is part of the repository; it needs no machine-local archify installation.

## Project structure

| Path | Contents |
|---|---|
| [drawing2cad-mcp/](drawing2cad-mcp/README.md) | Python MCP, PDF tools, part service, worker, and tests. |
| [deployment/](deployment/compose.yaml) | Compose files: published images, and a local build from the current source. |
| [Streamable HTTP guide](drawing2cad-mcp/STREAMABLE_HTTP.md) | HTTP transport, authentication, LiteLLM, and deployment limits. |
| [skills/drawing2cad/](skills/drawing2cad/SKILL.md) | Reusable skill and focused references. |
| [app/](app/README.md) | Web app: React frontend and Python backend with agent runs through the MCP. |
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

Upload the authorized PDF, inspect its images, record dimensions and assumptions, build through the MCP, and validate measured geometry.
Create the technical drawing, inspect its PDF, and record a review of its exact revision and source hashes.
Either drawing or model can be created first. The validated model gates the STEP release. The release records the drawing status.
Export a temporary STEP candidate and re-import it in a fresh worker.
Keep original resources unchanged.
Do not use a verification STEP as an unreported construction input.

Jobs use idempotency keys. Inspect job and run state after a lost response.
Cancellation cannot undo a running operation. An interrupted job is not replayed automatically.
The MCP uses one configured principal. The service contracts permit a future authenticated web adapter; they do not provide web authentication or hostile multi-tenant isolation.

The current MCP executes CAD only through the headless build123d worker.
The FreeCAD proxy has been removed. Historical adapter references remain for provenance; their calls are unavailable through the current MCP.

## Documentation and version control

Use technical English in accordance with ASD-STE100 for project documentation, comments, docstrings, and tool descriptions.
Use the [language guide](skills/drawing2cad/references/documentation-language.md).
Do not claim full conformity without the required review.

Keep source code, tests, dependency files, example configurations, maintained references, and original resources in Git.
Put generated artifacts in ignored output directories.
Do not commit environments, caches, credentials, or machine-specific configuration.
`.gitattributes` preserves original resource and STEP bytes for stable source hashes.
