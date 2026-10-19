# Validation and delivery claims

Use `pass`, `fail`, and `not_tested` for required tests.
A missing tool or unexecuted test is `not_tested`.
Do not treat it as success.

Define required features, dimensions, source views, and measurement tolerances before building.
A correct JSON input does not prove that the resulting solid matches the drawing.

## M1 prototype

The table separates claims and their evidence. It does not make every claim a prerequisite for the hackathon metric.
The metric requires three parts, passing MCP validations, and complete source review. A target-CAD opening test is optional.
AP242 and semantic PMI are optional M3 capabilities. Complete-service drawing acceptance applies to the domain profile.

| Claim | Required evidence |
|---|---|
| Source traceability | Authorized source hashes and regions for explicit values and assumptions. |
| Description integrity | Versioned schema, stable feature IDs, supported operations, and complete references. |
| Geometry validity | Actual nonempty solid geometry and kernel validity results. |
| Dimension agreement | Measurements from the resulting geometry compared with independently recorded drawing expectations. |
| Hole agreement | Measured hole axes, centers, diameters, depths, entry side where required, and supported hole attributes. |
| Feature coverage | Required inventory compared with constructed features; omissions remain visible. |
| Editable JSON | A parameter change rebuilds the required geometry from a new description revision. |
| STEP export | Candidate exists; product name, units, and actual schema are recorded. |
| Fresh re-import | Another worker imports the candidate and measures its resulting geometry. |
| STEP conformance | Independent analysis of the file; bounded syntax inspection alone is insufficient. |
| Target-CAD opening | Actual opening test in the named CAD product and version. |
| Headless execution | The tested worker runs without a CAD GUI or display dispatcher. |
| Complete-service drawing | A coverage table without `missing`, `needs_review`, or `not_tested` rows, including the isometric view, the necessary sections, the border, and the title block (see drawing-delivery.md), plus an accepted identified review. |
| Manufacturing release | A complete specification: each functional requirement is a source requirement or a recorded user decision. An open requirement prevents this claim. |

Use independent expectations from source observations or permitted verification resources.
Record the role of each resource.
Do not use a reference STEP as an unreported construction input.

A fresh import with the same kernel tests serialization and geometry transfer.
It is not an independent implementation of that kernel.
Keep external conformance and target-CAD tests separate.
A hole entry check requires a source-derived `entry_position` and the inward axis.
Without that check, do not infer the correct entry side from diameter or depth measurements.
For `outer_diameter`, put `position` on the cylinder axis at the required axial station.
The check uses the outer cylindrical face at that station.
It fails if no face contains the station, or if different diameters meet there at a shoulder.
At a part end, a station on the face boundary is valid.
For a `hole` measurement, `position` identifies the axis. It does not select an axial station.
For a hole feature, `position` identifies the entry. With explicit `thread.length`, the bore check uses this entry station.
The thread attribute check requires a full concave cylinder at that entry, with the declared tap-drill diameter and full bore depth.
It runs on the final shape and the fresh STEP import. It does not verify thread flanks or semantic PMI.

A technical release records passing geometry checks and an identified source-review attestation.
Its coverage counts do not prove that every source feature was identified.
If independent source review fails, mark source accuracy and the metric result as failed.
Preserve the technical release response as historical evidence, with the later rejection recorded separately.

The M1 JSON description is the editable construction source.
Its existence does not prove editable construction inside STEP.
An AP242 schema label does not prove construction or PMI content.

## Complete-service drawing checks

M2 adds the editable technical drawing and its inspected rendering.
Verify dimensions, projection and section orientation, units, revision, notes, and uncertainty markers.
Verify final drawing/model consistency.
Use [drawing-delivery.md](drawing-delivery.md) for the current drawing requirements.

## M3 AP242 acceptance

Apply this optional extension only when requested and when the client permits its tools.

Test each claim separately:

1. Actual AP242 schema, units, product identity, and final geometry.
2. Supported construction entities, operation dependencies, and driving parameters.
3. Reconstruction with STEP as the only model-content source.
4. A supported parameter change and its measured effects.
5. Export of the changed model and another fresh reconstruction.
6. Semantic PMI values, units, types, and geometry associations.
7. Graphical PMI presentation and required view visibility.
8. Review data and marker preservation after changes.
9. Independent conformance analysis and required target-CAD behavior.

Neither embedded JSON nor a readable parameter table proves editable STEP construction.
A normal imported STEP body does not prove reconstructed feature history.
A visible dimension does not prove semantic PMI.

## Reports

Record actual file hashes, tool versions, revisions, time, measurement methods, tolerances, and results.
Report deviations with the affected feature or source region.
Keep historical results distinct from new tests.
A candidate with missing required results remains limited.
Do not label it a complete AP242 master.

Use independent reviewers for source interpretation and final artifact claims when practical.
Reviewers must identify their actual inputs and tests.
A review of documentation is not a CAD execution test.
