# drawing2cad-mcp

This MCP server supplies PDF metadata, embedded text, page images, and detail images.
Its built-in vector analysis supplies views, text from glyph outlines, and classified strokes for a supported drawing profile.
It also supplies maintained STEP inspection tools and a persistent evidence workflow.
A configured FreeCAD proxy can be exposed explicitly for development. It is hidden by default.

Agent → **Streamable HTTP or stdio** → **drawing2cad-mcp** → PDF preparation / existing FreeCAD MCP → FreeCAD addon.

Use the [Streamable HTTP guide](STREAMABLE_HTTP.md) for installation, authentication, LiteLLM registration, network setup, and troubleshooting.

## Tools

| Tool | Purpose and parameters |
|---|---|
| `drawing2cad_status` | Runtime and proxy status. Optional argument: `refresh_freecad=true`. |
| `pdf_info` | `path`: SHA-256, page count, page size, CropBox, and rotation. |
| `pdf_read_text` | `path`, optional `pages`, `max_chars=50000`: embedded text. No OCR. |
| `pdf_render_page` | `path`, `page=1`, `dpi=150`, `include_image=true`: full page image. |
| `pdf_crop_region` | `path`, `page`, `bbox`, `dpi=300`, `include_image=true`: detail image. |
| `drawing_extract` | `path`, `include_strokes=false`, optional `stroke_kinds`: sheet size, views, glyph text, and optional classified strokes from page 1. See [Vector analysis](#vector-analysis). |
| `freecad_*` | All tools found in upstream discovery, with the prefix. The proxy does not maintain static copies of their schemas. |

Use the live catalog for the exact tool set. Local tools do not depend on FreeCAD.
The development proxy retains the discovered upstream schemas.
For example, `execute_code` becomes `freecad_execute_code`. Its arguments do not change.
The client can add a server namespace before the tool name.

PDF results contain machine-readable `structuredContent` and the same metadata as text.
Page and detail results also contain a PNG image block for direct inspection by an agent.
A separate local image viewer is not necessary. The full PNG stays available at `artifact.path`.
The server limits large preview images. The `preview` fields give their actual dimensions and scale factor.

## Managed evidence and STEP inspection

Call `cad_capabilities` before a run. Use the [managed workflow guide](../skills/drawing2cad/references/managed-workflow.md) for exact inputs, state transitions, recovery, and STEP tools.
The workflow validates structural evidence and review attestations. It does not create drawings or execute CAD.
Build, comparison, and export readiness remain unavailable until a verified backend exists.
STEP readers inspect limited profiles. They do not prove full EXPRESS conformity, geometric validity, or general PMI support.

The raw proxy is hidden by default. To use it for development, set `server.expose_freecad_proxy=true` and configure `freecad.enabled=true`.
Raw upstream calls bypass managed workflow gates. Previous proxy deployments need this explicit opt-in.
A metadata append writes a new STEP candidate without overwrite. It is not an AP242 CAD export.

## Installation

Install Python 3.11 or later and Poppler with `pdftoppm`.
Installation includes PyMuPDF 1.28.2 for vector analysis.
For CAD work, also install a FreeCAD MCP with a reachable FreeCAD addon.
This server does not require a GUI. It does not change the operating mode of the upstream FreeCAD server.

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
The recorded test used Windows and Python 3.12. Tests on other hosts have not been done.

Set the TOML configuration:

- `[pdf]`: permitted source directories, output directory, and optional absolute Poppler path. Without that path, the server searches `PATH` for `pdftoppm`.
- `[freecad]`: set `enabled=true`, the existing MCP launcher in `command`, and its `args`. Optional fields are `env` and `cwd`. For PDF work alone, set `enabled=false`.
- `[server]`: transport, preview limits, PDF concurrency, `max_step_bytes`, and optional `expose_freecad_proxy`. The default transport is `stdio`.
- `[http]`: listener address, port, permitted Host and Origin headers, and the bearer-token environment variable.

Relative **configuration paths** use the TOML directory as their base. PDF tool calls use **absolute file paths**.
The `.local.toml` file is specific to this computer. The portable example has no user-specific paths.

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
The server has no result store, stream resumption, or automatic replay of interrupted requests.
A lost response does not prove that an operation failed or stopped.
Inspect the actual model and artifacts before you repeat a CAD call.
This transport setting does not make CAD operations stateless.
One server process has one shared FreeCAD proxy. Its upstream calls run in sequence.
Coordinate document access between clients. Separate server processes do not share a CAD write lock.
Run one server process for one shared FreeCAD upstream until a worker coordinator exists.

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

The HTTP endpoint uses the same PDF and FreeCAD permissions as stdio.
It does not add user-specific file isolation, a web interface, or artifact downloads.
Returned `artifact.path` values refer to the server filesystem.
MCP image blocks remain available to remote clients.
The HTTP transport does not remove the current upstream's GUI dependency.

For a future shared Python backend, use `drawing2cad_mcp.http.create_http_app(application)` as the ASGI application factory.
Pass a configured `Application` and run the returned application's lifespan.
It owns upstream startup and shutdown. Do not start a second copy for each request.

## Register with an agent

Register only this server. It starts the existing FreeCAD MCP internally.
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
tool_timeout_sec = 1920
```

Omit `bearer_token_env_var` for the local listener without authentication.
The stdio alternative is:

```toml
[mcp_servers.drawing2cad]
command = 'C:\Projekt\drawing2cad-mcp\.venv\Scripts\python.exe'
args = ["-m", "drawing2cad_mcp", "--config", 'C:\Projekt\drawing2cad-mcp\drawing2cad-mcp.local.toml', "--transport", "stdio"]
startup_timeout_sec = 30
tool_timeout_sec = 1920
```

The example client timeout matches the local upstream timeout of 1900 seconds.
For different values, set the client timeout longer than the expected operation.
To supply only this interface, disable the existing direct FreeCAD entry.
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

1. Install `drawing2cad-mcp`, Poppler, and the selected FreeCAD upstream on the MCP server host.
2. Create the local configuration from the [TOML example](drawing2cad-mcp.example.toml). Set its paths for that host.
3. Start the [Streamable HTTP server](#start-streamable-http).
4. Set the example's `url` to an address that the LiteLLM process can reach.
5. Register the JSON with the LiteLLM management API, or enter its values in the Admin UI.
6. Assign the necessary MCP access in LiteLLM and list the tools.
7. Call `drawing2cad_status` with `refresh_freecad=true` through the registered tool name.

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

Neither registration mode installs the planned headless CAD worker. The current FreeCAD upstream still requires its own runtime.

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

`drawing_extract` reads page 1 from its size-limited source snapshot. The returned hash identifies that snapshot.
Its coordinates are **millimeters on the sheet**, origin top left, y down. They are not CAD coordinates.
The analysis does not apply the drawing scale or associate dimensions with model features.
Without `include_strokes=true`, each view gives `stroke_count` instead of `stroke_ids`.
Use `stroke_kinds`, for example `["unclear"]`, only with `include_strokes=true` to request a subset.
View membership and summary counts describe the complete analysis, including when the returned strokes are filtered.

The current profile supports BCT A3 landscape sheets from Siemens NX.
The profile removes its fixed frame and title block before classification.
Other layouts can produce missing geometry or incorrect classes, even when their sheet size matches.
The server rejects unsupported rotation, CropBox, MediaBox origin, and UserUnit values for vector analysis.
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

Create and review a dimensioned technical drawing from the verified observations.
Then build the editable 3D model and export STEP AP242 last.
Vector analysis does not author drawings, build CAD features, or supply semantic PMI.
See [ADR 0013](../docs/adr/0013-vector-analysis-in-mcp.md) for the feature comparison and package migration.

## Behavior and limits

- PDF preparation uses pypdf for text and metadata, Poppler for raster images, and Pillow for crops and previews.
- `drawing_extract` uses the internal `drawing2cad_mcp.vector` module and PyMuPDF in an isolated request process.
- The server has no OCR or automatic CAD reconstruction.
- The server verifies resolved PDF paths against permitted directories, file-size limits, page limits, and pixel limits.
- Poppler and vector analysis each use `pdf.timeout_seconds`. That timeout does not apply to the in-process pypdf parser.
- This server is not an isolated service for unrestricted hostile PDF inputs.
- The proxy preserves schemas, images, resource blocks, structured results, and error status.
- It is a **tool proxy**. It does not forward upstream resource lists, prompts, sampling, or elicitation.
- `freecad.connected` confirms the MCP transport. A suitable FreeCAD call is necessary to verify addon operation.
- If the upstream server is unavailable, the PDF tools stay available.
- The proxy can retain a previously discovered catalog with `catalog_stale=true`.
- Each server process runs its FreeCAD calls in sequence.
- Clients with separate server processes must coordinate access to shared CAD documents.
- The proxy does **not automatically retry** failed or canceled CAD calls.
- An operation that has started can have changed the model. Read its actual state before a retry.
- `freecad_execute_code` retains the upstream permissions.
- The PDF path restrictions do not restrict Python code that executes in FreeCAD.
- The proxy adds no AP242 or PMI capabilities and no implementation for CAD execution without a GUI.

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
The suite uses synthetic PDFs and a harmless MCP test process. It does not change FreeCAD models.
It tests rotation, CropBox/MediaBox, UserUnit, detail pixels, source identity, errors, transport fidelity, and cancellation without automatic retry.

The project skill is at `../skills/drawing2cad`.
It specifies this interface and the model-independent workflow in `references/drawing2cad-mcp.md`.
Create and verify the controlling dimensioned drawing before the 3D build.
Use `references/drawing-first.md` for the necessary evidence.
This is a work instruction. The server does not yet enforce it.
The CAD and AP242 adapters remain separate skill components with their own tests.

## Documentation language

Write project documentation in technical English in accordance with ASD-STE100.
Use the [language guide](../skills/drawing2cad/references/documentation-language.md) for terminology and review.
Keep exact interface text, executable examples, and historical test evidence unchanged.
