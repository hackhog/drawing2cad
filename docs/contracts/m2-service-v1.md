# M2 shared service contract

Contract identifier: `drawing2cad.domain/1`.
The M2 MCP part supplies the shared service and MCP adapter. The M2 web part supplies the web adapter and frontend.

## Application boundary

Create one `DomainService(settings)` for the backend application.
Call `start()` once at application startup. Call `close()` during shutdown.
Shutdown waits for active operations. It does not cancel their effects.
Both adapters call `service.call(context, operation, arguments)`.

Construct `AccessContext(subject)` from a verified server identity.
Never accept the identity from tool arguments or an unverified request header.
Cross-principal lookups return `NOT_FOUND`, or `JOB_NOT_FOUND` for jobs.
The current MCP uses one configured deployment principal.
Its bearer token does not provide user-level tenant authentication.
The web adapter must supply its own verified identity mapping.
Do not duplicate storage or release rules in the web adapter.

## Schemas and fixtures

`domain_schema` returns input schemas and core response-record schemas.
Python adapters can import the same function from `drawing2cad_mcp.domain_contracts`.
`part_schema` defines the editable part. `drawing_schema` defines drawing geometry and dimensions.
Use the synthetic [record fixtures](fixtures/m2-records.json) for client development.
Their placeholder hashes do not identify real files.
Contract tests validate these fixtures and actual service records.

## Sources and transfers

Use `upload_begin`, `upload_chunk`, and `upload_complete` to transfer PDF bytes.
The default source limit is 20 MiB. Each decoded chunk can contain up to 512 KiB.
The HTTP request limit is 4 MiB, including JSON and base64 overhead.
Read the configured limits from `drawing2cad_status`.

Supply the complete byte count and SHA-256 at upload start.
Supply the committed byte offset with each chunk.
An exact repeated chunk is idempotent. A conflicting retry fails.
Use `upload_get` to recover the committed offset after a lost response.
Completion verifies size, SHA-256, and basic PDF markers.
It returns `status=uploaded` and `pdf_validation=not_tested`.
Completion does not certify PDF structure or source accuracy.
PDF tools take `source_id`. Filenames are display metadata, not paths.
Input size and PDF concurrency are bounded. The PDF parser does not have the CAD worker's sandbox guarantees.

## Runs, revisions, and notes

`part_create` binds source IDs, hashes, and construction or verification roles.
Evidence uses those IDs and hashes. Verification sources cannot supply construction values.
Run labels are scoped to the authenticated principal.
Mutations require the current `expected_revision`.
Named parameters and ordered features remain in the versioned JSON description.
Notes have an independent revision counter. Use revision zero for the first note.
A stale note update returns `REVISION_CONFLICT` and preserves the current note.

The web run response includes `projection`, separate from release and generated-PDF verification.
It presents the newest `projection_report` of the current part revision and the preceding `projection_overlay` of that check.
The MCP registers these artifacts together in sequence; the report does not contain an overlay link.
The web adapter stops its image lookup at the previous report. It never substitutes an earlier check's overlay.
The response records report and overlay IDs, source page, sheet size, view regions, measurements, limits, and per-metric results.
Measurements and limits retain the MCP values. No release gate or numerical limit changes in the web adapter.
The overall state is `matches` when all current views pass, `deviates` when a view fails, and `not_tested` without complete current evidence.
An older revision, invalid binding, or unreadable newest report gives `not_tested`, with its reason.
Active runs show no completed projection result. Simulated service responses mark their data as simulated.

## Jobs and recovery

Use `job_submit` for build, drawing-render, or STEP-release operations.
Supply an idempotency key and the complete operation arguments.
Reuse a key only for an identical request.
Ownership and expected revision are verified at submission and execution.

| State | Meaning |
|---|---|
| `queued` | Accepted; execution has not started. |
| `running` | A worker has claimed the job. |
| `cancel_requested` | Cancellation was requested after execution started. |
| `succeeded` | The operation returned a successful result. |
| `failed` | The operation failed. |
| `cancelled` | Execution did not start, or the dispatcher confirmed cancellation. |
| `interrupted` | The service restarted after an uncertain active operation. |

Cancellation is cooperative. It does not roll back a completed model or artifact.
Active operations can finish after cancellation is requested.
After restart, queued jobs resume. Previously active jobs become `interrupted` and are not replayed automatically.
Read run state and artifacts before submitting a replacement operation.
Only one dispatcher process can own a job store.
The default admission limit is 128 active jobs. A full queue returns `JOB_QUEUE_FULL`.
Aggregate disk quotas and completed-job retention limits are not implemented.

## Drawings and release

The adapter accepts supplied view geometry, dimensions, sections, notes, and uncertainty markers.
It creates native DXF dimensions and renders the same drawing into PDF.
Use `drawing_derive_views` for supported model-derived views and sections in DrawingSpec 2.0.
Source accuracy, projection completeness, and drawing-to-solid equivalence require an identified review.
Automatic layout checks do not prove those properties.

Bind each drawing to the part revision and canonical description hash.
Use `drawing_validate`, `drawing_render`, `drawing_verify`, and `artifact_preview` before `drawing_review`.
The final review also binds the validated model candidate.
Complete-service delivery uses `export_step` with `delivery: "complete_service"`.
It requires an accepted drawing verified against the released STEP bytes and a current pair binding.
An explicitly requested STEP-only delivery uses `delivery: "step_only"`, the API default.
It records the drawing status without claiming a verified pair.
New release records use release `schema_version: 2` and profile `validated_geometry_step` for AP214.
The AP242 profile remains `validated_ap242_application_construction`.
The former `metric_acceptance` field has no per-run acceptance equivalent and is not written in new releases.
Stored releases without a release schema version remain readable with their original fields, including profile `validated_prototype_step`.
No new acceptance or pair claim is inferred from these legacy fields.
See the [release compatibility guide](../../drawing2cad-mcp/README.md#release-record-compatibility) for reader migration.
Use `pair_current: true` on the final `part_read` to establish current complete-service acceptance.
Drawing, verification, and review changes make an earlier complete-service pair stale while retaining its release record.
Parameter changes and rebuilds invalidate the applicable release evidence.
Historical artifacts remain readable, but cannot authorize release of a later revision.

The current geometry export is AP214. AP242 construction and semantic PMI belong to M3.
Record target-CAD opening and independent STEP analysis separately.
An unperformed test remains `not_tested`.

## Artifacts and errors

Artifacts have immutable IDs, hashes, media types, roles, run IDs, and revisions.
Use `artifact_list`, `artifact_get`, and `artifact_read` for delivery.
Each content read verifies stored bytes against the recorded hash.
Assemble chunks on the client, then verify the complete SHA-256.
Use `artifact_preview` for supported PDF or PNG inspection.

Public records omit private paths and raw process logs.
Service failures use `DomainError(code, message, target?, next_action?)`.
Adapters must not expose unexpected exception text.
Keep the actual error code in client logs. Use `next_action` when supplied.
Domain run events and CAD events are separate evidence streams.
They do not constitute a complete log of all MCP requests.

This contract does not define HTTP routes or browser authentication flows.
Those adapters belong to the M2 web part.
