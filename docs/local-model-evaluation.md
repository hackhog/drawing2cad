# Local model evaluation

Use the maintained client to run one bounded Ollama trial through the MCP interface.
It does not read PDF content or execute CAD directly.
It supplies the file selected by `skill_path` and the live tool schemas to the model.
It does not automatically load linked skill references.
Record this context limit when comparing trials.
For a complete-skill trial, supply an explicit instruction bundle and record the included reference hashes.
Do not include deprecated adapters or unrelated references in that bundle.

Run the client from an environment with the MCP package installed:

```text
python -m drawing2cad_mcp.local_model_client --plan /path/to/plan.json --output /path/to/new-output-directory
```

Put the plan and output in an ignored evaluation directory.
The output directory must not exist before the run.
The plan is trusted operator configuration. It can start the specified MCP command.
Do not accept an unreviewed plan from a model or an uploaded document.

Example plan fields:

```json
{
  "server": {"command": "docker", "args": ["run", "--rm", "-i", "drawing2cad-mcp:m1"]},
  "model": "local-model-name",
  "ollama_url": "http://127.0.0.1:11434",
  "skill_path": "../../skills/drawing2cad/SKILL.md",
  "source_path": "/inputs/authorized-drawing.pdf",
  "run_prefix": "localtrial",
  "step_budget": 45,
  "max_turns": 60,
  "model_timeout_seconds": 300,
  "total_timeout_seconds": 1200,
  "options": {"temperature": 0, "num_ctx": 32768, "num_predict": 8192},
  "think": true
}
```

Add the required source and storage mounts and container restrictions to the server arguments.
Use a separate volume and run prefix for each trial.
The source path must name the authorized PDF inside that server.
The client denies other PDF paths, other run prefixes, and tools outside its allowlist, including code execution tools.

If Ollama has no published host port, replace `ollama_url` with:

```json
{"docker_bridge": {"container": "ollama-container", "image": "drawing2cad-mcp:m1"}}
```

The fixed HTTP bridge uses the Ollama container's network namespace.
It does not mount the Docker socket or write a helper script.
The operator needs access to Docker on the client host.
The CAD server remains a separate restricted container.

The client retains exact model requests and responses, tool requests and responses, images, questions, and timestamps.
It also retains the skill, plan, catalog, initialization result, and server error log.
It reports model duration and MCP duration separately.
Ollama timing and token fields remain in the summary when supplied.
Large tool text is explicitly truncated only in the model conversation; the full response remains in the trace.
If a text block repeats the exact structured JSON, the model receives one copy.
The raw trace retains both protocol representations.
MCP images are forwarded as image evidence to models with vision support.

Failed and denied tool requests count against the budget.
A required user question stops the trial and remains in the summary.
A transport failure stops the trial because mutation completion can be unknown.
The client does not infer successful release from the model's final text.
Any later mutation or build request clears its release claim until another successful export.

One completed run cannot rank models.
Record equivalent inputs, runtime limits, reasoning settings, assistance, and actual acceptance checks before comparison.
The client's `released` status identifies an MCP release response.
It does not prove full metric acceptance, AP242, independent STEP conformance, or NX opening.

The protocol follows the official [Ollama tool calling guide](https://docs.ollama.com/capabilities/tool-calling)
and [chat API](https://docs.ollama.com/api/chat).
