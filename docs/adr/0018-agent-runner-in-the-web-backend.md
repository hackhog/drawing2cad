# 18. Agent runner in the web backend on the shared domain service

Date: 2026-10-17

## Status

Proposed. Builds on [ADR 0014](0014-headless-build123d-metric-prototype.md), [ADR 0015](0015-web-ui-on-tanstack-shadcn-with-service-adapter.md),
and [ADR 0016](0016-shared-domain-service-and-drawing-delivery.md).

## Context

The challenge requires that the 3D model is built exclusively through the MCP server, that the result is exported as STEP,
and that unclear information is flagged instead of guessed.
The web UI must start this work and show the result in step 4. A person must not copy files by hand.

A spike on 2026-10-17 tested the chain with the agent CLI `pi` (headless, only MCP tools, part "Splint"):

- 25 MCP calls, about 6 minutes, about 842,000 tokens, 0.37 USD.
- The agent followed the skill sequence, detected a scale conflict (printed lengths give 2:1, the title block shows 1:1), and built a solid.
- The release gate blocked `export_step`. The agent delivered open review flags.

`pi` uses a Node toolchain and user-specific provider extensions. These are not reproducible on a fresh machine.
The MCP package contains a bounded, traced agent loop: `drive()` in `drawing2cad_mcp.local_model_client`.

The [shared service contract](../contracts/m2-service-v1.md) requires one `DomainService` for each backend application,
one dispatcher for each job store, and no storage or release rules in the web adapter.
The web adapter supplies the trusted identity. The MCP uses one configured deployment principal.

## Decision

- **One application:** the web backend creates one `drawing2cad_mcp.server.Application` with the domain profile
  below `DRAWING2CAD_DATA_DIR`. It mounts `create_http_app(application)`, which serves `/mcp`, and runs its lifespan
  in the FastAPI lifespan. This lifespan starts and stops the domain service.
- **Identity:** web routes use `application.access_context`, the configured `domain.principal`. Agent runs through `/mcp`
  use the same principal, so they can read web uploads. The local and demo deployments have no login.
- **Web routes:** routes call `application.domain.call(context, operation, arguments)`. Uploads use `upload_begin`,
  `upload_chunk`, and `upload_complete`. Downloads use `artifact_get` and `artifact_read` and verify the SHA-256.
  The analysis uses `drawing_extract` and `pdf_render_page`. A domain error becomes an HTTP status with its code.
  The web API deletes a source with its web run records through the trusted `source_delete` method; an active run blocks it.
  Agents have no delete tool.
- **Agent loop:** a background worker runs `drive()` with a model call for OpenAI-compatible Chat Completions or
  Responses API endpoints (Azure AI Foundry, OpenRouter, OpenAI, Ollama). It connects to the mounted `/mcp` endpoint over loopback with the
  Streamable HTTP client. There is no subprocess and no second dispatcher. The MCP endpoint accepts loopback hosts only;
  the frontend proxy forwards only `/api/`.
- **Source scope:** `drive()` accepts an uploaded source ID and its SHA-256 instead of a local path. `authorize_call`
  restricts PDF tools and `part_create` sources to this source, and part run IDs to the run prefix. In this mode, the agent
  can also use the drawing tools, `artifact_preview`, and run notes, because `export_step` needs a reviewed drawing.
  The local-path mode does not change.
- **Results:** the final agent report is the first text of the note of the part run (`notes_update`). The report also stays
  in the agent trace (`summary.json`), and the UI shows it from there. Users can then change the note with its revision
  (`notes_read`, `notes_update`) to add review information. Part state, review items, and artifacts come from `part_read`
  and `artifact_list` for each request. Only a released STEP is a domain artifact,
  so the web UI shows no unreleased model. The 3D preview converts the released STEP to GLB for display only.
- **Web run record:** a small record holds the job state, the agent trace, and the domain part run ID. It copies no domain data.
  One run executes at a time. A restart marks unfinished runs as failed (`RUN_INTERRUPTED`).
- **Failed tool requests:** `drive()` returns each tool error to the model, with one short corrective instruction after
  a deterministic failure. It compares requests by tool name and canonical arguments (key order and call IDs do not
  count) and by the server state, which changes after each successful call that changes the part, its drawings, its
  release, or its note. An identical request with the same server state is blocked before execution, and the run stops as `no_progress` (`AGENT_NO_PROGRESS` with the tool, the field,
  and the repeat count). Transient errors, for example `WORKER_TIMEOUT`, and successful repeated calls are not blocked.
  The client invents no replacement values; interpretation, assumptions, and corrections stay with the model.
  A deadline that ends during model inference or a tool call gives `time_budget_reached` (`AGENT_TIME_BUDGET` when no STEP release exists; a built model stays readable).
- **Answers without a tool call:** such an answer ends the run only after a STEP release or with a final report. The first line of a
  final report is `FINAL REPORT`; the system message and the skill name this marker. After another answer without a tool call,
  `drive()` sends a continuation message and the run continues. The profile limit `max_continuations` (default 3) limits these
  messages. After the limit, the run stops as `stopped_without_tool_call` (`AGENT_NO_TOOL_CALL` when no STEP release exists).
- **Configuration:** `DRAWING2CAD_AGENT_BASE_URL`, `DRAWING2CAD_AGENT_MODEL`, and `DRAWING2CAD_AGENT_API_KEY` at runtime
  (for example, from a `.env` file that is not in Git). Optional: `DRAWING2CAD_AGENT_API_KEY_HEADER` (`api-key` for Azure AI Foundry)
  and `DRAWING2CAD_AGENT_REASONING_EFFORT`. Without the three required values, the image builds and starts, and the UI reports runs as unavailable.
- **Model selection:** the model must support function tools on the selected API (`DRAWING2CAD_AGENT_API`, `chat` by default,
  or `responses`). On Azure AI Foundry on 2026-10-17, `gpt-5.6-sol` and `gpt-5-4` did on Chat Completions;
  `gpt-6.1-sol` and `gpt-6-luna` accepted function tools with reasoning only through the Responses API.
  The Responses requests are stateless (`store: false`) and do not send reasoning items of earlier turns again.
  Function tools use `strict: false`, because the MCP schemas are not written for strict validation.
- **Model transport:** the official `openai` Python SDK sends the requests, with one client and `base_url` for each
  profile. It is the HTTP transport only. `drive()` keeps the agent loop, the authorization guards, the budgets, and the
  trace format, so the backend uses no agent framework. The SDK retries are off. The model call keeps its own retry
  policy with one deadline for each turn, and a response size limit of 8 MiB. One attempt can use half of the turn deadline
  (`model_timeout_seconds`), at least 120 s, so that a slow model can answer and one retry fits after a stalled attempt.

## Consequences

**Positive:**
- "Lauf starten" in the UI creates the model through the MCP. Web routes and agents use the same storage and release gates.
- Other MCP clients can use the same deployment and see the same sources and artifacts.
- One Python stack. Any OpenAI-compatible provider, also a local Ollama model, can supply the model.
- Tests run with a scripted model against the real mounted endpoint. They do not use model budget.

**Negative:**
- Each real run costs model budget (about 0.4 USD and 6 minutes for a small part in the spike). The runner limits tool calls and time.
- A run without release shows no 3D model, because the domain service registers only released STEP files.
- The backend image is larger (build123d, OpenCascade) and needs network access to the model endpoint.
  The CAD worker keeps its own sandbox without network.
- `drive()` belongs to the MCP evaluation client. A change to its contract affects the web backend.
- Uploaded sources stay in the data volume until the volume is removed.
