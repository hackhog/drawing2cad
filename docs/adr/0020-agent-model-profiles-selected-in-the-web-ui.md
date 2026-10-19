# 20. Agent model profiles managed in the web UI

Date: 2026-10-18

## Status

Proposed. Extends [ADR 0018](0018-agent-runner-in-the-web-backend.md).
[ADR 0028](0028-configuration-store-with-encrypted-keys.md) replaces the storage in `agent-profiles.json` with a SQLite store and encrypted keys.

## Context

ADR 0018 configures one model endpoint for agent runs with the `DRAWING2CAD_AGENT_*` variables.
The team uses more than one endpoint, for example Azure AI Foundry and OpenRouter. A change of endpoint needs a change
to `.env` and a backend restart. This is not usable during a demo.

Users must also add an endpoint with its key without access to the server configuration.
A key in the browser storage or in a response of the server can leak.

## Decision

- **Environment profiles:** `DRAWING2CAD_AGENT_PROFILES` lists profile names, for example `Foundry,OpenRouter`.
  Each profile reads the variables `DRAWING2CAD_AGENT_<NAME>_*` with the suffixes of ADR 0018
  (`BASE_URL`, `MODEL`, `API_KEY`, `API`, `API_KEY_HEADER`, `REASONING_EFFORT`).
  Without the list, the unprefixed variables make the one profile `Standard`.
  A profile without base URL, model, or key is skipped with a warning, so the service builds and starts without keys.
  Environment profiles are read-only in the UI.
- **UI profiles:** the settings page creates, changes, and deletes profiles. The user selects a provider:
  - OpenRouter: fixed base URL `https://openrouter.ai/api/v1`, `Authorization: Bearer`, Chat Completions.
  - Azure AI Foundry: the server makes `https://<resource host>/openai/v1` from any URL of the resource,
    for example the target URI from the portal. The key header is `api-key`. The deployment name is the model.
  - OpenAI-compatible: base URL as entered, `Authorization: Bearer`.
- **Keys:** the browser sends a key only in the request that saves a profile. No response contains a key; the profile
  view has `key_set` only. A change without key keeps the stored key. The UI does not keep keys in browser storage.
- **Storage:** `agent-profiles.json` in the data directory holds the UI profiles and the active selection.
  The file is written atomically with owner-only permissions (0600). The data directory is not in Git.
- **Selection:** `PUT /api/agent/active` selects a profile, or `null` for no agent. The selection persists.
  Without a stored selection, the first profile is active.
- **Connection check:** `POST /api/agent/profiles/{name}/check` sends one short request without tools to the
  selected API. It checks the endpoint, the key, the model or deployment name, and the API with a few tokens.
- **Runs:** a new run gets the profile that the user selects at its start, else the active profile, when it is queued.
  The run start does not change the active profile. The run record contains the profile name and the model.
  A later selection or change does not change queued or running runs.
- **UI:** the sidebar footer opens the settings. While the settings are open, the sidebar lists the settings sections
  in place of the drawings. The first section is `KI-Modell`; later settings add sections.

## Consequences

- A user can add an endpoint and change the model for the next run without a restart.
  The profiles and the selection apply to all users of one backend.
- Keys of UI profiles are stored as plain text in the data volume of the server. Protection depends on the file
  permissions and on access to the volume. This is acceptable for the demo; a production service needs a secret store.
- The profile and check endpoints have no authentication. The demo backend is reachable only through the frontend
  container (ADR 0012). A public deployment needs authentication before it offers these endpoints.
