# Local model evaluation

Use the maintained client to run one bounded Ollama trial through the MCP interface.
It does not read PDF content or execute CAD directly.
It supplies the file selected by `skill_path` and the live tool schemas to the model.
It supplies the skill references for each workflow step and records the references in the trace.
The model can read other maintained references through the bounded skill_read tool.
Keep the complete maintained skill folder available to the client.

Run the client from an environment with the MCP package installed:

```text
python -m drawing2cad_mcp.local_model_client --plan /path/to/plan.json --output /path/to/new-output-directory
```

Put the plan and output in an ignored evaluation directory.
The output directory must not exist before the run.
Start the authenticated MCP HTTP service before the trial.
Set `DRAWING2CAD_HTTP_TOKEN` in the client environment. The plan names the variable, not its value.
Keep the token out of the plan, trace, and logs.

Example plan fields:

```json
{
  "server": {"url": "http://127.0.0.1:8000/mcp", "token_env": "DRAWING2CAD_HTTP_TOKEN"},
  "model": "local-model-name",
  "ollama_url": "http://127.0.0.1:11434",
  "skill_path": "../../skills/drawing2cad/SKILL.md",
  "source_path": "/inputs/authorized-drawing.pdf",
  "run_prefix": "localtrial",
  "step_budget": 45,
  "max_turns": 60,
  "max_continuations": 3,
  "model_timeout_seconds": 300,
  "total_timeout_seconds": 1200,
  "options": {"temperature": 0, "num_ctx": 32768, "num_predict": 8192},
  "think": true
}
```

Start a host HTTP server with the local-path development profile and an authorized PDF root.
See the [HTTP setup guide](../drawing2cad-mcp/STREAMABLE_HTTP.md#1-prepare-a-host-installation) for installation, configuration, and startup.
The Compose `mcp-http` service uses the domain profile; the command-line evaluation client still uses server paths and cannot use that profile.
Use a separate run prefix for each trial.
The source path must name an authorized PDF accessible to the server.
The client denies other PDF paths, other run prefixes, and tools outside its allowlist, including code execution tools.

The web backend calls `drive()` directly against the domain profile ([ADR 0018](adr/0018-agent-runner-in-the-web-backend.md)).
Its plan contains `source_id` and `source_sha256` instead of `source_path`.
In this mode, PDF tools and `part_create` sources must use that source ID and hash.
The allowlist also contains the drawing tools, `artifact_preview`, and run notes.
Complete-service release requires a current verified STEP and drawing pair. An explicitly requested STEP-only release records the actual drawing status.
The command-line client supports only `source_path`.

If Ollama has no published host port, replace `ollama_url` with:

```json
{"docker_bridge": {"container": "ollama-container", "image": "drawing2cad-mcp:m1"}}
```

The fixed HTTP bridge uses the Ollama container's network namespace.
It does not mount the Docker socket or write a helper script.
The operator needs access to Docker on the client host.
The CAD server remains a separate restricted container.

The client retains exact model requests and responses, tool requests and responses, images, questions, and timestamps.
It also retains the skill, plan, catalog, and initialization result.
It reports model duration and MCP duration separately.
Ollama timing and token fields remain in the summary when supplied.
Large tool text is explicitly truncated only in the model conversation; the full response remains in the trace.
If a text block repeats the exact structured JSON, the model receives one copy.
The raw trace retains both protocol representations.
MCP images are forwarded as image evidence to models with vision support.

Failed and denied tool requests count against the budget.
A required user question stops the trial and remains in the summary.
An answer without a tool call ends the trial only after a release or with a final report.
The first line of a final report is `FINAL REPORT`. The check removes the Markdown heading and emphasis characters (`#`, `*`, `_`, and the backtick) from the first line with text, and ignores letter case and spaces at the start and the end.
The line can continue after the marker with a colon, a hyphen, an en dash, or a space and more text, for example `FINAL REPORT: blocked because ...`.
After another answer without a tool call, the client sends a continuation message and the trial continues.
`max_continuations` (default 3, from 0 to 10) limits these messages. The value 0 sends no continuation message. After the limit, the status is `stopped_without_tool_call`, and the summary keeps the last model text in `final_text`.
The conversation keeps an empty answer as the text `(no answer)`. The trace keeps the actual response.
The trace records each continuation message as a `continuation` event. The summary counts them in `continuations`.
A transport failure stops the trial because mutation completion can be unknown.
The client does not infer successful release from the model's final text.
Any later model mutation or build request clears its release claim until another successful export. A drawing render or review does not clear it.

One completed run cannot rank models.
Record equivalent inputs, runtime limits, reasoning settings, assistance, and actual acceptance checks before comparison.
The client's `released` status identifies an MCP release response.
It does not prove full metric acceptance, AP242, independent STEP conformance, or opening in a target CAD system.

The protocol follows the official [Ollama tool calling guide](https://docs.ollama.com/capabilities/tool-calling)
and [chat API](https://docs.ollama.com/api/chat).
