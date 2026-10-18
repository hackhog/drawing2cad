# 20. Agent model profiles selected in the web UI

Date: 2026-10-18

## Status

Proposed. Extends [ADR 0018](0018-agent-runner-in-the-web-backend.md).

## Context

ADR 0018 configures one model endpoint for agent runs with the `DRAWING2CAD_AGENT_*` variables.
The team has more than one endpoint, for example Azure AI Foundry and OpenRouter. A change of endpoint needs a change
to `.env` and a backend restart. This is not usable during a demo.

The browser must not get endpoints or API keys. An input field for a base URL and a key in the UI would send the key to the browser.

## Decision

- **Profiles on the server:** `DRAWING2CAD_AGENT_PROFILES` lists profile names, for example `Foundry,OpenRouter`.
  Each profile reads the variables `DRAWING2CAD_AGENT_<NAME>_*` with the suffixes of ADR 0018
  (`BASE_URL`, `MODEL`, `API_KEY`, `API`, `API_KEY_HEADER`, `REASONING_EFFORT`).
  A name starts with a letter and has only letters and digits, because it is part of the variable names.
- **Compatibility:** without `DRAWING2CAD_AGENT_PROFILES`, the unprefixed variables make the one profile `Standard`.
- **Build and start without keys:** a profile without base URL, model, or key is skipped with a warning.
  Without a complete profile, the service starts and reports runs as unavailable.
- **Selection:** the backend keeps the active profile in memory. The first complete profile is active at start.
  `GET /api/agent/profiles` returns the name, model, and API type of each profile and the active name.
  `PUT /api/agent/profiles/active` selects a profile, or `null` for no agent.
- **Runs:** a new run gets the active profile when it is queued. The run record contains the profile name and the model.
  A later selection does not change queued or running runs.
- **UI:** the sidebar footer has a settings entry that shows the active profile and model. The settings dialog lists
  the profiles and `Lokal, ohne KI`. The simulated service has no profiles.

## Consequences

- A user can change the model for the next run without a restart. The selection applies to all users of one backend.
- The selection is not persistent. After a restart, the first complete profile is active again.
- API keys stay in the server environment. The browser gets only profile names, models, and API types.
- A selection endpoint without authentication lets each user of the web UI change the model. The demo backend is
  reachable only through the frontend container (ADR 0012), so this is acceptable for the demo.
