# 16. Agent runner in the web backend: Python loop, OpenAI-compatible endpoint, MCP over stdio

Date: 2026-10-17

## Status

Proposed. Refs #30, #26, #24. Builds on [ADR 0014](0014-headless-build123d-metric-prototype.md) and [ADR 0015](0015-web-ui-on-tanstack-shadcn-with-service-adapter.md).

## Context

The challenge requires that the 3D model is built exclusively through the MCP server, that the result is exported as STEP,
and that unclear information is flagged instead of guessed.
The web UI must start this work and show the result in step 4. A person must not copy files by hand.

A spike on 2026-10-17 tested the chain with the agent CLI `pi` (headless, only MCP tools, `azure/gpt-6.1-sol`, part "Splint"):

- 25 MCP calls, about 6 minutes, about 842,000 tokens, 0.37 USD.
- The agent followed the skill sequence, detected a scale conflict (printed lengths give 2:1, the title block shows 1:1), and built a solid.
- The release gate blocked `export_step` with `COVERAGE_INCOMPLETE`. The agent delivered a marked diagnostic STEP and open review flags.
- The envelope agreed with the reference part (68.5 × 13 mm); the volume was 29 % too large because the half-round section was missing.

`pi` uses a Node toolchain and user-specific provider extensions. These are not reproducible on a fresh machine.
The MCP package already contains a bounded, traced agent loop: `drive()` in `drawing2cad_mcp.local_model_client` (budget, timeouts,
path and run-prefix authorization, image forwarding). Its model call supports only local Ollama.

The shared run and artifact services of #24 do not exist yet. #26 forbids a mandatory hosted LLM provider.

## Decision

- **Agent loop:** the web backend runs `drive()` from `drawing2cad_mcp.local_model_client` with a new model call for
  OpenAI-compatible Chat Completions endpoints (Azure AI Foundry, OpenRouter, OpenAI, Ollama). The adapter translates messages,
  tool calls, tool results, and images between both formats. No Node toolchain and no CLI are necessary.
- **Tools:** the agent can call only the drawing2cad MCP tools that `drive()` permits. It has no shell, file, or code tools.
  `authorize_call` restricts PDF paths to the source of the run and part run IDs to the run prefix.
- **MCP server:** for each run, the backend starts `python -m drawing2cad_mcp` as a stdio subprocess with a generated configuration:
  the authorized root is the source store, the output root is the MCP store. CAD executes in the restricted build123d worker.
  The Linux sandbox is required; on other hosts, CAD calls fail with a structured error.
- **Result collection:** after the conversation, the runner calls `part_read` through the same MCP session.
  It takes the description, review items, validation checks, and the released or candidate STEP from the MCP state, checks their hashes,
  and converts the STEP to GLB for the preview. A STEP without release is a diagnostic artifact, never a released one.
- **Configuration:** `DRAWING2CAD_AGENT_BASE_URL`, `DRAWING2CAD_AGENT_MODEL`, and `DRAWING2CAD_AGENT_API_KEY` at runtime
  (for example, from a `.env` file that is not in Git). Optional: `DRAWING2CAD_AGENT_API_KEY_HEADER` (`api-key` for Azure AI Foundry)
  and `DRAWING2CAD_AGENT_REASONING_EFFORT`. Without the three required values, the image builds and starts, and the UI reports runs as unavailable.
- **Model selection:** the model must support function tools on Chat Completions. On Azure AI Foundry on 2026-10-17,
  `gpt-5.6-sol` and `gpt-5-4` did; `gpt-6.1-sol` and `gpt-6-luna` accepted function tools only through the Responses API.
  Support for the Responses API is a follow-up item.
- **Stored sources:** an agent run needs the PDF after the upload request. The backend keeps each source in its data directory
  (a Docker volume) until a user deletes it. Previously, the demo removed each upload after the request.
- **Execution:** one run at a time in a background worker. Further runs wait as `queued`. The UI polls the run.
  A restart marks unfinished runs as failed (`RUN_INTERRUPTED`).
- **Interim store:** the backend stores sources and run records in its data directory, mapped to the provisional contract types of ADR 0015.
  Part revisions, builds, and releases stay in the MCP store. When #24 publishes its services, they replace this store.

## Consequences

**Positive:**
- "Lauf starten" in the UI creates the model through the MCP and shows it in step 4 and on the run page.
- One Python stack. Any OpenAI-compatible provider, also a local Ollama model, can supply the model.
- Tests run with a mocked model. They do not use model budget.
- The trace of each run (model requests, tool calls, results) stays in the run directory.

**Negative:**
- Each real run costs model budget (about 0.4 USD and 6 minutes for a small part in the spike). The runner limits tool calls and time.
- The backend image becomes larger (build123d, OpenCascade) and needs network access to the model endpoint.
  The CAD worker keeps its own sandbox without network.
- The interim store duplicates a part of the #24 scope. It must be removed when #24 is available.
- `drive()` belongs to the MCP evaluation client. A change to its contract affects the web backend.
