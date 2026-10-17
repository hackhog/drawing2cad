# Streamable HTTP setup and operation

Use this guide to run `drawing2cad-mcp` as an HTTP service and connect an MCP client or LiteLLM.
The guide applies to version 0.5.0 and later versions with the same configuration interface.

The connection path is:

```text
Agent or LiteLLM -> HTTP /mcp -> drawing2cad-mcp -> PDF tools
                                            -> isolated build123d worker
                                            -> part revisions and STEP candidates
```

The M1 image includes PDF tools and a build123d worker.
The supplied `compose.mcp.yaml` profile uses stdio with network disabled.
It does not expose an HTTP port.
An HTTP deployment needs a configured listener and network access for the application.
The CAD child retains its own network and filesystem restrictions.

The HTTP transport does not yet supply persistent uploads or artifact downloads.
These belong to the M2 unified service.
The [existing demo](../app/README.md) has a separate UI and API; it does not host this MCP endpoint.
The current MCP executes CAD only through the headless build123d worker. It has no FreeCAD proxy.

## 1. Prepare the installation

Install Python 3.11 or later and Poppler with `pdftoppm`.
For CAD operations, use the supported Linux sandbox and install the package with its `cad` extra.
Prefer the maintained Docker image. Host installation must not bypass worker restrictions.
Use a client that supports MCP Streamable HTTP.

Run the commands from the repository root.
For an existing installation, update its dependencies and migrate its local configuration.
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
The operation reads the selected one-based page (default 1). It creates no persistent JSON export or colored overlay.

The original transport test used Windows and Python 3.12.
Use current run evidence for Docker and CAD results. Installation commands alone do not prove platform validation.

## 2. Configure server paths and tools

Edit `drawing2cad-mcp.local.toml` from the [configuration example](drawing2cad-mcp.example.toml).
Keep this deployment file outside version control.

| Setting | Action |
|---|---|
| `pdf.allowed_roots` | Set the permitted input directories on the server. |
| `pdf.output_root` | Set a writable output directory. Keep generated files in an ignored directory. |
| `pdf.pdftoppm` | Set the Poppler executable path, or omit this setting to use `PATH`. |
| `pdf.timeout_seconds` | Set the time limit for each Poppler or vector-analysis process. |
| `cad.enabled` | Enable only the maintained worker with its required sandbox. |
| `cad.allow_build_code` | Keep `false` unless verified in-memory execution is required. |
| `cad.timeout_seconds` and `cad.memory_mb` | Set finite limits for each worker process. |
| `cad.concurrency` | Set the maximum number of concurrent CAD workers in this server process. |

Remove the old `[freecad]` section and `server.expose_freecad_proxy` setting during migration.
The current configuration rejects both, including disabled values.
The generic example disables CAD execution. The Docker configuration enables its supported build123d worker.

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
{}
```

The result must contain `transport: "streamable-http"`.
The local catalog contains PDF, STEP inspection, part construction, review, and capability tools.
Legacy `workflow_*` evidence tools require explicit configuration; they are separate from current part revision gates.
The removed `freecad_*` tools are unavailable and return `UNKNOWN_TOOL`.
Transport readiness does not prove that CAD execution is available.
Call `cad_capabilities` and `cad_worker_probe`, then inspect their actual results.
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
Follow the current skill sequence for source evidence, part construction, validation, and STEP export.
The complete service also requires a dimensioned technical drawing. Its creation can precede or follow the model.
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
| Configuration rejects `freecad` fields | Remove the obsolete section and `server.expose_freecad_proxy`, including disabled values. |
| `CAD_DISABLED` | Enable `[cad]` only in a deployment with the supported Linux sandbox. |
| `SANDBOX_UNAVAILABLE` | Use the maintained Docker profile and inspect the worker probe. Do not use an unsandboxed fallback. |
| Vector analysis rejects the page layout | Use the normal PDF image tools. The vector profile accepts orthogonal page rotation, but still requires the supported full-page boxes and UserUnit 1. |
| PDF path rejected | Use an existing absolute server path inside a permitted input directory. |
| Poppler unavailable | Install `pdftoppm` or set its actual executable path in the configuration. |
| Timeout or lost response | Inspect the model and artifacts before you repeat a CAD operation. |

To return to stdio, configure the client to launch the existing command with `--transport stdio`.
That override also works when the TOML configuration selects HTTP.
Use the [stdio registration example](litellm-stdio.example.json) for LiteLLM's stdio configuration format.

## Operating limits

- Part mutations use explicit stored revisions. Coordinate changes to the same part.
- Per-run locks protect part operations. A competing call can return `RUN_BUSY`.
- Stateless HTTP supplies no MCP session ID or stream resumption. The part store is separate from transport state.
- Returned artifact paths refer to server files. MCP image blocks remain available to remote clients.
- Bearer authentication does not provide user-specific file isolation. CAD workers retain their separate sandbox restrictions.
- The server does not automatically retry interrupted CAD calls.

## Validate the deployment

Verify the connection through each client that will use this deployment.
Test HTTP initialization, tool discovery, status, PDF rendering, and the configured worker probe.
Test CAD construction and fresh STEP re-import separately.
Verify token rejection and the permitted Host and Origin values.
Record actual results separately from this guide.
Transport tests do not prove headless CAD operation, editable STEP reconstruction, or semantic PMI.
See the [test instructions](README.md#tests-and-skill) for the automated suite.
Keep generated test outputs and reports outside version control.
