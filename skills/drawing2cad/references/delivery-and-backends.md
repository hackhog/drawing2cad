# Delivery artifacts and backend boundary

Use only `drawing2cad-mcp` for PDF preparation and CAD execution.
The skill does not depend on FreeCAD, build123d, or another backend's API.
The server owns backend selection, schemas, workers, artifacts, and capability reports.

## Delivery milestones

| Milestone | Required outputs | Limits |
|---|---|---|
| M1 prototype | Validated STEP candidate, editable JSON part description, review list, coverage report, manifest, and trace. | JSON is the construction source. STEP-only editability and PMI remain unproven. |
| M2 complete service | Uploads, source and artifact IDs, one application for MCP/API/browser clients, and a dimensioned technical drawing. | The drawing and model can be created in either order. Their final revisions must agree. |
| M3 AP242 | AP242 construction, supported import adapters, driving parameter changes, and semantic and graphical PMI. | Each claim needs its own test from STEP alone where required. |

AP242 and semantic PMI are M3 capabilities and are optional for the hackathon metric.
They do not block delivery of an explicitly limited M1 prototype.
A passed prototype must not be described as the final AP242 master.
The initial M3 adapter is documented in [ap242-adapter.md](ap242-adapter.md).
Its application-specific construction replay does not prove native target-CAD features.

The M2 domain profile accepts PDF uploads and keeps storage paths internal.
Clients use source, run, job, and artifact IDs.
A remote client must not need access to the server filesystem.
The local-path profile supports development and the metric. It does not deliver technical drawings.
Use uploads, jobs, and downloads only when the client permits those tools.
Shared services, storage, jobs, notes, and drawing delivery belong to the MCP milestone.
The web API and React interface are a separate implementation milestone using the same service instance and contracts.
MCP currently uses one configured principal. Its bearer token does not create separate client identities.

## Technical drawing

The maintained format is editable DXF plus a PDF inspection copy rendered from the same entities.
The adapter validates supplied view geometry, dimensions, evidence, and layout.
It does not automatically project solids or extract sections. Source accuracy and drawing/model agreement require independent review.
Raw projections or hand-written SVG do not establish a complete technical drawing.

Use [drawing-delivery.md](drawing-delivery.md) for sheet requirements.

## STEP and target formats

Record the actual STEP schema from the candidate.
Do not infer AP242 support from an export option or filename.
Measure the fresh imported geometry before releasing the candidate.

For final AP242, verify construction, driving parameters, relations, semantic PMI, and graphical PMI separately.
Use [validation.md](validation.md).
For optional NX or SOLIDWORKS derivatives, use [target-format-exports.md](target-format-exports.md).
Distinguish opening an imported body from reconstructing native editable features.

## Backend decision

The selected M1 backend is build123d with OCP/OpenCascade.
The maintained server translates the JSON feature description into backend operations.
Granular calls and full-description builds must use the same feature representation.

The current MCP executes CAD only through its headless build123d worker.
The FreeCAD proxy has been removed. Historical inline adapter calls are unavailable.
Historical adapter references are outside the skill package. They document provenance and the origins of maintained readers.
Their recorded code and hashes must not be rewritten or presented as new test results.
Do not load or execute them for the current workflow.

The backend decision does not prove universal feature coverage or complete PMI support.
Use the current tool catalog and actual test evidence for capability claims.
