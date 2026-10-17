# Dimensioned technical drawing before the model and STEP

Use this approved sequence:

1. Create the technical drawing.
2. Examine and version the drawing.
3. Derive the parametric 3D model.
4. Compare the model with the drawing.
5. Export STEP.
6. Verify STEP independently.

A set of Sketcher sketches alone is not a technical drawing.
The agent currently applies this rule through the skill.
The generic MCP does not enforce it.

## New construction from a drawing source

For production, author and render the sheet on the headless server through MCP.
Verify this method without `FreeCADGui`, `TechDrawGui`, or a display server.
A GUI-generated preview does not prove headless drawing support.
If this capability is missing, report the gap before the dependent model build.

1. Read the permitted sources.
   Collect evidence from those sources.
   Distinguish the original drawing from the new working drawing.
   Keep the original unchanged.
   Do not silently replace its values with new design values.
2. **Before the 3D build**, create a dimensioned technical sheet from explicit 2D geometry.
   Derive planar views, profiles, required sections, thicknesses, depths, hole positions, and manufacturing information from sources and recorded decisions.
   A later TechDraw drawing derived from the 3D model does not replace this first sheet.
   First verify the specific 2D authoring and rendering method through MCP.
   Do not bypass a missing capability with an early 3D build.
3. Specify the unit, projection method, scale, and revision.
   Dimensions necessary for construction must point to geometry without ambiguity.
   Do not add tolerances, radii, chamfers, or thread details without evidence.
   Connect all derived, assumed, and unresolved information to the review register through IDs and readable markers.
   Color alone is insufficient.
   If a location is unresolved, show the source region and its unresolved status.
4. Save an editable drawing file.
   Save a rendered sheet image.
   Inspect the rendered sheet.
   Make sure that views agree and that all dimensions and notes are complete and readable.
   Make sure that no information is hidden or clipped.
   Compare values with sources and decisions, not only with their labels.
   Unresolved mandatory dimensions block the dependent build.
   Previously authorized assumptions do not require confirmation again.
5. Fix the reviewed drawing revision with its file hashes, render hashes, and report.
   Derive the model contract parameters, profile definitions, relations, and operation DAG from that exact revision.
   Map dimension and note IDs to parameters and operations.
   Each construction input requires evidence or a marked decision.
   New construction information first requires a new drawing revision.
6. Create the native model from the fixed contract.
   You can reuse 2D profiles in Sketcher if their geometry, dimensions, and relations demonstrably agree.
   Keep pads, pockets, holes, fillets, and other operations with editable parameters and dependencies.
   PDF pixels or a sheet file do not automatically produce a complete solid.
7. Compare the 3D build with the controlling drawing through measured dimensions and the required projections and sections.
   An additional associative TechDraw drawing is a derived verification output.
   Resolve differences.
   If the model has an error, rebuild it from the same contract.
   If the design changes, first create new drawing and contract revisions.
   Do not silently change the reference sheet to match the result.
8. Export STEP only after the comparison passes.
   Then independently verify the required geometry, editable construction, relations, PMI, and markers.
   A visible sheet dimension does not prove that STEP contains semantic PMI linked to geometry.

When you resume work, you can reuse an approved working drawing if its hash was verified.
A copy of the input PDF does not meet the requirement to create a working drawing.
You can add a decorative or perspective view later if it adds no construction information.
It must not introduce unverified dimensions into the build.

## Application by mode

| Mode | Application |
|---|---|
| `new_drawing` | Use the full sequence above. Complete `drawing_prepare` and `drawing_review` before the first part build. |
| `replay_contract` | Reuse the reviewed drawing revision referenced by the contract or run manifest. Verify its hash. Do not reinterpret it. A legacy contract without this evidence remains valid as a historical regression test. It does not meet `drawing_first` retrospectively. |
| `import_step` | A pure STEP-only rebuild or import comparison reads only STEP for model content. Use the drawing as an independent reference only after reconstruction. For this isolated test, set `drawing_first=not_applicable` and give the reason. Never supply missing STEP data from a sheet. |
| `edit_model` | A required STEP-only import of the initial master can occur first. Before the requested construction change, create and examine a new dimensioned drawing revision. Derive the contract and native change from it. Export again only after comparison. Distinguish the original drawing from the changed design. |

An isolated adapter or kernel test does not require a new reference sheet if it publishes no new design revision.
The same exception applies to a temporary parameter change and reset test defined in the validation policy.
Record the test purpose and its separation from production in the manifest.
These tests do not prove a production run with the drawing first.

## Evidence in the run manifest

`drawing_ref` is a run and handoff field.
It is not a new mandatory operation in the model contract.
Record at least these items:

- Stable drawing ID, revision, unit, and editable drawing file path and hash.
- Path and hash of the rendered sheet that was inspected.
- Source hashes, register reference, and mapping from dimension and note IDs to contract parameters and operations.
- Review report with status, applied validation policy, inspected sheets, and open items.
- `drawing_prepare` and `drawing_review` before the dependent `build`, each with input and output hashes.
- References to the same drawing revision in the fixed contract and build report.
- `drawing_model_check` before `export`, with build hash, contract hash, measurements, and projections.
- An export report that identifies the exact verified build.

File timestamps or a drawing created later do not prove this sequence.
When you resume work, examine actual phase reports and hash relationships.
A layout change requires a new drawing revision and another visual check of the affected areas.
A change to construction values also invalidates the contract, build, and export verification.
Keep the change history.
Replace the last valid master only after the replacement passes all required checks.

For a pure STEP-only import, initially keep `drawing_ref` as `null`.
Permit external drawing references only in the subsequent comparison phase.
The transported construction graph and required PMI must still exist in STEP itself.
The preceding sheet is not an external replacement for missing history in an incomplete AP242 master.
