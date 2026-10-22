# Delivery artifacts and backend boundary

Use only `drawing2cad-mcp` for PDF preparation and CAD execution.
The skill does not depend on FreeCAD, build123d, or another backend's API.
The server owns backend selection, schemas, workers, artifacts, and capability reports.

## Delivery scopes

| Scope | Required outputs | Limits |
|---|---|---|
| Complete service | Validated STEP, editable JSON description, dimensioned DXF/PDF, accepted drawing review, current verified pair, review list, coverage, manifest, and trace. | Use domain `delivery: "complete_service"`. The final `pair_current` must be true. |
| STEP-only | Validated STEP, editable JSON description, review list, coverage, manifest, and trace. | This explicitly requested scope does not claim a verified drawing. Domain release uses `delivery: "step_only"`. |
| Optional AP242 and PMI | Requested construction replay, supported parameter changes, and semantic or graphical PMI. | Each claim needs its own test from STEP alone where required. AP242 builds require the server's additional independent analysis. |

AP214 can satisfy the STEP requirement for either delivery scope.
AP242 and semantic PMI are optional unless the requested delivery requires them.
The [AP242 adapter reference](ap242-adapter.md) describes the supported application-specific construction replay.
Its results do not prove native target-CAD features.

The domain profile accepts PDF uploads and keeps storage paths internal.
Clients use source, run, job, and artifact IDs.
A remote client must not need access to the server filesystem.
The local-path profile remains a reduced STEP-only profile for explicit STEP-only requests and development tests.
It does not deliver technical drawings or a complete-service pair.
Use uploads, jobs, and downloads only when the client permits those tools.
Storage, jobs, notes, drawing delivery, and release rules belong to the MCP service.
The web backend and React interface are optional clients of the same service contracts.
The standalone MCP server requires neither web component.
MCP currently uses one configured principal. Its bearer token does not create separate client identities.

## Technical drawing

The maintained format is editable DXF plus a PDF rendered from the same drawing revision.
Use `drawing_derive_views` for supported model projections and sections.
The adapter validates geometry, dimensions, evidence, and layout.
Independent PDF verification and identified review establish the supported drawing acceptance claims.
A layout pass alone does not establish source accuracy or drawing/model agreement.
Raw projections or hand-written SVG do not establish a complete technical drawing.

Use [drawing-delivery.md](drawing-delivery.md) for sheet requirements and verification limits.

## STEP and target formats

Record the actual STEP schema from the candidate.
Do not infer AP242 support from an export option or filename.
Measure the fresh imported geometry before releasing the candidate.

For final AP242, verify construction, driving parameters, relations, semantic PMI, and graphical PMI separately.
Use [validation.md](validation.md).
For optional NX or SOLIDWORKS derivatives, use [target-format-exports.md](target-format-exports.md).
Distinguish opening an imported body from reconstructing native editable features.

## Backend decision

The selected CAD backend is build123d with OCP/OpenCascade.
The maintained server translates the JSON feature description into backend operations.
Granular calls and full-description builds must use the same feature representation.

The current MCP executes CAD only through its headless build123d worker.
The FreeCAD proxy has been removed. Historical inline adapter calls are unavailable.
Historical adapter references are outside the skill package. They document provenance and the origins of maintained readers.
Their recorded code and hashes must not be rewritten or presented as new test results.
Do not load or execute them for the current workflow.

The backend decision does not prove universal feature coverage or complete PMI support.
Use the current tool catalog and actual test evidence for capability claims.
