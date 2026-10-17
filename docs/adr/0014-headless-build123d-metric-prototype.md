# 14. Build the metric prototype with a headless build123d worker

Date: 2026-10-17

## Status

Accepted design for the M1 prototype.
Runtime acceptance is separate from this decision.
Record actual tests and missing results in the run manifests and in the pull request.
This decision replaces the drawing-first order in ADR 0013 for future runs.
It does not change historical run evidence.

## Context

The production service must accept PDF uploads and deliver a technical drawing and STEP.
All PDF and CAD dependencies must run in Docker without a host CAD installation.
One Python application must serve MCP and the web API.
The browser interface must use React, shadcn, TanStack Router, and TanStack Query.

The first milestone targets the challenge metric.
A versioned JSON part description is the editable source for its declarative path.
AP242 construction, adapter edits, and semantic PMI remain required final capabilities.
A neutral end body does not satisfy those capabilities.

## Milestones

| Milestone | Scope | Acceptance boundary |
|---|---|---|
| M1 metric prototype | MCP image, PDF measurement, feature description, sandboxed CAD, validation, STEP, and automatic reports. | Three sample parts pass the defined metric. No claim of complete drawing delivery or editable STEP construction. |
| M2: MCP and shared services, web service | Persistent PDF upload, source/artifact IDs, unified Python MCP/API, browser interface, and technical drawing adapter. | A remote client completes the workflow without server filesystem access. Final drawing and model agree. |
| M3 AP242 | Construction representation, import adapters, driving parameter edits, semantic PMI, and graphical PMI. | Reconstruct and edit from STEP alone; export and repeat in a fresh worker. |

M1 is the first pull request's implementation scope.
M2 and M3 do not block the M1 prototype merge.
Metric acceptance follows after the implementation milestones.
Merging the implementation does not establish complete source coverage, independent STEP conformity, or target-CAD acceptance.

M2 has separate implementation owners for the MCP/domain services and the web API/frontend.
Agree on shared schemas, service interfaces, revisions, artifact access, and error definitions before parallel implementation.
The web owner can start with synthetic contract fixtures.
Final M2 acceptance requires integration with the real services.
Both interfaces use one Python backend application and the same domain services, state, and release gates.
Do not duplicate CAD or validation logic in the web adapter.

M1 can use configured server-side source paths.
M2 must receive PDF bytes and return an opaque source ID.
Local storage paths then remain implementation details.

The drawing can precede or follow the model.
Both remain necessary for the complete service.
The M2 drawing adapter must support dimensioned sheets and headless rendering.
DXF with native dimensions and a PDF preview is the proposed format pair, subject to adapter validation.

## CAD backend comparison

| Candidate | Useful capability | Workflow cost or limit | Decision |
|---|---|---|---|
| FreeCAD | Native parametric document and established feature objects. | The former proxy required an external runtime. Recorded GUI trials did not prove the complete headless pipeline. | Remove the proxy. Retain historical adapter code only for provenance and maintained reader origins. |
| CadQuery | Python construction and STEP/DXF exchange through OpenCascade. | The project needs a separate feature description and review model. Exchange does not preserve its parametric source automatically. | Suitable alternative, not the selected M1 backend. |
| build123d | Python construction, section/projection operations, and STEP/DXF exchange through OCP/OpenCascade. | Drawing layout, semantic PMI, and transferable construction need maintained adapters. | Select for M1, as required by the updated issue. |

See the official [FreeCAD source](https://github.com/FreeCAD/FreeCAD),
[CadQuery exchange guide](https://cadquery.readthedocs.io/en/latest/importexport.html),
and [build123d exchange guide](https://build123d.readthedocs.io/en/latest/import_export.html).
The comparison supports the selection. It is not an interoperability test.

Agents use only drawing2cad-mcp.
The server translates one versioned feature description into backend operations.
Granular calls and full-description builds use the same representation.
Keep backend code out of the skill.

The current execution backend is headless build123d only.
Remove the FreeCAD transport, tool surface, and configuration instead of retaining an optional execution path.
Old `[freecad]` and `server.expose_freecad_proxy` configuration fields are rejected, including disabled values.
Historical adapter references remain unavailable through the current MCP. Preserve their code and recorded hashes.

## Sandbox decision

| Option | Advantages | Costs and residual risks |
|---|---|---|
| One hardened worker container | Simple deployment. Network can be disabled; root filesystem can be read-only. | Container restrictions alone do not separate jobs. A writable shared job area exposes other jobs. |
| nsjail or bubblewrap inside the container | Namespace and filesystem isolation can separate jobs. | Host user-namespace and capability policy affects operation. Extra privileges can weaken the outer boundary. |
| One container per job | Separate namespaces, limits, and filesystem lifecycle for each job. | A scheduler needs container-control access. Mounting the Docker socket grants a powerful host interface. |
| Per-job process with Landlock and seccomp inside a hardened container | No Docker socket or privileged user namespace is required. Each child restricts its own file and syscall access. | Kernel support is mandatory. Processes share a kernel; limits and filesystem policy need denial tests. |

Select the last option for M1.
The container drops capabilities, uses no-new-privileges, and keeps its root filesystem read-only.
Each job receives a limited writable directory and explicit readable inputs.
Landlock restricts filesystem access.
Seccomp denies network and IPC operations.
Process resource limits and a parent timeout bound execution.
The MCP listener remains outside each restricted child.

The sandbox spike used Docker Desktop with Linux kernel 6.6, Landlock ABI 3, and libseccomp.
Network access and outside read, write, and chmod attempts were denied. Job-directory writes succeeded.
Timeout, 128 MiB memory exhaustion, exit-code 77 crash, and a new-worker recovery test passed.
These tests did not load CAD. They do not prove full model or container acceptance.
Do not enable CAD execution when the required sandbox checks fail.
Do not silently execute an unsandboxed worker on Windows or another unsupported host.
Enable free-code execution only after its stronger denial tests pass.

The implementation also denies new processes and session changes while allowing kernel library threads.
The parent writes worker records outside the child's writable job directory.
A separate trusted worker validates free-code output against the stored description.
The child receives a copy of that description for parameter reads.
Neither its self-reported checks nor changes to that copy are authoritative.
Retain the exact inline payload in the event trace.
Free-code geometry can depend on construction absent from the JSON description.
Rerun the recorded payload for supported parameter changes; JSON-only feature replay remains unverified.

The test matrix must include forbidden network access, forbidden reads/writes, timeout, memory exhaustion, and worker crash.
After each failure, the MCP must remain available.
Record the actual kernel, image, dependencies, policy revision, and test results.

A `network_mode: none` container is useful for an isolated stdio test.
It cannot serve a remote HTTP listener.
For HTTP, network denial belongs to the job process while the application serves its configured endpoint.

Residual risks include shared-kernel defects, dependency vulnerabilities, resource contention, and errors in policy construction.
The selected profile is not proof of hostile multi-tenant isolation.
Test a stronger deployment boundary before making that claim.

Official references:
[Landlock](https://kernel.org/doc/html/v6.6/userspace-api/landlock.html),
[bubblewrap](https://github.com/containers/bubblewrap),
[nsjail](https://github.com/google/nsjail),
[Docker security](https://docs.docker.com/engine/security/),
and [Docker resource limits](https://docs.docker.com/engine/containers/resource_constraints/).

## Stable tool interface

Use the live schemas for exact fields and bounded input sizes.
The maintained contracts are in `drawing2cad-mcp/src/drawing2cad_mcp/cad_tools.py` and `part_schema.py`.

| Tool | Responsibility |
|---|---|
| `drawing2cad_status`, `cad_capabilities`, `cad_worker_probe` | Report runtime, supported operations, and actual worker readiness. |
| `part_schema`, `part_validate` | Read the versioned schema; validate the description and evidence records. |
| `part_create`, `part_read`, `part_update` | Store and retrieve explicit part revisions. |
| `create_base_body` | Add a supported base profile and extrusion. |
| `add_hole` | Add through, blind, counterbore, countersink, or supported thread attributes. |
| `add_pocket`, `add_cut` | Remove material with a supported profile. |
| `add_chamfer`, `add_fillet` | Apply supported edge operations with explicit selection. |
| `build_from_description` | Build the stored graph, export a candidate, and validate fresh-worker re-import. |
| `build_code` | Optional in-memory code, only within a verified sandbox scope. |
| `export_step` | Release the validated candidate after source-dimension checks and complete review coverage. |
| `part_export_review` | Export review, coverage, manifest, and event evidence. |

Keep legacy `workflow_*` evidence tools and bounded STEP readers.
Their attestations and syntax checks are not CAD validation.
The M1 part service owns its revision, build, and export gates.
It does not require drawing-first evidence.

## Assumptions and measurement

If a dimension or position is missing, infer a reasonable value from drawing geometry.
Record `assumed`, the reason, source region, units, and affected feature.
Keep explicit dimensions, geometric estimates, and user decisions distinct.
Build the feature when the assumption is reasonable.
Block only when no reasonable assumption supports the required construction.

Mark undimensioned radii and all unclear features.
Keep assumptions visible in Markdown/CSV review records and the later technical drawing.
Do not treat the absence of an extractor warning as proof of complete evidence.

Calibrate image scale from two printed dimensions.
Prefer source vectors where available.
Treat circles and detected dimensions as candidates until their source associations are reviewed.
Measure constructed geometry against independent drawing expectations.
Do not use construction constants as the sole validation evidence.
Source coverage is a reviewer assertion with a callout-to-measurement inventory.
The server can validate the assertion structure and measured IDs; it cannot prove that every source feature was identified.
A separate reviewer must compare all source views with the final feature list.
A correct bounding box cannot prove the presence of an internal web, rib, or drill tip.

## Evaluation scope and pass definition

The initial evaluation set is:

| Part | Authorized construction input |
|---|---|
| Flansch | `resources/Drawing2CAD/Flansch/Flansch_dwg.pdf` |
| 3-Loch-Hebel | `resources/Drawing2CAD/3-Loch-Hebel/3-Loch-Hebel.pdf` |
| Grundplatte | `resources/Drawing2CAD/Grundplatte/Grundplatte.pdf` |

These filenames were verified when the decision was written.
The table is not a report that their geometry passed.
Other resource files remain verification-only unless explicitly authorized as construction inputs.
The optional hard case is `Gehaeuse 1 124 0146 0`; supply its authorized source separately.

For each normal part, stop after 45 MCP calls, including failed calls and retries.
The optional hard case has a 60-call budget.
Report the last proven checkpoint and remaining blockers when the budget is reached.
A budget stop is not a passed conversion.
The server counts part-service calls; the agent also tracks PDF preparation, discovery, and retries against the overall budget.
After the execution budget is reached, the service still permits recorded read and report calls.
These audit calls do not permit another build, edit, or release.

Freeze the feature and dimension inventory before building.
The metric pass requires:

- 100% of geometry-defining source views inspected and represented in the interpretation.
- 100% of required features represented, including visible holes, pockets, cuts, chamfers, fillets, and thread attributes.
- 100% of printed controlling dimensions inventoried and compared with measured geometry.
- Every missing dimension assigned a reasonable documented assumption, or an explicit blocker.
- MCP geometry validation and fresh STEP re-import passed.
- Product identity, units, and actual schema recorded.
- Independent STEP analysis and an actual NX opening test recorded as passed.
- Review list, coverage report, manifest, and event trace exported.

Use source tolerances where given.
For an untoleranced nominal comparison, define the numerical comparison tolerance in the run before construction.
This test tolerance is not a manufacturing tolerance.
Do not invent manufacturing tolerances or count assumed values as printed-dimension coverage.

At least two parts must build without `build_code`.
A missing NX or independent conformance tool gives `not_tested`.
The metric then remains incomplete, even if the server's geometry tests pass.

Repeat equivalent trials with strong, cheaper, and local models when those runtimes are available.
Record reasoning settings, tool calls, retries, questions, review assistance, queue time, and infrastructure failures.
An unavailable model gives `not_tested`; one assisted run cannot rank model quality.
Use the maintained [local evaluation client](../local-model-evaluation.md) for a bounded local trial.
Preserve failed trials before changing prompts or response formatting.

## Consequences

The declarative prototype has one editable construction source and one MCP boundary.
The optional free-code path also depends on its recorded inline payload.
The first milestone can demonstrate geometric reconstruction before the final AP242 representation exists.
That boundary must remain visible in the UI, skill, reports, and pull request.

The complete service still needs persistent uploads, artifact IDs, technical drawing creation, and browser integration.
AP242 construction and semantic PMI need separate implementation and acceptance tests.
Do not present a JSON sidecar or STEP end body as their substitute.


## Portable architecture renderer

The required diagram build failed because the machine-local archify program was absent.
Keep JSON as the only diagram source.
Use the maintained renderer in `tools/diagrams/renderer.mjs` for deterministic light/dark SVG and a browser viewer.
`npm run build --prefix tools/diagrams` generates all outputs and their hash lock.
`npm run check --prefix tools/diagrams` regenerates in memory and compares exact content.
This replaces ADR 0011's external renderer dependency.
It preserves the rule against manual HTML or SVG edits.
The viewer provides theme, zoom, and SVG download controls without external assets.
