# Validation contract and publication

Use one status per verification group: `pass`, `fail`, `not_tested`, or `not_applicable`.
`not_applicable` requires a reason.
A missing capability does not automatically make a requirement inapplicable.
`not_tested` is not success.
The request and model contract define which groups must pass before master publication.
A new report does not replace unchanged historical evidence.
It references that evidence through hashes and versions and separates it from the current run.

## Separate verification claims

| Group | Evidence |
|---|---|
| `source_traceability` | Sources, pages, and hashes are authorized. Used information has evidence or an explicitly identified derivation or assumption. |
| `headless_pipeline` | All required phases pass on the server without a FreeCAD GUI session, GUI dispatcher, or display server. Worker and rendering evidence are separate. |
| `drawing_first` | An editable dimensioned technical drawing and inspected sheet rendering exist before the dependent build or design change. Drawing revision, hashes, and phase references are recorded. Apply the mode rules in [drawing-first.md](drawing-first.md). |
| `drawing_model_consistency` | Relevant model dimensions, projections, and sections were compared with the controlling drawing revision. Export uses this exact build. |
| `contract_integrity` | Fixed revision and hash, valid data, complete references, acyclic graphs, and recorded decisions. |
| `native_construction` | Actual editable native operations, parameters, and dependencies within the claimed scope. |
| `brep_equivalence` | Independently read final BREP is geometrically equivalent to the reconstruction. |
| `step_structure` | Header, schema, specific entity types, and references are verified. This does not imply full EXPRESS certification. |
| `step_only_rebuild` | Fresh build with STEP as its only model source. |
| `contract_replay` | A second fresh build from the same fixed contract is equivalent. |
| `step_replay` | A second fresh STEP-only build is equivalent. |
| `editability` | A relevant upstream change has the correct effect on the result and can be reset. |
| `relation_transport` | Each promised relation is reconstructed from STEP and responds as a relation. Evaluated numbers alone are insufficient. |
| `pmi_semantics`, `pmi_presentation`, `native_pmi_visibility` | Original PMI is complete, assigned to geometry, and actually visible in the respective representations. |
| `review_register`, `review_marker_transport`, `native_review_visibility` | Register is complete. Status, sources, anchors, and markers are separately preserved and visible. |
| `authoring_geometry`, `authoring_relations`, `authoring_pmi`, `authoring_review` | Change, re-export, and another fresh import are demonstrated separately for each data family. |

The summary status `authoring_roundtrip` can be `pass` only if all required data families pass.
A successful geometry test with `authoring_pmi=not_tested` is not a complete re-export.
Identify the standard importer and the special adapter separately by name and version.

## Drawing before build and STEP

For `new_drawing` and published design changes, `drawing_first` and `drawing_model_consistency` are mandatory.
Require the reviewed sheet revision, editable file, render hash, source and dimension references, and phase reports before the dependent build.
A sketch screenshot, unchanged copy of the input PDF, or TechDraw drawing created after the model is insufficient.
Timestamps alone do not prove the sequence.

Compare the model independently through the specified dimensions, views, and sections.
Resolve differences before STEP export.
After changes, invalidate the affected drawing, contract, and build references.
Verify those references again.
Do not silently overwrite the reference drawing from an incorrect model.
Visible dimensions do not prove semantic PMI in STEP.

For isolated STEP-only import tests, `drawing_first=not_applicable` is permitted with that reason.
A subsequent drawing comparison must not supply missing STEP content.
Legacy regressions retain their actual historical evidence.
A new work instruction does not certify old runs retrospectively.
The current 3D TechDraw trial does not prove creation of a drawing from 2D geometry before the model.

## Geometry and construction

1. Define validation tolerances and the expected solid count before the first result.
   Explain the magnitude, unit, kernel, and comparison method.
   Do not present numerical tolerances as manufacturing tolerances.
   Do not relax them after a failed attempt.
2. Examine the complete reachable DAG, relations, parameters, units, and placements.
   Make sure that radii and depths are positive and profiles are valid.
   Make sure that directions and coordinate frames agree.
   Do not test only the root.
3. Make sure that native intermediate objects have no error state.
   Make sure that their shapes and expected object types are correct.
   Profiles are not solids.
   Count adapter helper objects, Spreadsheet objects, and review and PMI objects separately.
   A labeled final solid is not a native operation tree.
4. Read the final BREP independently from the same STEP file.
   Compare it with the reconstructed final solid.
   Measure both directed Boolean material differences.
   Examine topology validity, solid count, bounding box, relevant dimensions, and sections if necessary.
   Volume and bounding box alone are insufficient.
   For open surfaces or wires, specify suitable distance tests.
   A volume test is insufficient for these objects.
5. Examine the actual schema header and entity references.
   Make sure that auxiliary BREP for topology anchors does not create unexpected additional product solids.
   Reject the affected construction if operators are unknown, references are missing, or selectors are ambiguous.

Investigate an isolated volume-integration difference after STEP import separately from Boolean material differences.
Record measurement methods and differences.
Do not substitute one method for another retrospectively when applying a limit.
A known case difference does not permit new geometry errors in general.

## Original PMI: semantics and display

For each expected `source_id`, verify exactly one original item.
Make sure that its type, text or value, unit, explicitly required tolerance or datum, and complete target set are correct.
Make sure that its derivation graph is valid.
Do not silently ignore unknown PMI types or tolerance families.
Do not add standard values absent from the drawing.
Verify completeness through ID sets and properties.
The count alone is insufficient.

For required graphic PMI, verify the chain: graphics → callout → semantic dimension or property.
Make sure that annotation planes, text anchors, and polylines agree.
For semantic text properties, make sure that the link points to the actual `PROPERTY_DEFINITION`.
Callouts require a valid annotation plane and draughting-model reference.
If an XCAF reader shortens derivation graphs, also examine them directly in STEP.

Display the stored views.
Inspect them for readability, missing labels, hidden content, overlaps, and clipped presentation.
Coplanarity alone is insufficient.
From the intended view, the plane must be in front of the body that would hide it.
Also identify derived bolt-circle and angle geometry graphically.
Native display, STEP presentation links, and display in another viewer are separate evidence.
A screenshot does not automatically prove a semantic link.

Fix the final layout only after visual inspection.
A layout correction requires a new contract revision and repetition of the affected checks.

## Register, assumptions, and visible review markers

1. From the contract and decoded data, determine all derived, assumed, unresolved, and conflicting values and positions.
   Make sure that the register covers every affected ID.
   Do not record only assumptions considered important.
2. For each entry, verify origin, evidence or derivation, value and unit or explicit `null`, decision, and verification status.
   Also verify affected IDs, anchor, marker ID, and history.
   Do not assign `accepted` without decision evidence.
   Confirmed assumptions keep their origin classification.
3. Resolve unambiguous geometric targets again.
   For an unresolved location, require the source region, intended logical target, and a visible "Location unresolved" note.
   Do not accept an invented specific geometric anchor.
   An unresolved mandatory construction input blocks the dependent build and export.
4. Display markers separately from original PMI.
   Include origin and status in readable text.
   Do not use color alone.
   Enable marker groups.
   Inspect each relevant view.
   Locations without a resolved CAD target must remain visible in the review list or source view.
5. During the fresh STEP-only import, compare IDs, status, origin, target selectors, anchor fingerprints, and presentation.
   An external JSON report or property text alone does not prove recovery of a visible marker.
6. After changes, verify target anchors again.
   Set affected register entries and markers to `stale` until reassessment is complete.
   An unchanged visible old label is not valid evidence for a change.

The profile in [inline-review-envelope.md](inline-review-envelope.md) uses named local properties for review and UI data.
Claim only the parser, import, and export path that was specifically verified.
Do not claim automatic interpretation in other CAD systems.
Count review entries and original PMI separately.
A requirement for a complete register does not certify old fixtures retrospectively.

## Fresh replays and input provenance

- For `contract_replay`, create a new build from the identical fixed contract. Do not use active selection, stored process variables, or an existing FCStd as construction sources.
- For each `step_only_rebuild` and `step_replay`, use a new process with STEP as its only model source. The adapter and validation policy can be loaded. Original contract, drawing, and FCStd must not supply missing STEP data. Compare with reference values only after independent reconstruction is complete.
- Record the inputs actually read in the report. Demonstrate matching source and contract hashes, adapter and toolchain profile, and process isolation. A filename and timestamp do not prove a fresh run.
- Compare logical DAGs, parameters, promised relations, PMI inventory, register and marker inventory, and geometry. Map STEP entity IDs to logical identity. Different serial numbers are not content differences.
- File hashes can differ because of serialization. Report each missing replay type separately as `not_tested`. Two STEP imports do not automatically prove a second build from the contract.

## Editability and native user interface

Select a relevant upstream parameter whose geometric effect can be calculated independently.
Before execution, define the change, permitted range, expected effect, and reset test.
The reconstruction must recompute through the root and retain intermediate operations.
Then reset the original value.
Verify the original geometry again.
One test does not prove arbitrary changes to all parameters.

If relations are promised, also select a change that exercises the relation.
Equality, coupling, tangency, or a position rule must actually respond.
Independent equal values or cells do not count as coupling.
Examine the actual constraint scope of native sketches.
Fully constrained primitive rectangles do not prove a complete part design network.

UI metadata can supply labels, parameter mappings, or a native display strategy.
Compare freshly imported construction values with the standard STEP operation graph.
Reject conflicting UI values.
The number of Spreadsheet cells does not prove complete editability.

## Change and re-export

Create a changed revision from the STEP-only reconstruction.
Explicitly record the model revision, changed parameters, and effects on geometry, relations, PMI, and review entries.
Initially set affected original PMI to `stale`.
Recalculate, reassign, display, and verify those PMI.
Do not silently equate an original drawing value with a new design value.
Record the deviation from the drawing in the register.

Export the changed construction graph and final BREP as a new AP242 candidate.
Include all required updated PMI and review data.
In another fresh process, reconstruct exclusively from this STEP file.
Verify the changed parameter, expected effects, relations, and every affected annotation.
Unaffected original PMI must remain preserved.
A native change test followed by a reset, without this re-export, proves only editability.

A missing reverse adapter or missing automatic PMI update blocks the corresponding claim.
Manual PMI updates are acceptable only if explicitly versioned and fully verified again.
Do not describe that process as automatic.
Keep the valid initial master.

## Report, review, and publication

A JSON report identifies the request, file paths and hashes, contract hash and revision, adapter and toolchain versions, and permitted and actual inputs.
It also records capability scope, status per verification group, measurement methods and values, test parameters, register, and generated artifacts.
Set `pass` only from actual measurements.
Identify historical evidence, current tests, and planned extensions separately.

Mark a candidate as the current master only if all groups required by the request pass.
For required groups, `fail` or `not_tested` blocks publication.
Deliver a useful partial result as a candidate with its missing evidence identified.
Previously authorized assumptions do not require approval again.
Identify content conflicts, new necessary decisions, or missing facts precisely.

Deliver the master or candidate, declarative contract, verification report, visible original PMI and review views, and optional derived FCStd.
Also deliver the handoff manifest defined in [model-agnostic-workflow.md](model-agnostic-workflow.md).
The limits and next step must be understandable without chat history.
Keep the old master file until its replacement is validated.

## Headless server acceptance

Start the complete pipeline without an interactive desktop or an existing FreeCAD process.
Record `FreeCAD.GuiUp == 0` in each CAD worker and identify the process that receives MCP jobs.
A headless child behind a required GUI bridge does not meet this requirement.
An offscreen FreeCAD GUI or Xvfb session is not evidence of GUI-independent execution.

Test source preparation, dimensioned drawing creation and rendering, native construction, and model-to-drawing comparison.
Then test AP242 export, semantic PMI, fresh STEP-only reconstruction, parameter changes, and required visual outputs.
Inspect server-rendered sheets, PMI, and review markers as actual images.
Native GUI views remain optional desktop checks. They cannot replace the server-rendering tests.
If a required renderer is unavailable, report that capability as unverified or unsupported.

Record versions, input and artifact hashes, process boundaries, and each phase result outside the skill package.
For a Docker deployment, repeat acceptance in the actual container image.
Host tests alone do not prove container support.
Inspect runtime file creation. Do not permit ad hoc model scripts or temporary executable payload files.
Versioned server application code remains permitted.

## External validation inputs

Receive expected dimensions, tolerances, and parameter-change results from the authorized run inputs.
Define these values before result comparison. Keep customer data and test results outside the skill package.
For a hole change, calculate the expected volume effect from actual material intersection.
The cutting tool length can differ from the material thickness.
Do not increase general tolerances to conceal a discrepancy in one test.
