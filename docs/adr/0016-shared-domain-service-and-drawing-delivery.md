# 16. Use shared domain services for uploads, jobs, and drawing delivery

Date: 2026-10-17

## Status

Implementation decision for the M2 MCP and shared services.
This extends [ADR 0014](0014-headless-build123d-metric-prototype.md).
It does not report a completed resource acceptance trial.
Resource acceptance tests follow after the delivery milestones.

## Context

Agents must send PDF bytes to a headless service without access to its filesystem.
The required outputs include an editable construction description, a technical drawing, and validated STEP.
The web interface has a separate implementation owner.
Its adapter must use the same operations, state, and release gates as MCP.
It must not create a second CAD backend or an independent storage model.

The service must preserve upload progress and job state across process restarts.
It must distinguish queued work from operations whose effects are uncertain after a crash.
Drawing delivery must expose its actual scope without claiming automatic source interpretation or semantic PMI.

## Decision

### One shared Python service

`DomainService` owns source storage, artifact storage, part operations, drawing operations, run notes, and jobs.
MCP validates its tool arguments and calls this service with a trusted `AccessContext`.
The future web adapter must use the same instance and contracts in the same application lifespan.
Start and close its job service once. Do not create a second job dispatcher for the web routes.

The public contracts use source, run, job, and artifact IDs.
Adapters resolve these identifiers to private paths inside the service.
Tool arguments cannot select the principal or an arbitrary server path.
The MCP deployment uses one configured principal. Bearer access is shared across its authorized clients.
Separate web authentication and identity mapping belong to the M2 web service.
This implementation does not claim hostile multi-tenant isolation.

Docker enables the domain profile by default, with state under `/data/domain`.
The base Compose service uses stdio and no network.
The HTTP override publishes an authenticated endpoint on host loopback port 8765.
No input-directory mount is required.
The Python configuration retains a disabled-by-default domain setting for local-path development compatibility.
That development profile is not the remote upload contract.

### Durable sources and immutable artifacts

SQLite stores ownership, committed upload offsets, object metadata, and note revisions.
Source and artifact bytes remain in private namespaces.
The default limits are 20 MiB for a PDF and 512 KiB for a decoded upload chunk.
Upload completion verifies declared size, SHA-256, and PDF header/trailer markers.
It does not claim that the PDF structure is valid or that a hostile parser is isolated.

An exact retry of a committed chunk is safe. Changed bytes or chunk boundaries are rejected.
The client can inspect the committed offset before resuming.
Source bytes are verified again before use.
Artifact registration copies bytes into an immutable object and records their hash.
Downloads use bounded reads. Clients must verify the completed file hash.
The service rejects linked source, artifact, and metadata paths.

Notes have a revision independent of the part revision.
Conflicting note updates fail instead of overwriting another update.
No aggregate disk quota, automatic retention policy, or storage garbage collector is supplied in this milestone.
Operators must manage available space and retained evidence.

### Persistent jobs and cancellation

The job store records requests, idempotency keys, states, timestamps, results, and public errors.
The default admission limit is 128 queued or active jobs.
Exact idempotent retries remain available when the queue is full.
One dispatcher holds an operating-system lock for the store.
The worker pool has a finite concurrency limit.

On restart, queued jobs resume. Unfinished active jobs become `interrupted`.
The service does not replay operations with uncertain effects.
It verifies ownership and expected revision again before dispatch.
Clients must inspect run state before submitting replacement work.

Cancellation prevents queued work from starting.
Cancellation of active work is cooperative. A running operation can finish with effects and a `succeeded` or `failed` result.
Cancellation does not roll back CAD state or released artifacts.
Synchronous operations and jobs use the same domain operations and validation gates.

### A bounded drawing adapter

DrawingSpec 1.0 binds a sheet to its part revision and canonical description hash.
It declares views with line, circle, and arc geometry, dimensions, manufacturing notes, and uncertainty markers.
Geometry and dimensions refer to source evidence and stable feature identifiers.
Drawing scalar references can derive values from a named parameter with a factor and offset.

The maintained worker creates native DXF linear, radius, diameter, and angular dimension entities.
It renders the same entities to PDF and returns a drawing report.
Validation includes reference consistency, dimension values, required-view declarations, uncertainty coverage, and bounded layout checks.
The implementation uses ezdxf and its PDF rendering backend inside the existing restricted worker.

This adapter renders supplied 2D view geometry.
It does not automatically project arbitrary solids or extract sections.
Section geometry and its identifying note must be supplied and independently reviewed.
Automatic drawing-to-solid equivalence, general GD&T validation, and semantic PMI are unsupported.
Layout success does not prove correct source interpretation or sufficient views.

### Diagnostic output for failed layouts

Drawing reports include collision identifiers and actual rendered bounds.
The restricted worker can produce a marked diagnostic PDF when a valid declaration fails its layout checks.
The domain service verifies fixed artifact paths, sizes, hashes, and revision bindings before it registers these artifacts.
The existing authenticated artifact interface supplies the PDF and JSON report.
Diagnostic artifact roles remain separate from accepted technical drawing roles.
They cannot satisfy drawing review or STEP release.

Agents use these diagnostics in a correction loop: validate the declaration, render, inspect reported defects, correct them, and render again.
Independent source and visual reviews follow the passing render.
Pydantic validates the declaration structure and bounded values. It does not prove geometric or manufacturing correctness.

### Drawing and model release

Either drawing or model can be created first.
Their final revisions must agree.
The final accepted drawing review identifies the exact drawing hash, part revision, construction-source hashes, reviewer, reason, and current model candidate.
A model rebuild invalidates the earlier drawing review, including a rebuild of the same revision.
Drawing review is an identified attestation. Automatic CAD equivalence remains `not_tested`.

STEP release requires current drawing artifacts, passing layout checks, and an accepted current review.
It also retains the existing fresh-worker STEP import, geometry measurements, and source-coverage gates.
Reports expose artifact IDs and public evidence without server storage paths.

The geometry exporter remains AP214.
JSON is the editable construction source; DXF is the editable drawing output.
Neither proves editable construction or semantic PMI inside STEP.
AP242 construction, adapter edits, and semantic and graphical PMI belong to M3.

## Consequences

The web owner can implement routes against shared versioned contracts and synthetic fixtures.
The MCP can accept PDFs and deliver drawing and STEP artifacts without client filesystem access to the server.
The browser interface remains a separate task using React, shadcn, TanStack Router, and TanStack Query.

Supplied drawing geometry requires explicit preparation and independent review.
The service cannot promise automatic conversion of every technical PDF.
Real source acceptance, independent STEP analysis, and target-CAD opening remain separate from synthetic regression tests.
Keep their actual results and untested limits in run evidence and the pull request.

## Verification requirements

- Verify upload retries, interrupted writes, hash failures, ownership, and immutable artifact downloads.
- Verify note revision conflicts, queue capacity, idempotency, process locking, restart behavior, and cancellation effects.
- Verify DXF dimension entities, PDF rendering, stale drawing bindings, layout failures, and uncertainty markers.
- Verify that an old drawing review cannot release a changed or rebuilt model.
- Verify the complete synthetic upload-to-drawing-and-STEP flow in the restricted Docker runtime.
- Verify contract compatibility between MCP and the future web adapter separately.

Record tests that actually ran. A design requirement or historical result is not a new test result.
