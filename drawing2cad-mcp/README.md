# drawing2cad-mcp

This server supplies PDF preparation, drawing measurements, versioned part construction, and validated STEP through one MCP interface.
The M1 backend is build123d with OCP/OpenCascade.
A restricted child process executes each build or fresh STEP import.
CAD execution uses only the headless build123d worker. The server has no FreeCAD proxy.

Use the [Streamable HTTP guide](STREAMABLE_HTTP.md) for HTTP transport and client registration.
Use [ADR 0014](../docs/adr/0014-headless-build123d-metric-prototype.md) for the selected sandbox and milestone boundaries.

## M1 Docker runtime

From the repository root:

```bash
docker compose -f compose.mcp.yaml build
docker compose -f compose.mcp.yaml run --rm -T mcp
```

This starts MCP over stdio. Attach a client to stdin/stdout.
The service has no network and publishes no HTTP port.
It mounts permitted inputs at `/inputs` and retains outputs in the `cad-data` volume at `/data`.
Set `DRAWING2CAD_INPUT_DIR` to select the permitted input directory; the default is `./resources`.

The image contains Python, Poppler, build123d, OCP/OpenCascade, and the worker.
The container has a read-only root filesystem, no Linux capabilities, no-new-privileges, and finite CPU, memory, and process limits.
Each CAD job adds Landlock filesystem rules, seccomp restrictions, resource limits, and a timeout.
A missing sandbox produces a structured failure. There is no unsandboxed host fallback.
The current profile is not a claim of hostile multi-tenant isolation.

M1 accepts configured server-side paths.
Persistent PDF uploads, opaque source/artifact IDs, browser downloads, and the unified MCP/API application belong to M2.
A client-local file path is not an upload.
The existing demo does not implement that production storage contract.

The editable source for declarative construction is the versioned JSON part description.
The prototype exports AP214 geometry and records the actual file schema.
It does not export editable construction or semantic PMI.
AP242 construction, adapter edits, and semantic and graphical PMI remain binding M3 requirements.

## Tools

Use the live catalog for exact schemas and limits.

| Tool | Purpose |
|---|---|
| `drawing2cad_status`, `cad_capabilities` | Runtime versions, service scope, and capability limits. |
| `cad_worker_probe` | Actual restriction, failure, and recovery tests for the worker. |
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
| `build_code` | Optional in-memory execution, requiring configuration and a verified sandbox. |
| `export_step` | Release a candidate after trusted re-import, dimension checks, and source-review coverage. |
| `part_export_review` | Review records, coverage, manifest, and event evidence. |
| `workflow_*` | Legacy structural evidence profile; hidden unless `server.expose_legacy_workflow=true`. |
| `step_*` | Bounded STEP inspection and application-property tools; not full conformance analysis. |

The server can prefix tool names with its client namespace.
PDF results contain `structuredContent` and equivalent text metadata.
Page and detail results also contain PNG image blocks.
Preview metadata give the actual display size; the full artifact remains in server storage.

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
If this field is absent, `entry_side` is `not_tested`; diameter and depth alone do not prove the entry side.
Named references update their direct uses. There is no algebraic constraint solver for derived profile coordinates.
Rebuild and measure a changed description before claiming parameter editability.

## Validation and milestone limits

Call `cad_worker_probe` before CAD work.
Use the current revision returned by `part_read` for mutations.
After a lost response, inspect stored state and artifacts before another mutation.

The build creates the first STEP candidate and validates its import in a fresh worker.
`export_step` releases that candidate only after dimension checks and complete source-review coverage.
The coverage record is a reviewer attestation, not automatic proof of source interpretation.
The geometry test is separate from independent STEP conformance analysis and opening in NX.
Unavailable external tests remain `not_tested`.
They prevent a complete metric pass where required.

The M2 service must also produce an editable technical drawing and rendered inspection copy.
Drawing and model creation can occur in either order.
Their final revisions must agree.
M3 must prove construction and parameter changes from STEP alone, plus separate semantic and graphical PMI results.

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
For CAD work, use the M1 Docker image with its supported Linux sandbox.
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

Relative **configuration paths** use the TOML directory as their base. PDF tool calls use **absolute file paths**.
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
Coordinate edits to the same run; a busy run returns `RUN_BUSY`.
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

The HTTP endpoint uses the same PDF path rules, part revision gates, and CAD worker restrictions as stdio.
It does not add user-specific file isolation, a web interface, or artifact downloads.
Returned `artifact.path` values refer to the server filesystem.
MCP image blocks remain available to remote clients.

For a future shared Python backend, use `drawing2cad_mcp.http.create_http_app(application)` as the ASGI application factory.
Pass a configured `Application` and run the returned application's lifespan.
The lifespan manages the MCP application. Reuse that application for requests.

## Register with an agent

Register only this server. The M1 worker and CAD dependencies are part of its image.
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

Registration does not install server dependencies. The M1 Docker image supplies the worker. The supplied Compose profile uses stdio and no network.

Load the complete [drawing2cad skill folder](../skills/drawing2cad/SKILL.md) in the agent that uses these tools.
Include its `references/` files. MCP registration does not install the skill or load its workflow instructions.
The skill remains at `skills/drawing2cad`; the JSON examples remain with the MCP configuration examples.

## Reproducible PDF procedure

1. Give only the permitted PDF to `pdf_info`.
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
{"path":"C:/Projekt/resources/Zeichnung.pdf","page":1,"bbox":[0.25,0.0,0.75,0.5],"dpi":300,"include_image":true}
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
The reader does not read stroke text in the title block.
Obtain the drawing scale, tolerances, and manufacturing notes from verified source observations.
Unclassified strokes remain `unclear`. Classification is evidence for review, not a verified manufacturing requirement.

The analysis runs in a separate process for each request.
`pdf.timeout_seconds` limits that process. The service terminates it when the timeout expires.
The source snapshot and internal response are temporary data. The operation creates no persistent JSON export or colored overlay.
For visual review, use `pdf_render_page` and `pdf_crop_region`.

Create the model through the maintained part tools. The complete M2 service must also create and review a dimensioned technical drawing.
Its creation can precede or follow construction; final revisions must agree.
Vector analysis does not author drawings, build CAD features, or supply semantic PMI.
See [ADR 0013](../docs/adr/0013-vector-analysis-in-mcp.md) for the feature comparison and package migration.

## Behavior and limits

- PDF preparation uses pypdf for text and metadata, Poppler for raster images, and Pillow for crops and previews.
- `drawing_extract` uses the internal `drawing2cad_mcp.vector` module and PyMuPDF in an isolated request process.
- The server has no OCR or autonomous drawing interpretation. CAD tools build the explicit feature description supplied through MCP.
- The server verifies resolved PDF paths against permitted directories, file-size limits, page limits, and pixel limits.
- Poppler and vector analysis each use `pdf.timeout_seconds`. That timeout does not apply to the in-process pypdf parser.
- This server is not an isolated service for unrestricted hostile PDF inputs.
- PDF preparation remains available when CAD execution is disabled or its sandbox is unavailable.
- CAD calls use the maintained build123d worker. There is no external CAD proxy or GUI dispatcher.
- Part revisions and per-run locks prevent conflicting mutations. They do not provide user-specific storage isolation.
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
Use `references/drawing-first.md` for technical drawing delivery. Its filename is retained for compatibility; no drawing-first order is required.
M1 part gates, M2 drawing delivery, and M3 AP242 acceptance have separate scope and test results.

## Documentation language

Write project documentation in technical English in accordance with ASD-STE100.
Use the [language guide](../skills/drawing2cad/references/documentation-language.md) for terminology and review.
Keep exact interface text, executable examples, and historical test evidence unchanged.
