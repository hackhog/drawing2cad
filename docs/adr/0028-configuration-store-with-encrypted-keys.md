# 28. Configuration store in SQLite with encrypted API keys

Date: 2026-10-19

## Status

Accepted. Replaces the storage decision of [ADR 0020](0020-agent-model-profiles-selected-in-the-web-ui.md) (`agent-profiles.json`). The other decisions of ADR 0020 stay valid. Not implemented yet.

## Context

The web backend stores the model profiles of the web UI and the active selection in `agent-profiles.json` in its data volume.
The file contains the API keys as plain text. Owner-only permissions (0600) protect the file in the container.
Each person with access to the volume, to the container, or to a backup can read the keys.

The run limits are fixed in `runner.py`: 45 tool requests, 60 turns, 300 s for each model call, 240 s for each tool call, 2,400 s for the run, and 80,000 characters for each tool result.
A small local model with a small context needs other limits than a hosted model.

The web UI changes this configuration while the service runs. The MCP domain store is a SQLite database of the MCP. It holds domain data, not settings of the web app.

## Decision

### Two kinds of configuration

- **Deployment configuration** stays in the environment (`.env`, Compose, `docker.toml`). It is necessary before a database opens, and a change needs a restart. Examples: ports, `DRAWING2CAD_DATA_DIR`, the MCP URL, the HTTP token, sandbox and CAD limits, the server maximums of the run limits, and the master key.
- **Runtime configuration** goes into a SQLite database of the web backend: `config.sqlite` in `DRAWING2CAD_DATA_DIR` (`/data/config.sqlite` in the container). It holds the model profiles of the web UI, the active profile, and the run limits of each profile.
- The configuration database is separate from the MCP domain store. The web app owns it.
- Profiles from `DRAWING2CAD_AGENT_*` variables stay read-only. The backend shows them next to the stored profiles. It does not copy them into the database. Their keys stay in the environment.

### Schema

```
profiles(id, name UNIQUE, provider, base_url, model, api, reasoning_effort, key_header,
         key_ciphertext, key_nonce, key_version, limits_json, revision, created_at, updated_at)
settings(key PRIMARY KEY, value_json, revision, updated_at)     -- for example active_profile
config_events(id, at, actor, action, target)                    -- audit, without values
schema_migrations(version, applied_at)
```

- The backend uses the Python `sqlite3` module in WAL mode with one writer.
- Each change states the expected revision of the profile or setting, as the run notes do. A stale revision fails with a conflict error, so two browser tabs cannot overwrite each other.
- Versioned migrations in the backend create and change the schema at start.
- `config_events` records who changed which profile or setting, and when. It never records a key or another value.

### Encrypted API keys

- The backend encrypts each API key from the web UI with AES-256-GCM (`cryptography`, which the backend lock file already contains) before it writes the key to the database.
- Each key has a new random 96-bit nonce. The associated data is the profile ID and the field name, so a ciphertext cannot be moved to another profile.
- The master key is 32 random bytes, Base64-encoded. It comes from `DRAWING2CAD_SECRET_KEY_FILE` (for example a Docker secret under `/run/secrets/`) or from `DRAWING2CAD_SECRET_KEY`. It is never in the database, in the data volume, in the image, or in a log.
- `key_version` identifies the master key. A rotation command decrypts each key with the old master key and encrypts it with the new one in one transaction.
- The backend decrypts a key only for the model call of a run or for the connection check. It does not keep decrypted keys in a log, a trace, a run record, or an API response. A response shows `key_set` only, as before.
- Without a master key, the web UI cannot save a profile with a key. The API returns an actionable error. Profiles from the environment still work.
- If the master key does not decrypt a stored key (wrong or lost master key), the profile shows `key_locked`. A run with that profile fails at start with an actionable error. The user enters the key again.

### Run limits for each profile

- A profile can set `step_budget`, `max_turns`, `model_timeout_seconds`, `call_timeout_seconds`, `total_timeout_seconds`, and `max_tool_text_chars`.
- A value that a profile does not set uses the server default. The defaults are the current values of `runner.py`.
- The deployment configuration sets the maximum of each limit. The API rejects a value above the maximum or below 1.
- A run records the limits that it used, next to the profile name, the model, and the reasoning effort.

### No migration

The new store does not read `agent-profiles.json`. After the change, users create their web UI profiles again. The backend ignores an old `agent-profiles.json`. Operators delete it from the data volume.

### Interfaces

The REST paths `/api/agent/profiles`, `/api/agent/active`, and `/api/agent/profiles/{name}/check` stay. Profile requests and views add the optional run limits and `revision`. The view adds `key_locked`. Older clients that send no revision get a conflict error only when a revision is stale.

## Consequences

- A copy of the data volume or a backup does not disclose API keys without the master key.
- The master key is a new secret for each deployment. A lost master key makes the stored keys unusable; users enter them again. A backup must store the master key separately from the data volume.
- Each run can use limits that fit its model, for example a smaller tool budget and longer model calls for a local model.
- Existing web UI profiles are lost at the change and must be created again.
- The backend has a schema to maintain, with migrations and tests.
- Encryption does not protect against a person who can read the process environment or the memory of the running backend.

## Tests for the implementation

- Round trip of a profile with a key: the database contains no plain text key, and no API response contains it.
- A ciphertext copied to another profile does not decrypt (associated data).
- Missing master key: saving a key fails with an actionable error; environment profiles still run.
- Wrong master key: the profile shows `key_locked`, and a run fails at start with an actionable error.
- Rotation re-encrypts all keys, and runs use them afterwards.
- A stale revision gives a conflict error.
- Limits above the server maximum or below 1 are rejected; unset limits use the defaults; a run records its limits.
- An existing `agent-profiles.json` is not read.

## Alternatives considered

| Alternative | Reason for rejection |
|---|---|
| Keep `agent-profiles.json` | Plain text keys in the volume and in backups |
| SQLite with plain text keys | The same exposure as the JSON file |
| Store the configuration in the MCP domain store | Couples settings of the web app to the domain data of the MCP |
| Only references to secrets (`key_ref`), no keys from the web UI | Users cannot add a key without access to the server configuration |
| External secret manager (for example Azure Key Vault) | Not necessary for the local and single-server deployment; possible later behind the same encryption interface |
| Migrate `agent-profiles.json` | Not necessary: few profiles, and the user decided against a migration |
