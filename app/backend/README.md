# drawing-demo backend

This service supplies the web API ([ADR 0012](../../docs/adr/0012-demo-app-as-frontend-and-backend-container.md), [ADR 0018](../../docs/adr/0018-agent-runner-in-the-web-backend.md)).
It creates one shared domain service (`drawing2cad_mcp.server.Application`, domain profile) for the process.
Web routes call this service. The backend also mounts its MCP endpoint at `/mcp` for agent runs.
It passes review flags and user decisions through and converts STEP files to GLB for display.
The frontend container serves the UI and forwards only `/api` requests to this service.
The `/mcp` endpoint accepts loopback hosts only. The backend does not serve static UI files.

## Build, test, and run

Use Python 3.12 or later, but earlier than 3.15, [Poetry](https://python-poetry.org/) 2.4.1, and Poppler.
CI and the image use Python 3.12 and Poetry 2.4.1.
The lock file covers Python versions earlier than 3.15, because build123d 0.13.0 requires them.

```bash
cd app/backend
poetry install
poetry run pytest
poetry run drawing-demo
```

`poetry install` installs the locked dependencies and the dev group (pytest, Playwright).
For a production installation without the dev group, use `poetry install --only main`.

Put `pdftoppm` on `PATH`, or set `DRAWING2CAD_PDFTOPPM` to its executable path.
The health endpoint is `http://127.0.0.1:8000/api/health`.
Sample-based tests are skipped when their source drawings are absent.
`tests/test_browser.py` drives the built UI in Google Chrome (Playwright) against this backend, its domain service, and its mounted MCP endpoint, with a scripted model.
It covers upload, run start, job state, review, parameter display, the run note with a revision conflict, run file download, and error messages.
It does not cover a released STEP or drawing download, because the scripted model does not build a model.
Run `npm run build` in `app/frontend` first. Without the UI build or Google Chrome, these tests are skipped.

The MCP package is a non-editable path dependency with the `cad` extra.
`poetry install` does not install a changed MCP source again while the version stays the same.
After a change in `../../drawing2cad-mcp`, remove the installed copy and install it again:

```bash
poetry run python -m pip uninstall -y drawing2cad-mcp
poetry install
```

The backend lock records the version and the dependencies of the MCP package.
After a change to the version or the dependencies of the MCP package, update the backend lock:

```bash
poetry lock
poetry install
```

Commit the changed `poetry.lock`. The backend CI job stops if the lock is out of date.

## API

| Method | Path | Response |
|---|---|---|
| `GET` | `/api/health` | Status and `drawing2cad_mcp_version` |
| `GET` | `/api/capabilities` | Available functions; `runs` is true only with an active model profile; `agent_profile` and `agent_model` name it |
| `GET` | `/api/agent/profiles` | Model profiles (`name`, `provider`, `origin`, `base_url`, `model`, `api`, `reasoning_effort`, `key_set`, `key_locked`, `limits`, `revision`), the `active` profile with `active_revision`, `master_key_set`, and the default and maximum run limits; never a key ([ADR 0020](../../docs/adr/0020-agent-model-profiles-selected-in-the-web-ui.md), [ADR 0028](../../docs/adr/0028-configuration-store-with-encrypted-keys.md)) |
| `PUT` | `/api/agent/active` | Select the profile for new runs: `name`, or `null` for no agent, and optional `revision` (422 `UNKNOWN_PROFILE`, 409 `REVISION_CONFLICT`) |
| `PUT`/`DELETE` | `/api/agent/profiles/{name}` | Create, change, or delete a UI profile: `provider` (`openrouter`, `azure`, `openai`), `endpoint`, `model`, `api`, `api_key` (empty keeps the stored key), `reasoning_effort`, `limits`, and optional `revision` (body for `PUT`, query parameter for `DELETE`). Environment profiles are read-only (409 `PROFILE_READ_ONLY`). Without a master key, a key cannot be saved (503 `SECRET_KEY_MISSING`) |
| `POST` | `/api/agent/profiles/{name}/check` | Send one short request without tools to the endpoint; returns `ok`, `message`, `latency_ms` |
| `POST` | `/api/sources` | Upload a PDF (multipart field `file`) to the domain service; returns the source record |
| `GET` | `/api/sources`, `/api/sources/{id}` | Source records: opaque ID, filename, size, SHA-256 |
| `GET` | `/api/sources/{id}/analysis` | Drawing data, `page_png`, `page_px_per_mm`, review flags, and provenance |
| `GET` | `/api/sources/{id}/flags` | Review flags with the decisions of the user ([ADR 0019](../../docs/adr/0019-review-flag-decisions-in-the-domain-service.md)) |
| `PUT` | `/api/sources/{id}/flags/{flag_id}` | Record a decision: `action` (`ignore`, `classify`, `correct`, `reopen`), `stroke_class`, `text`, `note` |
| `GET` | `/api/feedback` | All flag decisions as a JSON download for the developers of the analysis |
| `GET` | `/api/measurements` | Review measurements of all sources, oldest first: review time, optional manual-effort estimate, and estimator |
| `POST` | `/api/sources/{id}/measurements` | Record one review: `review_seconds`, optional `manual_hours` and `estimator` (`drafter`, `guest`, `team`) |
| `GET`/`POST` | `/api/sources/{id}/runs` | List runs / queue an agent run with the active profile and its run limits (503 without active profile, 409 `PROFILE_KEY_LOCKED` when the stored key cannot be decrypted) |
| `DELETE` | `/api/sources/{id}` | Delete a source with its web run records and measurements (409 `RUN_ACTIVE` while a run is active) |
| `GET` | `/api/runs/{id}` | Phase, job, part, review, artifacts, and the agent report |
| `GET`/`PUT` | `/api/runs/{id}/note` | Read / replace the run note; `PUT` takes `expected_revision` and `text` (409 on a stale revision or an active run) |
| `GET` | `/api/runs/{id}/files`, `/api/runs/{id}/archive` | Run record and agent trace, as single files or a ZIP archive |
| `GET` | `/api/artifacts/{id}/content` | Artifact content by opaque ID, verified against its SHA-256 |
| `POST` | `/api/model` | GLB for a STEP file that the user supplies (display only) |

The PDF upload limit is 20 MiB. The STEP upload limit is 50 MiB.
Errors use status 413 for excess size, 415 for an incorrect format, 422 for processing failures, and 404 for unknown or malformed IDs.
Structured errors have `code`, `message`, `field`, and `recovery` in `detail`. A domain error keeps its code.
A disagreement between the analysis and render source hashes returns status 422.

The domain store is in the data directory (`DRAWING2CAD_DATA_DIR`, default `.data`).
The backend keeps the analysis of up to 32 sources in memory, so a page is not rendered again for each request.
Returned records contain hashes and opaque IDs, never server paths.

The analysis uses page 1 of the BCT/NX profile.
It supplies candidate text and sheet geometry, not verified part dimensions or general OCR.
See [ADR 0013](../../docs/adr/0013-vector-analysis-in-mcp.md) for the analysis limits.
The STEP conversion is for display only. It does not verify AP242, editable construction, or semantic PMI.

## Agent runs

See [ADR 0018](../../docs/adr/0018-agent-runner-in-the-web-backend.md).
A run executes one bounded agent conversation (`drive()` from `drawing2cad_mcp.local_model_client`) in a background thread.
The agent connects to the mounted `/mcp` endpoint and can call only its permitted tools, with the uploaded source ID as its only input.
The runner stores the final agent report as the first text of the note of the part run. Users can change this note later.
The run view shows the report from the agent trace (`summary.json`), so a changed note does not change the report.
Part state, review, and artifacts come from the domain service for each request.
A built model without release is a finished run with release state `blocked`. Only a released STEP is an artifact.

| Variable | Required | Meaning |
|---|---|---|
| `DRAWING2CAD_AGENT_PROFILES` | no | Names of more than one model profile, for example `Foundry,OpenRouter`. Each profile reads `DRAWING2CAD_AGENT_<NAME>_*` with the suffixes below. Without this list, the unprefixed variables make the profile `Standard` |
| `DRAWING2CAD_AGENT_BASE_URL` | for runs | OpenAI-compatible base URL, for example `https://<resource>.cognitiveservices.azure.com/openai/v1` |
| `DRAWING2CAD_AGENT_MODEL` | for runs | Model or deployment name; it must support function tools on the selected API |
| `DRAWING2CAD_AGENT_API` | no | `chat` (Chat Completions, default) or `responses` (Responses API, for example for `gpt-6.1-sol`) |
| `DRAWING2CAD_AGENT_API_KEY` | for runs | API key; never in Git |
| `DRAWING2CAD_AGENT_API_KEY_HEADER` | no | `Authorization` (Bearer, default) or `api-key` (Azure AI Foundry) |
| `DRAWING2CAD_AGENT_REASONING_EFFORT` | no | Sent as `reasoning_effort` (Chat Completions) or `reasoning.effort` (Responses API) |
| `DRAWING2CAD_AGENT_STEP_BUDGET`, `_MAX_TURNS`, `_MODEL_TIMEOUT_SECONDS`, `_CALL_TIMEOUT_SECONDS`, `_TOTAL_TIMEOUT_SECONDS`, `_MAX_TOOL_TEXT_CHARS` | no | Run limits of an environment profile, with the same profile prefix as above, for example `DRAWING2CAD_AGENT_LITELLM_STEP_BUDGET`. Unset limits use the defaults |
| `DRAWING2CAD_RUN_MAX_<LIMIT>` | no | Maximum of a run limit for all profiles, for example `DRAWING2CAD_RUN_MAX_STEP_BUDGET` (defaults: step budget 100, turns 150, model call 1800 s, tool call 900 s, run 14400 s, tool result 400000 characters) |
| `DRAWING2CAD_SECRET_KEY_FILE` | for UI keys | File with the master key, for example a Docker secret under `/run/secrets/`. It has priority over `DRAWING2CAD_SECRET_KEY` |
| `DRAWING2CAD_SECRET_KEY` | for UI keys | Master key: 32 random bytes, Base64-encoded. It encrypts the API keys of UI profiles with AES-256-GCM. Without it, the UI cannot save keys; environment profiles still work |
| `DRAWING2CAD_DATA_DIR` | no | Data directory; `/data` in the container |
| `DRAWING2CAD_SKILL_PATH` | no | Skill file for the agent; the image sets it |
| `DRAWING2CAD_MCP_URL` | no | MCP endpoint for agent runs; default `http://127.0.0.1:$PORT/mcp` |
| `DRAWING2CAD_HTTP_TOKEN` | no | Bearer token for `/mcp`; the runner sends it |
| `DRAWING2CAD_CAD_ENABLED` | no | `1` (default) enables CAD operations of the domain service |

CAD execution requires the Linux sandbox of the MCP worker. Use Docker Compose for agent runs on macOS or Windows.
Tests use a scripted model and do not call a model endpoint.

## Configuration store and master key

The backend stores UI profiles, their run limits, and the active profile in `config.sqlite` in `DRAWING2CAD_DATA_DIR`
([ADR 0028](../../docs/adr/0028-configuration-store-with-encrypted-keys.md)). It does not read a former `agent-profiles.json`.
The database contains each API key only encrypted. The master key is never in the database, the data volume, or the image.

Make a master key once and keep it outside the data volume, for example in a password manager:

```bash
python -c "import base64, os; print(base64.b64encode(os.urandom(32)).decode())"
```

Supply it as `DRAWING2CAD_SECRET_KEY` (for example in the `.env` file, which is not in Git) or as a file in
`DRAWING2CAD_SECRET_KEY_FILE`. A backup of the data volume needs the master key separately.
If the master key changes, profiles with keys show `key_locked`; enter their keys again, or rotate the keys first.

To rotate the master key, write the old and the new key into two files and run:

```bash
docker compose -f deployment/compose.local.yaml exec backend python -m drawing_demo.agent.config_store rotate --database /data/config.sqlite --old-key-file /run/secrets/old.key --new-key-file /run/secrets/new.key
```

Then set the new key in the deployment and restart the backend. The command changes no key if the old key is wrong.
After the rotation, a backend that still has the former master key saves no new key (409 `MASTER_KEY_CHANGED`) until it restarts.

If a master key is lost, its stored keys cannot be decrypted. Remove them, then enter the keys of the UI profiles again:

```bash
docker compose -f deployment/compose.local.yaml exec backend python -m drawing_demo.agent.config_store forget-keys --database /data/config.sqlite --yes
```

## Structure

- `src/drawing_demo/api.py`: HTTP routes, analysis through the domain service, and STEP display conversion.
- `src/drawing_demo/service.py`: the domain service of the process, its MCP endpoint, uploads, and verified artifact reads.
- `src/drawing_demo/jobs.py`: web run records (job state, agent trace, domain part run ID).
- `src/drawing_demo/measurements.py`: review measurements per source (review time, manual-effort estimate).
- `src/drawing_demo/agent/`: model adapter (`model.py`), runner (`runner.py`), model profiles and run limits (`profiles.py`), the SQLite configuration store with encrypted keys (`config_store.py`), and mapping of domain results to the contract (`mapping.py`).
- `Dockerfile`: Python runtime with the MCP package, build123d, the sandbox libraries, Poppler, and the agent skill. Poetry installs the locked runtime dependencies.

The Docker build context is the repository root because the MCP package is a path dependency.
The image excludes input drawings and local configuration.
In Compose, the backend has no published host port.
The frontend reaches the API through the Compose network.
