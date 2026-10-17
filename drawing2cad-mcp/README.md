# drawing2cad-mcp

This server supplies PDF uploads and preparation, versioned part construction, dimensioned DXF/PDF drawings, and validated STEP through one MCP interface.
The backend is build123d with OCP/OpenCascade. The drawing adapter uses ezdxf and its PDF renderer.
A restricted child process executes each build or fresh STEP import.
CAD execution uses only the headless build123d worker. The server has no FreeCAD proxy.

Use the [Streamable HTTP guide](STREAMABLE_HTTP.md) for HTTP transport and client registration.
Use [ADR 0014](../docs/adr/0014-headless-build123d-metric-prototype.md) for the selected sandbox and milestone boundaries.
Use [ADR 0016](../docs/adr/0016-shared-domain-service-and-drawing-delivery.md) for shared services, persistent jobs, and drawing delivery.

## Docker runtime

From the repository root:

```bash
docker compose -f compose.mcp.yaml build
docker compose -f compose.mcp.yaml run --rm -T mcp
```

This starts MCP over stdio. Attach a client to stdin/stdout.
The service has no network and publishes no HTTP port.
It retains sources, revisions, jobs, notes, and artifacts in the `cad-data` volume at `/data`.
The Docker configuration enables the domain profile, with private storage at `/data/domain`.
Send PDF bytes through the upload tools. No source directory mount is required.

For HTTP, set `DRAWING2CAD_HTTP_TOKEN` through your secret mechanism and run:

```bash
docker compose -f compose.mcp.yaml -f compose.mcp-http.yaml up --build -d
```

The endpoint is `http://127.0.0.1:8765/mcp`. Use the same bearer token in the client.
Only the host loopback interface is exposed. The application can receive HTTP requests; the CAD child retains its separate network restrictions.

The image contains Python, Poppler, build123d, OCP/OpenCascade, STEPcode, and the worker.
The container has a read-only root filesystem, no Linux capabilities, no-new-privileges, and finite CPU, memory, and process limits.
Each CAD job adds Landlock filesystem rules, seccomp restrictions, resource limits, and a timeout.
A missing sandbox produces a structured failure. There is no unsandboxed host fallback.
The current profile is not a claim of hostile multi-tenant isolation.

The domain profile uses source, run, job, and artifact IDs. It does not accept client-supplied server paths.
`DomainService` owns the shared operations and storage for MCP and the future web adapter.
The web routes and React interface belong to the M2 web part and are not implemented here.
MCP uses one configured principal. A bearer token does not establish separate identities for each client.
The service accepts a trusted `AccessContext` from an adapter; no tool argument can select that identity.
The existing demo is separate from this service.

The editable source for declarative construction is the versioned JSON part description.
The default profile exports AP214 geometry and records the actual file schema.
The optional `ap242` profile embeds application-specific construction and supports nominal
diameter and linear PMI. Read `pmi_schema` before use. The remote `step_reconstruct`
tool accepts an existing STEP artifact ID and hash, then returns diagnostic replay outputs.
It does not release or change the original run. External STEP upload is out of scope.
See [ADR 0017](../docs/adr/0017-ap242-application-construction-and-pmi.md) for the contract,
validation boundaries, and remaining M3 requirements.

Each AP242 build also uses the independent STEPcode reader in a fresh restricted
worker. Release requires a passing schema read and nominal PMI graph check bound
to the candidate hash. The graph check covers values, units, identifiers, product
links, and face membership. It does not independently measure the solid.
This is not full EXPRESS or exact-edition certification. Read each report's checks.
Use `part_render_pmi` before release, or `step_render_pmi` on a generated artifact,
to produce PDF/PNG inspection views of the actual stored PMI strokes. Read detail
views in the annotation plane; overview views can reverse or flatten text.
Rendering does not replace an identified visual review or a third-party CAD test.

## Tools

Use the live catalog for exact schemas and limits.

| Tool | Purpose |
|---|---|
| `drawing2cad_status`, `cad_capabilities` | Runtime versions, service scope, and capability limits. |
| `cad_worker_probe` | Actual restriction, failure, and recovery tests for the worker. |
| `upload_begin`, `upload_get`, `upload_chunk`, `upload_complete`, `upload_abort` | Resumable PDF bytes with size, hash, and committed-offset checks. |
| `source_get`, `source_list` | Source metadata for the authenticated principal. |
| `artifact_get`, `artifact_list`, `artifact_read`, `artifact_preview` | Immutable artifact metadata, bounded downloads, and PDF/PNG inspection. |
| `domain_schema` | Shared input contracts and public response-record schemas for MCP and web adapters. |
| `job_submit`, `job_get`, `job_list`, `job_cancel` | Persistent CAD and drawing jobs, idempotent submission, and cancellation requests. |
| `notes_read`, `notes_update` | Run notes with their own expected revision. |
| `pdf_info` | PDF hash, page count, page geometry, boxes, and rotation. |
| `pdf_read_text` | Bounded embedded-text extraction; no OCR. |
| `pdf_render_page`, `pdf_crop_region` | Page/detail images and artifact hashes. |
| `drawing_extract` | Supported vector analysis, views, glyph text, and geometric candidates. |
| `pdf_calibrate` | Scale from two distinct printed dimensions in one source view. |
| `pdf_measure_distance`, `pdf_measure_circle` | Evidence-linked estimated measurements from supplied observations. |
| `part_schema`, `part_validate` | Read the closed versioned schema; validate description structure and references. |
| `part_create`, `part_read`, `part_update` | Stored description revisions and results. |
| `create_base_body`, `add_hole`, `add_pocket`, `add_cut`, `add_chamfer`, `add_fillet` | Granular operations on the same feature representation. |
| `build_from_description` | Build the description, export a candidate, and validate a fresh-worker import. |
| `pmi_schema` | Read the closed nominal PMI contract for the optional AP242 profile. |
| `step_reconstruct` | Rebuild an existing STEP artifact in fresh workers. Return separate diagnostic artifacts; do not approve or change the source run. |
| `part_render_pmi` | Inspect the current AP242 build before release. Return stored-PMI PDF/PNG views bound to its revision and hash. |
| `step_render_pmi` | Inspect an authorized generated STEP artifact by ID and exact hash. Return PDF/PNG views; no model approval. |
| `build_code` | Optional in-memory execution, requiring configuration and a verified sandbox. The tool list omits it when `allow_build_code` is false. |
| `export_step` | Release a candidate after trusted re-import, dimension checks, and source-review coverage. |
| `part_export_review` | Review records, coverage, manifest, and event evidence. |
| `drawing_schema`, `drawing_validate`, `drawing_render`, `drawing_read`, `drawing_review` | Revision-bound drawing specification, DXF/PDF output, layout checks, and identified review. |
| Read-only `step_*` | Inspect STEP by artifact ID and expected hash; not full conformance analysis. |

The server can prefix tool names with its client namespace.
PDF results contain `structuredContent` and equivalent text metadata.
Page and detail results also contain PNG image blocks.
Preview metadata give the actual display size; the full artifact remains in server storage.

## Uploads, artifacts, and jobs

1. Call `upload_begin` with `filename`, byte count, and exact SHA-256. The filename is metadata only.
2. Send base64 chunks through `upload_chunk` at the committed byte offset. The default chunk limit is 512 KiB before base64 encoding. The PDF limit is 20 MiB.
3. After a lost response, use `upload_get`. An exact retry of a committed chunk is safe; different bytes or a different chunk boundary are rejected.
4. Call `upload_complete`. The service verifies size, hash, and PDF header/trailer markers. Structural PDF validation remains `not_tested` at this point.
5. Use the returned `source_id` in PDF tools and `part_create.sources`. Include its exact hash and source role.
6. Download results through `artifact_read`, using its byte offset and bounded length. Verify the complete download against `artifact_get.sha256`.

Artifacts are immutable snapshots. A later build does not replace an earlier artifact ID.
Failed drawing layouts can return diagnostic PDF and JSON artifacts through `drawing_render`.
Use `artifact_preview` to inspect the marked PDF. Read the report for label identifiers and rendered bounds in sheet millimeters.
Diagnostic artifacts retain the drawing hash, description hash, and part revision. They are not accepted technical drawings.
Correct the identified layout defects and render again. An accepted drawing review and STEP release still require a passing render.
Malformed declarations fail the maintained Pydantic contract before drawing state changes.
Schema validation does not establish correct geometry, complete source coverage, or a readable sheet.
Source and artifact access is scoped to the trusted principal. Source bytes are checked again before use.
The service does not enforce an aggregate disk quota or a retention period. Operators must manage retained data and free space.

Use `job_submit` for `build_from_description`, `build_code`, `drawing_render`, or `export_step`.
Supply `operation`, its normal `arguments`, and an `idempotency_key`. Reuse a key only for the identical operation and arguments.
Read completion with `job_get`; a transport response that confirms submission is not a CAD pass.
A job that ran and failed its checks has the state `failed` and keeps the public operation report in `result`, for example the defects of a drawing validation.
The queue permits 128 pending or active jobs by default. It returns `JOB_QUEUE_FULL` at the limit and still permits exact idempotent retries.
One job service holds an operating-system lock for the shared store. Start it once in the application lifespan.
After a restart, queued jobs resume. Unfinished active jobs become `interrupted`; uncertain effects are not replayed.
Cancellation prevents queued work from starting. A running operation can still finish with effects and a `succeeded` or `failed` state.
Inspect its result and the part before another mutation. Cancellation does not roll back CAD state.

Run notes have an independent revision that starts at zero. `notes_update.expected_revision` refers to the note revision, not the part revision.

## Part description and supported geometry

Schema version `1.0` uses millimeters and a right-handed XYZ frame.
Features have stable IDs. Their list defines the operation order.
Named parameters have values, units, and evidence IDs.
A numeric feature field can reference a parameter with `{"parameter":"name"}`.

| Feature | Supported scope |
|---|---|
| Base/additive body | Box, cylinder, polygon extrusion, or closed line-and-arc profile extrusion. Extrusions can have a bounded draft angle. |
| Hole | Through or blind; plain, counterbore, or countersink. A blind hole can have an explicit conical drill tip. |
| Thread data | Tap-drill geometry and thread designation, pitch, and hand in JSON. No helical flanks or semantic STEP PMI. |
| Pocket/cut | Box, cylinder, or polygon removal. |
| Chamfer/fillet | Geometric edge-center bounds, geometry type, size, and exact expected selection count. |

A box origin is its minimum corner.
A cylinder origin is its base center.
Polygon points lie in the local XY plane.
For a ±X extrusion axis, local X follows global Y; otherwise local X follows global X.
A hole position is its entry center, and its axis points into the part.
The default hole axis is -Z.
The blind depth measures the cylindrical portion. A conical tip extends beyond that depth.
Inline `build_code` receives `build123d` and a copy of the current `description`.
Use its named parameters to avoid a second set of unlinked values in code.
The trusted validation uses the stored description, not the copy changed by inline code.
Retain the exact inline payload in the trace and rerun it for parameter changes.
JSON alone cannot replay geometry that exists only in this payload.
Free-code feature replay remains unverified, even when a parameter-change test passes.

Evidence has a source ID, SHA-256, page, view, region, reason, and status.
Statuses are `explicit`, `derived`, `inferred`, `assumed`, or `unresolved`.
Review status is `open`, `accepted`, or `rejected`.
Regions declare `normalized_displayed`, `pdf_points`, or `pixels`.
Do not mix these coordinate conventions.

If a dimension is absent, use a reasonable geometric assumption and record its source region and reason.
Block only when no reasonable assumption supports construction.
Execution coverage is not proof that every source feature was identified.

Independent expectations cover bounding-box extents, volume, cylindrical diameters and lengths,
circle radii, hole-axis spacing, planar spacing, draft angles, line angles, and cone angle/width.
`section_distance` measures spacing along a selected line between trimmed planar faces, including drafted walls.
`surface_radius` measures a cylindrical surface near an actual surface anchor, including a trimmed fillet.
Their values are literals with source evidence and predefined comparison tolerances.
Do not copy construction constants as the only evidence of correct interpretation.
Missing measurements produce `not_tested`.
A hole measurement can include source-derived `entry_position`; its signed axis must point into the part.
The entry check supports connected full cylinders, cones, and planar shoulders at a planar circular opening.
A stepped bore is one connected cavity. Each of its bores has the outer opening as entry; an internal shoulder is not an entry.
If this field is absent, `entry_side` is `not_tested`; diameter and depth alone do not prove the entry side.
Named references update their direct uses. There is no algebraic constraint solver for derived profile coordinates.
Rebuild and measure a changed description before claiming parameter editability.

## Technical drawing delivery

Read `drawing_schema`. DrawingSpec 1.0 binds the sheet to `part_revision` and the canonical `description_sha256` returned by the part service.
Supply views with line, circle, and arc geometry, evidence and feature references, dimensions, notes, and uncertainty markers.
Coordinates can reference named part parameters with a factor and offset. A model edit requires a newly bound drawing specification and rendering.
Native DXF linear, radius, diameter, and angular dimension entities describe the supplied view geometry. The PDF is rendered from these same entities.
The output is editable DXF; it is not a native parametric CAD drawing with automatic solid projections.

The adapter does not infer arbitrary orthographic views or extract sections from the solid.
Supply required section geometry and labels, then review them against source images and the model.
Automatic drawing-to-solid equivalence, general GD&T validation, and semantic PMI remain unsupported.
Schema and layout checks cannot prove that the source was interpreted correctly or that all necessary views were supplied.

Use `drawing_validate`, then `drawing_render`. Inspect the returned PDF artifact and layout report.
Either drawing or model can be created first. After the model build, record `drawing_review` for the exact drawing hash, current part revision, construction-source hashes, reviewer, decision, and reason.
A model rebuild invalidates the earlier drawing review, including a rebuild of the same revision.
STEP release requires current drawing artifacts, passing layout checks, and an accepted review bound to the current model candidate.
The review is an identified attestation; automatic CAD equivalence remains `not_tested`.

## Validation and milestone limits

Call `cad_worker_probe` before CAD work.
Use the current revision returned by `part_read` for mutations.
After a lost response, inspect stored state and artifacts before another mutation.

The build creates the first STEP candidate and validates its import in a fresh worker.
`export_step` releases that candidate only after dimension checks, complete source-review coverage, and the current drawing-review gate.
The coverage record is a reviewer attestation, not automatic proof of source interpretation.
The geometry test is separate from independent STEP conformance analysis and an optional opening test in a target CAD system.
Unavailable external tests remain `not_tested`.
They prevent a complete metric pass where required.

Drawing delivery and model validation are separate checks. Their final revisions must agree.
M3 must prove construction and parameter changes from STEP alone, plus separate semantic and graphical PMI results.
The web interface belongs to the M2 web part. AP242 and PMI belong to M3.
Resource acceptance trials follow after the delivery milestones.

See the [skill workflow](../skills/drawing2cad/references/managed-workflow.md)
and [validation contract](../skills/drawing2cad/references/validation.md).
Neither a metadata append nor a structural evidence attestation replaces geometric validation.

## Recorded evaluations

Use the maintained `drawing2cad_mcp.evaluation_client` module to replay declared MCP calls.
It records exact requests, responses, timing, hashes, questions supplied in the plan, and infrastructure errors.
It does not process PDF or CAD content outside the MCP.
Keep plans, model inputs, traces, and generated files in ignored output storage.
For a local Ollama trial, use the [local model evaluation guide](../docs/local-model-evaluation.md).
These clients are evaluation tools. They are not part of the production API.

## Installation

Install Python 3.11 or later and Poppler with `pdftoppm`.
Installation includes PyMuPDF 1.28.2 for vector analysis.
For CAD work, use the Docker image with its supported Linux sandbox.
A local `[cad]` installation does not bypass the sandbox requirement.

On Windows, run these commands from this directory:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[test]"
Copy-Item drawing2cad-mcp.example.toml drawing2cad-mcp.local.toml
```

Vector analysis is part of this package. No second package or CLI installation is necessary.
`drawing2cad_status` reports the built-in analysis under `drawing_analysis`.

On Linux or macOS, use `python3 -m venv .venv` and `.venv/bin/python`.
Install Poppler separately, or configure the existing absolute path to `pdftoppm`.
`requirements-tested.txt` records the Python package versions from the test.
To use those versions, run `pip install -c requirements-tested.txt -e ".[test]"`.
The constraints file records a previous environment. Use current run reports for actual platform test results.

Set the TOML configuration:

- `[pdf]`: permitted source directories, output directory, and optional absolute Poppler path. Without that path, the server searches `PATH` for `pdftoppm`.
- `[cad]`: enable the maintained worker and set finite timeout, memory, concurrency, and call-budget limits. Keep `allow_build_code=false` unless its verified scope is needed.
- `[server]`: transport, preview limits, PDF concurrency, `max_step_bytes`, and optional `expose_legacy_workflow`. The default transport is `stdio`.
- `[http]`: listener address, port, permitted Host and Origin headers, and the bearer-token environment variable.
- `[domain]`: enable ID-based operations, select private storage, set the server principal, and bound PDF/chunk sizes. Docker enables this profile.

Relative **configuration paths** use the TOML directory as their base. Domain tools use IDs and keep server paths internal.
The default Python settings keep `domain.enabled=false` for the local-path development profile. Enable it for remote upload operation.
The `.local.toml` file is specific to this computer. The portable example has no user-specific paths.
Remove the old `[freecad]` section and `server.expose_freecad_proxy` setting when migrating.
The current configuration rejects these fields, including disabled values.
The generic example disables CAD execution; the Docker configuration enables the supported build123d worker.

## Start Streamable HTTP

Run this command from the package directory:

```powershell
.\.venv\Scripts\python.exe -m drawing2cad_mcp --config drawing2cad-mcp.local.toml --transport streamable-http
```

On Linux or macOS, use `.venv/bin/python`.
The default endpoint is `http://127.0.0.1:8000/mcp`.
The path is `/mcp`. The server does not supply the legacy `/sse` transport.
Set `[server].transport = "streamable-http"` to make HTTP the configured transport.
CLI options `--transport`, `--host`, and `--port` override their configuration values.
The standard command keeps stdio if the configuration does not select HTTP.

The server uses the MCP SDK's stateless Streamable HTTP transport with streamed responses.
It does not require an `Mcp-Session-Id` header.
Each HTTP request body has a limit of 4 MiB.
The transport has no stream resumption or automatic replay of interrupted requests.
Part revisions, build results, and release records are stored separately from transport state.
A lost response does not prove that an operation failed or stopped.
Use `part_read` and inspect artifacts before you repeat a CAD call.
Part operations use a per-run lock and expected revisions.
Coordinate edits to the same run; a busy run returns `RUN_BUSY` for a mutation.
While another operation holds the run, `part_read`, `drawing_read`, `drawing_validate`, and `notes_read` return a consistent snapshot with `read_mode: snapshot_during_active_operation`.
A rejected build (`CAD_DISABLED`, `BUILD_CODE_DISABLED`, `PMI_PROFILE_REQUIRED`, `STEP_BUDGET_EXHAUSTED`, or a source check) keeps the current build, release, and drawing review.
Errors contain a stable `code` and a message without host paths. Worker errors keep their `feature_id`. Invalid arguments return the JSON Pointer of the field in `target`.
This transport setting does not make CAD operations stateless.

### Listener access

The default listener accepts connections only on the local loopback interface.
If `DRAWING2CAD_HTTP_TOKEN` is set, each request must include `Authorization: Bearer <token>`.
The server reads the variable named by `[http].token_env` at startup.
Set the same token in the client. Do not commit its value.
Restart the server after a token change.
A non-loopback listener requires a non-empty token before startup.

`allowed_hosts` permits incoming Host headers. Add the deployment hostname and port before clients use that address.
The defaults permit loopback names. A listener address such as `0.0.0.0` does not permit every Host header.
Requests without an Origin header are permitted.
If a request has an Origin header, it must match `allowed_origins`.
The default empty list rejects all supplied origins. This setting does not add browser CORS support.

For a container service, set the listener to `0.0.0.0` and configure its token.
Add the actual service address, for example `drawing2cad:8000`, to `allowed_hosts`.
Use `http://drawing2cad:8000/mcp` from another container on that network.
The address `127.0.0.1` in a LiteLLM container refers to that container.
For connections across an untrusted network, put the endpoint behind a TLS reverse proxy.
Preserve the permitted Host header and request streaming through that proxy.

The HTTP endpoint uses the same domain storage, source ownership, part revision gates, and CAD worker restrictions as stdio.
Uploads and downloads use MCP tools. There are no separate REST download routes or web interface in this milestone.
The local-path development profile returns server paths; do not use that profile as the remote upload contract.
MCP image blocks remain available to remote clients.

For a future shared Python backend, use `drawing2cad_mcp.http.create_http_app(application)` as the ASGI application factory.
Pass a configured `Application` and run the returned application's lifespan.
The lifespan manages the MCP application. Reuse that application for requests.

## Register with an agent

Register only this server. The worker and CAD dependencies are part of its image.
For LiteLLM, use [litellm-mcp.example.json](litellm-mcp.example.json) and the [registration procedure](#register-with-litellm).
For an HTTP client with an `mcpServers` configuration, use the server URL:

```json
{
  "mcpServers": {
    "drawing2cad": {
      "url": "http://127.0.0.1:8000/mcp"
    }
  }
}
```

Configure the bearer token through the client's secret mechanism when the server requires it.
The client must support Streamable HTTP. A browser page or ordinary GET request is not an MCP readiness test.
Initialize an MCP connection, list tools, and call `drawing2cad_status`.

For stdio clients, replace the example paths:

```json
{
  "mcpServers": {
    "drawing2cad": {
      "command": "C:/Projekt/drawing2cad-mcp/.venv/Scripts/python.exe",
      "args": ["-m", "drawing2cad_mcp", "--config", "C:/Projekt/drawing2cad-mcp/drawing2cad-mcp.local.toml", "--transport", "stdio"]
    }
  }
}
```

Codex uses TOML. For HTTP, use a URL and an optional token variable:

```toml
[mcp_servers.drawing2cad]
url = "http://127.0.0.1:8000/mcp"
bearer_token_env_var = "DRAWING2CAD_HTTP_TOKEN"
startup_timeout_sec = 30
tool_timeout_sec = 300
```

Omit `bearer_token_env_var` for the local listener without authentication.
The stdio alternative is:

```toml
[mcp_servers.drawing2cad]
command = 'C:\Projekt\drawing2cad-mcp\.venv\Scripts\python.exe'
args = ["-m", "drawing2cad_mcp", "--config", 'C:\Projekt\drawing2cad-mcp\drawing2cad-mcp.local.toml', "--transport", "stdio"]
startup_timeout_sec = 30
tool_timeout_sec = 300
```

The example allows 300 seconds for a tool call.
Set the client timeout above the total duration of all worker phases in that call.
A build can include both construction and fresh STEP import, each with its own worker timeout.
After configuration changes, reload the MCP connection in the client.
See the [Codex configuration reference](https://learn.chatgpt.com/docs/config-file/config-reference).

To start the stdio protocol process manually, run this command:

```powershell
.\.venv\Scripts\python.exe -m drawing2cad_mcp --config drawing2cad-mcp.local.toml --transport stdio
```

The process waits for an MCP client on stdin/stdout. It sends logs to stderr.
An empty console is not an error.

## Register with LiteLLM

[litellm-mcp.example.json](litellm-mcp.example.json) is a request body for `POST /v1/mcp/server` on LiteLLM.
It registers Streamable HTTP with the explicit LiteLLM value `"transport": "http"`.
It is not a stdio UI JSON block or a complete LiteLLM configuration file.

1. Install the MCP and PDF dependencies. Use the supported Docker worker profile for CAD execution.
2. Create the local configuration from the [TOML example](drawing2cad-mcp.example.toml). Set its paths for that host.
3. Start the [Streamable HTTP server](#start-streamable-http).
4. Set the example's `url` to an address that the LiteLLM process can reach.
5. Register the JSON with the LiteLLM management API, or enter its values in the Admin UI.
6. Assign the necessary MCP access in LiteLLM and list the tools.
7. Call `drawing2cad_status` with `{}` through the registered tool name.

For the UI, open **MCP Servers → Add New MCP Server**.
Select **Streamable HTTP** and enter the server name, alias, URL, and authentication settings.
Configure database storage for UI registrations as required by the LiteLLM deployment.
For API registration, send the example as JSON to the LiteLLM endpoint with a permitted LiteLLM administration credential.
The `auth_type` and `auth_value` fields configure LiteLLM's connection to drawing2cad.
They are separate from the credential used to call the LiteLLM management API.

The example uses `auth_type="none"` for the default local listener without a token.
If the MCP server requires a token, set `auth_type="bearer_token"` and supply `auth_value` through the registration process.
Use the same value as the server's configured token variable. Keep it outside the committed JSON example.
Do not use `auth_type="api_key"`; that setting sends a different header.

LiteLLM `config.yaml` uses a separate format:

```yaml
mcp_servers:
  drawing2cad:
    url: http://127.0.0.1:8000/mcp
    transport: http
    auth_type: none
```

For a token-protected server, use these fields instead of `auth_type: none`:

```yaml
    auth_type: bearer_token
    auth_value: os.environ/DRAWING2CAD_HTTP_TOKEN
```

Set that variable in the LiteLLM process environment.
HTTP registration does not require `LITELLM_ENABLE_MCP_STDIO`.
See the official [transport and configuration reference](https://docs.litellm.ai/docs/mcp_config_reference)
and [API registration example](https://docs.litellm.ai/docs/mcp_public_internet#per-server-setting).
Use the [authentication reference](https://docs.litellm.ai/docs/mcp/) for credential fields.

### Optional stdio registration

[litellm-stdio.example.json](litellm-stdio.example.json) preserves the `mcpServers` JSON format for the LiteLLM stdio UI.
Install the MCP package on the LiteLLM host. Replace both paths with paths accessible to that process.
Set `LITELLM_ENABLE_MCP_STDIO=true` in the LiteLLM process environment before startup.
Select **Standard Input/Output (stdio)** and paste the adjusted JSON into its configuration field.
See the [stdio registration instructions](https://docs.litellm.ai/docs/mcp/#add-stdio-mcp-server).

Registration does not install server dependencies. The Docker image supplies the worker. The base Compose profile uses stdio and no network; the HTTP override publishes the authenticated endpoint.

Load the complete [drawing2cad skill folder](../skills/drawing2cad/SKILL.md) in the agent that uses these tools.
Include its `references/` files. MCP registration does not install the skill or load its workflow instructions.
The skill remains at `skills/drawing2cad`; the JSON examples remain with the MCP configuration examples.

## Reproducible PDF procedure

1. Upload only the permitted PDF, then give its `source_id` to `pdf_info`.
2. Record `source.sha256`.
3. Call `pdf_read_text` for the necessary pages.
4. If page 1 has `status="native_text_missing"`, assess whether it meets the [vector analysis profile](#vector-analysis).
   For supported vector drawings, call `drawing_extract` to read glyph outlines and sheet coordinates.
   Examine `?` characters and `unclear` strokes in detail images. Also verify critical values that appear recognized.
   For scans or unsupported profiles, use page and detail images. Record unresolved data.
5. Call `pdf_render_page`.
6. Inspect the returned image.
7. Create detail images for critical dimensions, for example:

```json
{"source_id":"src_0123456789abcdef0123456789abcdef","page":1,"bbox":[0.25,0.0,0.75,0.5],"dpi":300,"include_image":true}
```

8. Record the source hash, page, crop region, resolution, and artifact hash with the observation.
9. Compare `source.sha256` after each call. A changed source requires a new revision.

Page numbers start at **1**.
`bbox=[left,top,right,bottom]` uses **normalized values from 0 to 1**.
Its origin is the top-left corner of the displayed page after rotation.
The effective page is the intersection of **CropBox and MediaBox**.
Metadata contain the original boxes and the effective box.
The crop operation rounds left and top down to pixels. It rounds right and bottom up.
These coordinates are not CAD coordinates.

The server renders the full page before it creates a detail image.
Thus, `max_pixels` also applies to the full page during a crop call.
DPI must be from 36 to 600.
A higher DPI cannot restore missing image information from a raster source.
Each call reads its own size-limited PDF snapshot.
There is no session across documents and no automatic interpretation of drawing dimensions.

## Vector analysis

`drawing_extract` reads the selected one-based `page` (default 1) from its size-limited source snapshot. The returned hash identifies that snapshot.
Its coordinates are **millimeters on the displayed sheet**, origin top left, y down after page rotation. They are not CAD coordinates.
The analysis does not apply the drawing scale or associate dimensions with model features.
Without `include_strokes=true`, each view gives `stroke_count` instead of `stroke_ids`.
Use `stroke_kinds`, for example `["unclear"]`, only with `include_strokes=true` to request a subset.
View membership and summary counts describe the complete analysis, including when the returned strokes are filtered.

The current profile supports BCT A3 landscape sheets from Siemens NX.
The profile removes its fixed frame and title block before classification.
Other layouts can produce missing geometry or incorrect classes, even when their sheet size matches.
The server supports page rotation of 0, 90, 180, or 270 degrees.
It still requires the supported full-page CropBox, zero MediaBox origin, and UserUnit 1.
The normal PDF text, page, and crop tools retain their separate page-transform support.

The glyph reader uses the bundled NX glyph templates. It does not perform OCR.
Unknown characters can appear as `?` or as an incorrect known character.
Filled triangles are arrowheads, not characters. The glyph reader ignores them.
The class `annotation` marks strokes that are not part geometry. Text positions are the evidence.
It includes free table separators between stacked text and free edge condition corners (ISO 13715) next to a signed value.
It also includes drawn parentheses around a text block. The enclosed text then starts with `(`.
A free stroke has no contact with other strokes at its ends, along its length, or at a crossing.
The reader does not read stroke text in the title block.
Obtain the drawing scale, tolerances, and manufacturing notes from verified source observations.
Unclassified strokes remain `unclear`. Classification is evidence for review, not a verified manufacturing requirement.

The analysis runs in a separate process for each request.
`pdf.timeout_seconds` limits that process. The service terminates it when the timeout expires.
The source snapshot and internal response are temporary data. The operation creates no persistent JSON export or colored overlay.
For visual review, use `pdf_render_page` and `pdf_crop_region`.

Create the model through the maintained part tools. Use the drawing tools to create and review the dimensioned technical drawing.
Its creation can precede or follow construction; final revisions must agree.
Vector analysis does not author drawings, build CAD features, or supply semantic PMI.
See [ADR 0013](../docs/adr/0013-vector-analysis-in-mcp.md) for the feature comparison and package migration.

## Behavior and limits

- PDF preparation uses pypdf for text and metadata, Poppler for raster images, and Pillow for crops and previews.
- `drawing_extract` uses the internal `drawing2cad_mcp.vector` module and PyMuPDF in an isolated request process.
- The server has no OCR or autonomous drawing interpretation. CAD tools build the explicit feature description supplied through MCP.
- The domain service resolves authorized source IDs to private paths, verifies source hashes, and applies file-size, page, and pixel limits.
- Poppler and vector analysis each use `pdf.timeout_seconds`. That timeout does not apply to the in-process pypdf parser.
- This server is not an isolated service for unrestricted hostile PDF inputs.
- PDF preparation remains available when CAD execution is disabled or its sandbox is unavailable.
- CAD calls use the maintained build123d worker. There is no external CAD proxy or GUI dispatcher.
- Part revisions and per-run locks prevent conflicting mutations. Domain storage also scopes objects to the adapter's trusted principal. MCP currently supplies one configured principal.
- The server does not automatically retry failed or canceled CAD calls.
- An operation that has started can have changed stored state. Use `part_read` before a retry.
- `build_code` requires configuration and a verified sandbox. Its exact inline payload is part of the construction evidence.
- M1 STEP geometry export does not establish AP242 construction or semantic PMI.
- Removed `freecad_*` calls return `UNKNOWN_TOOL`. Historical adapters do not supply a current execution path.

## Tests and skill

```powershell
$env:DRAWING2CAD_PDFTOPPM = 'C:\Pfad\zu\pdftoppm.exe'
New-Item -ItemType Directory -Force ../output | Out-Null
$testRun = '../output/tests-' + [guid]::NewGuid().ToString('N')
.\.venv\Scripts\python.exe -m pytest tests --basetemp $testRun -q
```

Without Poppler, the test suite skips image-render tests.
Without the sample drawings in `../resources/Drawing2CAD/`, it skips the vector sample tests.
It can skip symbolic-link tests if the operating system does not permit symbolic links.
The suite uses synthetic PDFs, explicit CAD descriptions, and isolated test processes.
It tests rotation, CropBox/MediaBox, UserUnit, detail pixels, source identity, errors, transport fidelity, and cancellation without automatic retry.

The project skill is at `../skills/drawing2cad`.
It specifies this interface and the model-independent workflow in `references/drawing2cad-mcp.md`.
Use `references/drawing-delivery.md` for technical drawing delivery. Drawing and model creation can occur in either order.
M1 part gates, M2 drawing delivery, and M3 AP242 acceptance have separate scope and test results.

## Documentation language

Write project documentation in technical English in accordance with ASD-STE100.
Use the [language guide](../skills/drawing2cad/references/documentation-language.md) for terminology and review.
Keep exact interface text, executable examples, and historical test evidence unchanged.
