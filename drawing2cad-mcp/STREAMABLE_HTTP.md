# Streamable HTTP setup and operation

Use this guide to run `drawing2cad-mcp` as an HTTP service and connect an MCP client or LiteLLM.
The guide applies to version 0.3.0 and later versions with the same configuration interface.

The connection path is:

```text
Agent or LiteLLM -> HTTP /mcp -> drawing2cad-mcp -> PDF tools
                                            -> stdio FreeCAD MCP -> FreeCAD runtime
```

The HTTP server uses one process and one shared FreeCAD proxy.
The current FreeCAD upstream still requires its configured runtime.
The HTTP MCP service does not supply a headless FreeCAD worker, packaged Docker image, or artifact download endpoint.
The [demo application](../app/README.md) has its own UI and Docker setup. It does not host this MCP endpoint.

## 1. Prepare the installation

Install Python 3.11 or later and Poppler with `pdftoppm`.
For CAD operations, install the selected FreeCAD MCP and its required FreeCAD runtime.
Use a client that supports MCP Streamable HTTP.

Run the commands from the repository root.
For an existing installation, keep its virtual environment and local configuration.
First, enter the `drawing2cad-mcp` directory.
Run only the package installation command to update its dependencies.

For a new Windows installation:

```powershell
Set-Location drawing2cad-mcp
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -c requirements-tested.txt -e ".[test]"
Copy-Item drawing2cad-mcp.example.toml drawing2cad-mcp.local.toml
```

For a new Linux or macOS installation:

```bash
cd drawing2cad-mcp
python3 -m venv .venv
.venv/bin/python -m pip install -c requirements-tested.txt -e '.[test]'
cp drawing2cad-mcp.example.toml drawing2cad-mcp.local.toml
```

The remaining commands use the `drawing2cad-mcp` directory.
Installation includes the vector analysis module and its pinned PyMuPDF dependency. No separate extractor package is necessary.
Use `drawing_extract` for the supported profile described in [Vector analysis](README.md#vector-analysis).
The operation reads page 1. It creates no persistent JSON export or colored overlay.

The recorded runtime tests used Windows and Python 3.12.
The Linux and macOS commands are installation instructions, not evidence of platform validation.

## 2. Configure server paths and tools

Edit `drawing2cad-mcp.local.toml` from the [configuration example](drawing2cad-mcp.example.toml).
Keep this deployment file outside version control.

| Setting | Action |
|---|---|
| `pdf.allowed_roots` | Set the permitted input directories on the server. |
| `pdf.output_root` | Set a writable output directory. Keep generated files in an ignored directory. |
| `pdf.pdftoppm` | Set the Poppler executable path, or omit this setting to use `PATH`. |
| `pdf.timeout_seconds` | Set the time limit for each Poppler or vector-analysis process. |
| `freecad.enabled` | Use `false` for PDF tools alone. Use `true` when the upstream is configured. |
| `freecad.command` and `freecad.args` | Set the existing FreeCAD MCP launcher and its arguments. |
| `freecad.cwd` and `freecad.env` | Set these optional fields only when the upstream requires them. |
| `freecad.timeout_seconds` | Set the permitted duration of an upstream operation. |

Relative configuration paths use the TOML file's directory.
PDF tool calls require absolute paths on the server filesystem.
An HTTP connection does not upload input files.
Supply only sources permitted for the current task, even when the path rules permit more files.

## 3. Select Streamable HTTP

Replace the corresponding values in the existing TOML sections.
Do not add a second `[server]` or `[http]` section.

```toml
[server]
transport = "streamable-http"
preview_max_pixels = 4000000
preview_max_bytes = 6000000
pdf_concurrency = 2

[http]
host = "127.0.0.1"
port = 8000
allowed_hosts = ["127.0.0.1:*", "localhost:*", "[::1]:*"]
allowed_origins = []
token_env = "DRAWING2CAD_HTTP_TOKEN"
```

The default endpoint is `http://127.0.0.1:8000/mcp`.
If the demo application already uses port 8000, select another MCP port and update the client URL.
The path is always `/mcp`.
The service does not supply a legacy `/sse` endpoint.

The default configuration selects stdio until you change `server.transport` or supply a CLI override.
The `--transport` option overrides the configured transport.
The `--host` and `--port` options apply only to Streamable HTTP.

## 4. Configure authentication when required

For the default loopback listener, a token is optional.
If the configured token variable exists, all HTTP requests require that token.
A non-loopback listener requires a token before startup.
An empty token or a token with whitespace causes startup to fail.

Generate a URL-safe random secret with your secret manager.
Supply it to the server through the variable named by `http.token_env`.
The default variable name is `DRAWING2CAD_HTTP_TOKEN`.

For an interactive PowerShell session, read the secret without showing it:

```powershell
$tokenInput = Read-Host 'MCP bearer token' -AsSecureString
$env:DRAWING2CAD_HTTP_TOKEN = [System.Net.NetworkCredential]::new('', $tokenInput).Password
Remove-Variable tokenInput
```

For an interactive Bash session:

```bash
read -r -s -p 'MCP bearer token: ' DRAWING2CAD_HTTP_TOKEN
export DRAWING2CAD_HTTP_TOKEN
```

Configure the client to send `Authorization: Bearer <token>` with the same secret.
Keep tokens outside committed files, model contracts, and test reports.
Restart the server after a token change.

## 5. Start and stop the server

On Windows:

```powershell
.\.venv\Scripts\python.exe -m drawing2cad_mcp --config drawing2cad-mcp.local.toml --transport streamable-http
```

On Linux or macOS:

```bash
.venv/bin/python -m drawing2cad_mcp --config drawing2cad-mcp.local.toml --transport streamable-http
```

Keep the process running while clients use the endpoint.
HTTP clients connect to this process; they do not start it.
For unattended operation, configure your service manager with the same command, working directory, environment, and file permissions.

Press `Ctrl+C` to stop an interactive server.
Before a planned restart, let active CAD operations finish.
After an interrupted call, inspect the model before you repeat that call.

## 6. Verify the MCP connection

1. Connect an MCP client to `http://127.0.0.1:8000/mcp`.
2. Supply the bearer token if the server requires it.
3. Initialize the MCP connection.
4. List the tools.
5. Call `drawing2cad_status` with these arguments:

```json
{
  "refresh_freecad": true
}
```

The result must contain `transport: "streamable-http"`.
The local catalog contains PDF, STEP inspection, capability, and managed workflow tools.
To expose development tools with the `freecad_` prefix, set both `freecad.enabled=true` and `server.expose_freecad_proxy=true`.
Raw proxy calls bypass managed evidence gates. They are hidden by default.
The upstream determines their number and schemas.

`freecad.connected` confirms the upstream MCP connection.
It does not prove that the FreeCAD addon can execute operations.
Use a suitable read-only FreeCAD tool from the discovered catalog to verify runtime access.
The `drawing_analysis` field reports the built-in engine, profile, schema version, and process timeout.
A browser page or ordinary GET request is not an MCP readiness test.

## 7. Connect LiteLLM

Start the MCP service before you register it in LiteLLM.
Choose one registration method below.
The address must be reachable from the LiteLLM process.

### Method A: management API or Admin UI

Use [litellm-mcp.example.json](litellm-mcp.example.json) as the request body for `POST /v1/mcp/server` on LiteLLM.
The example selects LiteLLM's transport value `"http"`.
It uses `auth_type: "none"` for a loopback MCP server without a token.
The JSON is not a complete LiteLLM configuration file.

1. Set `url` to the MCP endpoint reachable from LiteLLM.
2. For a token-protected endpoint, set `auth_type` to `bearer_token`.
3. Supply `auth_value` through the registration process with the MCP server's token.
4. Send the JSON with a permitted LiteLLM administration credential.
5. Assign the required MCP access in LiteLLM.
6. List the tools.
7. Call `drawing2cad_status` through LiteLLM.

The LiteLLM administration credential and the MCP bearer token have different purposes.
Do not put either credential in the committed example.
Do not use `auth_type: "api_key"` for this MCP; it sends a different header.

For UI registration, open **MCP Servers -> Add New MCP Server**.
Select **Streamable HTTP** and enter the corresponding values.
Configure database storage for UI registrations as required by your LiteLLM deployment.

### Method B: LiteLLM configuration file

For a loopback endpoint without a token, add this entry to LiteLLM's `config.yaml`:

```yaml
mcp_servers:
  drawing2cad:
    url: http://127.0.0.1:8000/mcp
    transport: http
    auth_type: none
```

For a token-protected endpoint, replace the authentication field with these fields:

```yaml
    auth_type: bearer_token
    auth_value: os.environ/DRAWING2CAD_HTTP_TOKEN
```

Supply the token variable to the LiteLLM process as well as the MCP process.
Apply the updated configuration through your LiteLLM deployment procedure.
Then list the tools and call `drawing2cad_status` through LiteLLM.
HTTP connections do not require `LITELLM_ENABLE_MCP_STDIO`.

Use the official [configuration reference](https://docs.litellm.ai/docs/mcp_config_reference)
and [API registration procedure](https://docs.litellm.ai/docs/mcp_public_internet#per-server-setting) for deployment-specific details.
The [authentication reference](https://docs.litellm.ai/docs/mcp/) describes the credential fields.

## 8. Use a network or container address

In a container, `127.0.0.1` identifies that container.
It does not identify the MCP service in another container.
This example assumes that you provide the container runtime and service name `drawing2cad`.

Replace the `[http]` section for an internal service on port 8000:

```toml
[http]
host = "0.0.0.0"
port = 8000
allowed_hosts = ["drawing2cad:8000"]
allowed_origins = []
token_env = "DRAWING2CAD_HTTP_TOKEN"
```

Supply the token before startup.
Use `http://drawing2cad:8000/mcp` from clients on that network.
Adapt the hostname and port to the actual deployment.
The bind address and the permitted Host header are separate settings.
Add any additional client-facing Host header explicitly.

For untrusted networks, put the service behind a TLS reverse proxy.
If a reverse proxy makes a loopback listener reachable remotely, configure its bearer token before startup.
Permit the Host header that the reverse proxy sends to this service.
Forward the Authorization header and streamed responses.
Set client and reverse-proxy timeouts to permit the expected CAD operation duration.

Requests without an Origin header are permitted.
Requests with an Origin header must match `allowed_origins`.
The empty list rejects all supplied origins.
This setting does not implement browser CORS support.

## 9. Load the workflow skill

Load the complete [drawing2cad skill folder](../skills/drawing2cad/SKILL.md) in the agent that uses the MCP.
Include its `references/` files.
Use your agent host's skill installation mechanism, or supply the same instructions and references through its supported context mechanism.
MCP registration supplies tools; it does not install or load the skill.

Keep authorized inputs and validation evidence separate from the skill package.
Follow the required sequence: dimensioned drawing, drawing review, editable 3D model, then STEP export.
HTTP transport does not change the evidence or review requirements.

## 10. Diagnose connection problems

| Symptom | Action |
|---|---|
| Connection refused | Verify that the process runs and the client uses the correct address and port. |
| Address already in use | Stop the conflicting service or select another port with `--port`. |
| Startup requests a token | Set the configured token variable before binding to a non-loopback address. |
| Startup rejects a token | Supply a nonempty ASCII bearer token without whitespace. |
| HTTP 401 | Supply exactly one valid Authorization header. Verify the server and client token values. |
| HTTP 421 | Add the actual Host header to `allowed_hosts`, including the port where applicable. |
| HTTP 403 | Compare the supplied Origin header with `allowed_origins`. |
| HTTP 404 | Use `/mcp`; the service has no `/sse`, download, or health route. |
| HTTP 413 | Reduce the request body below the 4 MiB limit. |
| No `freecad_*` tools | For the optional development profile, verify `server.expose_freecad_proxy`, `freecad.enabled`, the launcher, its arguments, and refreshed status. |
| Vector analysis rejects the page layout | Use the normal PDF image tools. The vector profile requires an unrotated, uncropped page with unit UserUnit. |
| `catalog_stale=true` | Restore the upstream connection, then refresh status and list the tools again. |
| FreeCAD tool fails after discovery | Verify addon access separately; upstream MCP discovery does not prove CAD execution. |
| PDF path rejected | Use an existing absolute server path inside a permitted input directory. |
| Poppler unavailable | Install `pdftoppm` or set its actual executable path in the configuration. |
| Timeout or lost response | Inspect the model and artifacts before you repeat a CAD operation. |

To return to stdio, configure the client to launch the existing command with `--transport stdio`.
That override also works when the TOML configuration selects HTTP.
Use the [stdio registration example](litellm-stdio.example.json) for LiteLLM's stdio configuration format.

## Operating limits

- One server process serializes individual upstream calls. Coordinate complete model workflows between agents that share the runtime.
- Run one server process per shared FreeCAD upstream until a worker coordinator exists.
- Stateless HTTP supplies no MCP session ID, result store, or stream resumption. CAD document state remains shared.
- Returned artifact paths refer to server files. MCP image blocks remain available to remote clients.
- Bearer authentication does not provide user-specific file isolation or restrict the upstream's Python execution permissions.
- The server does not automatically retry interrupted CAD calls.

## Validate the deployment

Verify the connection through each client that will use this deployment.
Test HTTP initialization, tool discovery, status, PDF rendering, and access to the selected FreeCAD runtime.
Verify token rejection and the permitted Host and Origin values.
Record actual results separately from this guide.
Transport tests do not prove headless CAD operation, editable STEP reconstruction, or semantic PMI.
See the [test instructions](README.md#tests-and-skill) for the automated suite.
Keep generated test outputs and reports outside version control.
