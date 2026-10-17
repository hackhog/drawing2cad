---
name: drawing2cad
description: Reconstruct CAD models from permitted technical drawings through drawing2cad-mcp. Create and verify the dimensioned drawing before the 3D model. Record evidence and uncertainties. Test editable construction and PMI in STEP AP242. Also use this skill for reconstruction from STEP alone, model changes, and adapter tests within a verified capability scope.
metadata:
  version: "0.6.0"
---

# drawing2cad: a reproducible AP242 master file

Use explicit inputs, a fixed declarative model contract, and measured outputs.
A suitable language model can continue the phases without previous chat messages or Python variables.
The CAD adapter depends on its tools. It must supply evidence for its capabilities.
An interchangeable language model does not imply universal CAD support or identical interpretation of a drawing.

**First, create a dimensioned technical drawing. Then, do the drawing review. Build the native parametric 3D model from that drawing. Export STEP last.**
Native 2D sketches alone do not meet this requirement.
The drawing is the controlling design record with a revision and hash.
Drawing creation, model comparison, and export require separate evidence.
Use [drawing-first.md](references/drawing-first.md) for new designs, repeated builds, STEP-only imports, and changes.

Write all documentation in technical English in accordance with ASD-STE100.
Use [documentation-language.md](references/documentation-language.md) for project terms and the language review.
Keep source text, identifiers, verified code, and historical evidence unchanged.
Keep project data outside the skill package. Supply authorized inputs separately for each run.
Do not include customer parts, resource links, model data, host snapshots, or historical run results in this skill.
Archive removed evidence outside the skill. Do not link that archive from the skill.

The production target is a fully headless server through `drawing2cad-mcp`.
All required phases must work without a FreeCAD GUI session or GUI dispatcher.
This includes drawing creation and rendering, editable construction, STEP AP242, semantic PMI, and independent validation.
A web interface can manage jobs, files, and notes. It must not supply a required CAD execution session.
The current GUI bridge is a development path. It does not meet the production requirement.
Record headless capability evidence for each phase. Do not report the complete server workflow as implemented without these tests.

Use `drawing2cad-mcp` for PDF preparation and access to FreeCAD tools.
Before each run, inspect the actual tool catalog and `drawing2cad_status`.
Do all CAD work through the FreeCAD MCP proxy, with the prefix `freecad_`.
You can send all necessary Python code inline.
Do not create ad hoc model scripts, macros, or executable helper files.
Authorized, versioned server code in `drawing2cad-mcp` is outside this restriction.
You can create declarative JSON test data, CAD files, and preview images.
For skill maintenance alone, do not change CAD files.

## Start and capability limits

For each run, read [model-agnostic-workflow.md](references/model-agnostic-workflow.md).
Read the interface in [drawing2cad-mcp.md](references/drawing2cad-mcp.md).
Read the capability requirements in [tooling-and-mcp-contract.md](references/tooling-and-mcp-contract.md).
Then, load only the references necessary for the active phase.

| Task | Reference |
|---|---|
| Create and verify the controlling drawing before model construction | [drawing-first.md](references/drawing-first.md) |
| Write documentation and review its language | [documentation-language.md](references/documentation-language.md) |
| Read a PDF, render a page, create a detail image, and call FreeCAD tools | [drawing2cad-mcp.md](references/drawing2cad-mcp.md) |
| Define sources, construction, relations, uncertainties, or a transfer between agents | [model-contract.md](references/model-contract.md) |
| Control processes and identify STEP representations or known binding limits | [execution-and-ap242.md](references/execution-and-ap242.md) |
| Read constructive solid geometry (CSG) and nominal PMI from STEP | [inline-readers.md](references/inline-readers.md) |
| Export or import a procedural graph with constant-radius fillets | [inline-procedural-adapter.md](references/inline-procedural-adapter.md), [edge-blends-and-thread-pmi.md](references/edge-blends-and-thread-pmi.md) |
| Find metric coarse threads and typical chamfers | [metric-thread-chamfers.md](references/metric-thread-chamfers.md). The general table contains 35 rows, from M1 through M68. |
| Read semantic text properties and display native PMI | [inline-property-pmi-reader.md](references/inline-property-pmi-reader.md) |
| Transfer local UI mappings and review data separately from original PMI | [inline-review-envelope.md](references/inline-review-envelope.md). Obey the verified scope of the profile. |
| Reconstruct a native parameter table and fully constrained rectangular profiles | [inline-editable-ui-adapter.md](references/inline-editable-ui-adapter.md). STEP supplies dimensions; the UI property supplies control mappings. |
| Show operations as a linear list in the native model tree | [inline-linear-history-view.md](references/inline-linear-history-view.md). Group original operations and keep their dependencies. |
| Show local review markers from embedded data | [inline-review-markers.md](references/inline-review-markers.md). Verify unique geometry anchors and separate review views. |
| Test reconstruction, changes, PMI, markers, and release | [validation.md](references/validation.md) |

The general contract vocabulary includes primitive solids, planar profiles and extrusions, Boolean operations, and constant-radius edge fillets.
This vocabulary does not prove an implementation for each operation.
The documented procedural adapter family has a smaller scope:

- Rectangular extrusions parallel to the coordinate axes.
- Full-circle extrusions along +Z or +X.
- Refined Boolean operations.
- Constant-radius fillets with unique topology anchors.
- Millimeter units.

Earlier CSG readers have different scopes.
For the actual part, verify each operation, unit, orientation, relation, PMI type, and necessary adapter direction.
Do not replace unsupported construction with an end body and identify that body as editable construction.

A reconstructed native operation tree supplies evidence for traceable construction.
It does not prove the unknown original design intent, original sketch constraints, or historical user actions.
Identical values do not prove preserved parameter relations.
A standard STEP import of a BREP and reconstruction through a verified specialist adapter are separate capabilities.

## Modes and phases

1. **Set the inputs.** Record the mode: `new_drawing`, `replay_contract`, `import_step`, or `edit_model`. Record exact permitted sources, hashes, pages, output artifacts, and necessary evidence. Reference cases are not additional construction sources. Keep user decisions that already apply.

2. **Verify capabilities.** Record `drawing2cad_status`, the current tool catalog, tool versions, and adapter profiles. Compare necessary functions with verified functions. A reachable proxy does not prove a reachable FreeCAD kernel or operation without a GUI. Missing evidence is not a pass. Use small isolated MCP tests to resolve specific capability questions.

3. **Collect evidence and review entries.** For PDF sources, use `pdf_info → pdf_read_text → pdf_render_page → pdf_crop_region`. Request only necessary pages and details. Compare the returned source hashes. Inspect the actual images. Text extraction has no OCR and does not replace visual interpretation. Separate original data, deterministic derivations, assumptions, and unresolved data. Give each unclear location and derived or assumed value a source, status, target anchor, and visible review marker. Keep these markers separate from original PMI. Do not conceal an unresolved location with an invented position.

4. **Create and verify the technical drawing.** For a new design, create a dimensioned sheet from explicit 2D geometry before the 3D build. Include necessary views, sections, notes, and review markers. Save an editable file and a rendered sheet. Inspect the sheet against sources and recorded decisions. Record its revision and hashes in `drawing_ref`. Use [drawing-first.md](references/drawing-first.md) for mode-specific rules.

5. **Fix the contract from the drawing.** Derive contract data from the verified drawing revision. Include parameters, units, coordinate frame, relation graph, operation graph, PMI, markers, test policy, and adapter scope. Save a revision and hash. Connect dimension and note IDs to parameters and operations. Resolve blocking questions while independent work continues. An approved assumption remains an assumption. Record changes in the controlling drawing first. Do not silently change a fixed contract.

6. **Build in a new run.** Load all inputs and inline dependencies. Use an isolated run. Keep logical IDs stable. Evaluate explicit dependencies in topological order. Verify intermediate geometry and the end body. Do not depend on active selections, existing documents, or session variables.

7. **Compare the model with the drawing.** Compare measured dimensions and necessary projections or sections with the fixed drawing revision. A later TechDraw output is a verification output. It does not replace the controlling drawing. Resolve differences. Do not change expected values to match an incorrect model.

8. **Export an AP242 candidate.** Use only the build that passed the drawing comparison. Export an evaluable construction graph, end BREP, necessary semantics and presentation, and supported review data. JSON text or named intermediate bodies alone do not meet the construction contract. Keep the last valid master file.

9. **Reconstruct from STEP alone in a new run.** The candidate is the only source of model content. Tools and the test policy are permitted inputs. Do not fill missing STEP data from the source contract, FCStd, drawing, or previous variables. Then, compare the result with independent expected values. For contract replay, also do a new build from the same fixed contract.

10. **Test changes and export again.** If the request includes a design change, use the defined sequence. First, reconstruct native operations from AP242. Next, verify a new drawing revision. Apply the change and compare the result with that drawing. Then, export AP242 and import it in a new process. A temporary change test uses the existing test policy. Assess geometry, construction, relations, original PMI, and review markers separately. Set affected data to an unverified status after a change.

11. **Review and deliver.** Release a master file only after all necessary tests pass. Supply candidate status, controlling drawing, register, reports, hashes, current limits, and the resume package. Inspect the actual display to verify visibility. Remove temporary files only from the artifact list of your own run.

## Reproducibility and evidence limits

Unrestricted drawing interpretation and construction strategy are not deterministic.
The verified build from identical contract data and a recorded toolchain can be reproducible.
Compare the operation graph, parameters, preserved relations, PMI, markers, and geometry under predefined tolerances.
Do not promise identical STEP bytes. Timestamps, entity numbers, and serialization can differ.

The skill documents a workflow and limited adapter components. It does not install a universal import or export service.
Revalidate modified adapters before use. Removed project tests do not certify the current skill package.
The remaining readers and construction exporter do not supply a general semantic-PMI authoring service.
Verify the required PMI export types and geometry associations through a separate adapter test before release.
A different CAD system requires its own verified adapter.
Do not promise full EXPRESS conformity, arbitrary geometric dimensioning and tolerancing (GD&T), or all tolerance systems.
Full relation transfer and automatic PMI or marker updates also require separate evidence.

## Separate run data

The skill contains procedures, adapter interfaces, and general technical references.
Receive drawings, contracts, geometry IDs, PMI layouts, and expected results as explicit authorized run inputs.
Keep source evidence and regression results in the run storage outside this package.
Do not copy part dimensions, assumptions, face names, or output paths into reusable defaults.
For each adapter revision, record independent capability tests with their actual input and output hashes.

At delivery, link the master file or clearly identified candidate, contract, test report, and optional derived working file.
State passed tests, remaining assumptions, missing functions, and the next executable action.
The reader must understand these items without the chat history.
