# Model-independent workflow and handoff

This reference defines inputs, outputs, and gates.
[model-contract.md](model-contract.md) defines their content.
[validation.md](validation.md) defines the evidence.
[tooling-and-mcp-contract.md](tooling-and-mcp-contract.md) gives tool names and specific calls.
The roles below define responsibilities.
They do not require a specific LLM or multiple agents.

For new construction, this sequence is mandatory: **dimensioned technical drawing → verified parametric build → STEP**.
[drawing-first.md](drawing-first.md) defines the controlling sheet, hash references, and application to replays, isolated STEP import tests, and changes.
The phases below give the full `new_drawing` workflow.
Other modes use only applicable phases.
Do not invent missing evidence retrospectively.

The production workflow must run on a fully headless server through `drawing2cad-mcp`.
No phase can require an open FreeCAD GUI or a GUI dispatcher.
Test drawing rendering and PMI presentation separately from geometric computation.
An optional web client can submit jobs and display server artifacts. It does not execute required CAD phases.
Existing GUI-based development tests do not prove this deployment.

## Replaceable components

- **Interpretation:** An LLM or person reads only permitted drawings, collects evidence, and proposes a construction. Origin, construction, and undimensioned details can vary. Record the model identifier and methods as provenance. They do not guarantee quality.
- **Contract verification:** A reviewer requires fully referenced data, open decisions, necessary capabilities, and predefined tests. The fixed contract separates interpretation from replay.
- **Deterministic core:** An adapter evaluates explicit relations and operations in stable order. It reads data, not executable code generated from source documents. An unknown operator causes a traceable error.
- **CAD execution:** The current execution profile permits only FreeCAD-MCP. Other CAD systems are possible adapter targets. They are not implemented alternatives. Native types, geometry kernels, and neutral-format mappings each require separate tests.
- **Verification and review:** Independent readers compare actual results. The LLM must not estimate missing measurements or references. It must not replace them with plausible success reports.

A different LLM does not require new drawing interpretation if the next step uses the fixed contract.
A different kernel, adapter code, or export profile requires a new capability gate and the affected replay tests.
Different valid constructions of the same external shape are not identical operation DAGs.

## Input package

Before the first CAD mutation, record a declarative `request` object or equivalent unambiguous structured information:

| Field | Required content |
|---|---|
| `request_id`, `mode` | Stable request ID; `new_drawing`, `replay_contract`, `import_step`, or `edit_model`. |
| `source_allowlist[]` | Exact permitted paths or URIs, roles, hashes, and pages. Distinguish `construction_source`, `verification_only`, and `tool_reference`. |
| `required_outputs[]` | For new construction, the controlling editable drawing and rendered sheet. Other outputs can include an AP242 master, native working file, original PMI, review markers, report, and preview. Specify required transfer directions. |
| `required_claims[]` | Claims that require evidence: drawing before build, model and drawing consistency, STEP-only build, contract replay, native editability, relation transport, re-export, semantics, and display. |
| `decisions[]` | Existing user decisions with references. Do not request approval again for these decisions. |
| `output_root`, `run_id` | Explicit accessible output location and separate run ID. Do not copy paths from case examples. |
| `validation_policy` | Units, tolerances, geometry and presentation checks, and requested change test. Fix these before result comparison. |

For `replay_contract`, the specific contract and its revision and hash are the construction source.
For `import_step`, only the selected STEP file supplies model content.
A verification contract can serve as a reference only for a subsequent comparison.
For `edit_model`, also record the change, base model hash, and affected requirements.
If a source is missing or its hash differs, stop work that depends on that input.
Report the finding.
Continue independent work that remains possible.

## Capability gate before each commitment

Derive the requirement list from the specific contract.
Compare it with the capabilities of the selected adapter version.
Before a contract exists, do only a preliminary comparison.
After the `freeze` phase, do the complete comparison again.
For each capability, record `capability_id`, direction, permitted parameter, geometry and unit ranges, `required`, and status.
Also record tool and code hashes and evidence paths and hashes.
Use these statuses: `verified`, `untested`, `unsupported`, or `failed`.
A historical test applies only within its recorded scope.
It is not evidence of a fresh run.

| Capability | Minimum gate question |
|---|---|
| `source_observation` | Can the permitted pages and details be inspected legibly and referenced with stable evidence? |
| `drawing_authoring` / `drawing_render` | Can explicit 2D geometry produce an editable, dimensioned technical sheet and readable rendering before the 3D build? An existing 3D TechDraw export does not prove this method. |
| `drawing_model_check` | Can model dimensions and required projections and sections be independently compared with the controlling sheet? |
| `isolated_execution` | Are MCP execution, a fresh process, explicit inputs, and a structured result possible without script files? |
| `headless_pipeline` | Can every required phase complete on the server without FreeCADGui, a GUI dispatcher, or a display server? Record worker and renderer evidence separately. |
| `native_build` | Can each specific operation produce an editable native result with its placement, profile, unit, and dependencies? |
| `constructive_export` / `constructive_import` | Can AP242 store all required operations and topology anchors in an evaluable form? Can they be read from STEP alone? |
| `relation_transport` | Are formulas and constraints transferred and linked again, or only their evaluated numbers? Do a separate test for each relation type. |
| `brep_reference` | Can the same STEP be read independently as final geometry without auxiliary solids appearing as additional products? |
| `pmi_semantics` / `pmi_presentation` | Are all required PMI types, target sets, units, derivations, and graphic references supported? |
| `review_register_transport` / `review_marker_display` | Are register status, origin, targets, and visible review markers separately preserved and recovered from STEP alone? |
| `authoring_export` | Can the reconstructed native model be fully exported again after changes? Which data are not updated automatically? |
| `verification` | Are an independent reader, geometric comparison, fresh replay, and actual visual inspection available? |

First test each required untested function in an isolated MCP run limited to that function.
If support is missing, produce a report and an inspectable partial result.
Do not make the affected master claim.
A successful BREP export must not hide missing register or marker transport.
If the adapter supports only an external register, identify the result as a limited candidate.
It does not meet a requirement for a fully self-contained AP242 master.

The interfaces below are a working contract, not a newly implemented SDK.
Adapt existing inline blocks to these roles through explicit inputs.
A block with fixed case paths or names is a regression test.
A copy of that block is not a generic adapter.

## Phases with explicit transitions

| Phase | Permitted inputs | Outputs | Gate to the next step |
|---|---|---|---|
| `intake` | Request, permitted files | Input manifest, source hashes, preliminary capability profile | Source and scope are unambiguous. |
| `observe` | Only permitted drawing pages | Evidence inventory, original information, conflicts, draft register | Each used interpretation has provenance. Open items are visible. |
| `drawing_prepare` | Evidence, decisions, explicit 2D geometry | Editable dimensioned sheet, rendered sheet, register markers | Required construction views, sections, and information exist. No part build has started. |
| `drawing_review` | Sheet and rendering, source evidence, register | Actual visual and dimension checks, reviewed drawing revision, hashes | Sheet is readable and consistent. Mandatory open items are resolved. Assumptions are marked. |
| `freeze` | Reviewed drawing revision, evidence, decisions, capability findings | Versioned model contract with drawing reference, DAG, relations, PMI and marker specifications, and hash | Construction values come from this exact drawing. No mandatory parameter is unresolved. Required capabilities are verified. |
| `build` | Fixed contract, versioned adapter, explicit run paths | Native operations, intermediate geometry, build report, optional FCStd | DAG and shapes are valid. Actual parameters match the contract. |
| `drawing_model_check` | Build, exact same contract, controlling drawing revision | Dimension, projection, and section comparison; optional derived verification drawing | Model matches the controlling drawing. No hidden adjustment of reference values occurred. |
| `export` | Build outputs verified against the drawing, exact same contract, export profile | Separate AP242 candidate, representation and anchor mapping, export report | Export identifies the verified build. Content is complete. Schema and references are verified. |
| `fresh_rebuild` | Only AP242 as model source, adapter, validation policy | Reconstructed native operations, decoded PMI and register, measurement report | Construction and final BREP agree. Reference comparison follows. |
| `replay` | Unchanged contract for a new build; AP242 for a new independent import | Second fresh run and comparison report | Required reproducibility is demonstrated. |
| `edit_roundtrip` | STEP-only reconstruction, new drawing revision reviewed before the design change, explicit change, applicable reverse adapter | New revision, drawing comparison, changed STEP candidate, another STEP-only build | Change and its effects are preserved. Affected semantics and markers are verified again. Identify temporary reset tests separately under the validation policy. |
| `review` | Actual outputs and reports | Status for each verification group, visible original PMI, separately visible review markers, open items | Required tests pass. No gaps are hidden. |
| `publish` | Candidate that passed, artifact manifest | Current master reference, hashes, report, resume package | Replace the last valid master only now. |

The controlling technical sheet must exist before `build`.
The graphic 3D PMI presentation can require an initial CAD build.
In that case, use this sequence only after the drawing review:
`freeze → build → PMI layout review → new contract revision → build → drawing_model_check → export`.
This later work does not replace the drawing gate.
Before final export and replay verification, include the final PMI layout and stored text polylines in the fixed contract.
If construction information changes, first create and examine a new drawing revision.
Do not change previous revisions retrospectively.
Do not read layout requirements from session state.

The `replay` and `edit_roundtrip` phases pass only if they were actually executed.
If the request requires these phases, a missing test blocks the corresponding publication.
Otherwise, explicitly report `not_tested`.
A geometric re-export does not prove re-export of PMI, relations, or the register.

## Data flow without hidden session dependencies

Each inline task receives a complete execution envelope.
It contains `run_id`, `phase`, input artifacts with hashes and roles, permitted contract hash, adapter ID and code hash, configuration, output destinations, and timeout.
The payload imports its own libraries.
It defines or loads all helper functions from the permitted documented code blocks.
Before a mutation, it verifies expected units, input files, and function signatures.

A result contains at least `status`, `phase`, actually read `source_inputs`, generated `artifacts` with hashes, `metrics`, `warnings`, `errors`, and the completed checkpoint.
An exit code alone is not evidence of success.
The documented FreeCADCmd behavior also requires a structured success signal.
An error report has a specific error code.
Examples are `SOURCE_HASH_MISMATCH`, `UNRESOLVED_VALUE`, `UNSUPPORTED_OPERATION`, `AMBIGUOUS_ANCHOR`, `STALE_PMI`, and `MISSING_MARKER_TRANSPORT`.

DAG construction and pure-data verification can be prepared independently.
CAD mutations and exports for the same document run sequentially.
After a timeout, first examine the status and actual output files.
Do not start concurrent retries.
For a retry, use new candidate paths or replace only proven incomplete outputs from the same run.
If fresh evidence is required, do not continue from an open GUI document.

The STEP-only reader has no original construction data outside STEP.
External expected values can support a *subsequent* comparison.
They must not reconstruct a missing operation, relation, PMI, or marker position.
The reader can prove drawing provenance only to the extent that the corresponding references were stored.
Report missing provenance as `unknown`.
Do not supply it from a familiar reference part.

## Handoff and resume package

The package contains declarative data and referenced artifacts.
Do not create an executable resume file.
`run_manifest.json` can represent the structure below.
The table is the normative field description.
It is not a model contract populated with example values.

| Field | Content |
|---|---|
| `handoff_version`, `request_id`, `run_id`, `mode` | Schema, request, run, and active mode. |
| `skill_version`, `contract_ref` | Skill version; contract file, revision, file hash, and canonical model hash. For a pure STEP import, initially use `null` with a reason. |
| `drawing_ref` | Controlling drawing ID and revision, file and render hashes, verification, and dimension-to-parameter mapping from [drawing-first.md](drawing-first.md). For a pure STEP-only import, initially use `null` with a reason. |
| `source_allowlist[]` | Exact sources and roles; permitted input set for the next phase. |
| `toolchain_ref`, `capability_ref` | Versions, adapter and payload hashes, capability matrix, and evidence. |
| `completed_phases[]` | Actual status, input hashes, output hashes, report, and time for each phase. |
| `next_phase`, `next_action` | One specific repeatable step. Include the documented inline entry reference and explicit input and output fields. |
| `pending_decisions[]`, `review_register_ref` | Unresolved items, previously authorized assumptions, affected IDs, and blocking reason. |
| `validation_ref`, `claims` | Measurement reports and separate status for each verification group. Do not copy a general success status. |
| `artifacts[]`, `current_master` | File path and hash, role, revision, and generating phase. Keep the last valid master separate from the candidate. |
| `process_state` | Actual active process or job, ID, and last known status; or explicitly `none`. |
| `cleanup_candidates[]` | Only files generated by this run that can later be removed. Do not use a general directory deletion pattern. |

For another LLM to resume work:

1. Read the package and referenced documentation.
   Use only permitted artifacts with matching hashes.
   If files differ, identify the last proven checkpoint.
2. Verify the MCP and process status and capability profile again.
   Resolve open processes before new mutations.
   Test version differences separately.
3. Retain the register and existing decisions.
   Do not reinterpret the drawing only because chat context is missing.
   Identify missing mandatory information precisely.
4. Determine `next_phase` from actual reports.
   An existing filename or screenshot does not prove a passed checkpoint.
   Repeat an interrupted phase in a new isolated run from its validated inputs.
5. Create the complete input envelope.
   Execute the documented inline entry with explicit arguments.
   Measure the outputs.
   Update the manifest.
   Set success statuses only from actual returned results.

A self-contained handoff identifies the remaining work, necessary inputs, capability scope, and missing evidence.
If only STEP is available on a new host, start with `import_step`.
Report the absence of other evidence.
Do not invent a complete historical contract status.

## Limits of existing components

The references document limited adapters for native operations, constructive STEP representations, PMI reading, selected text properties, and graphic polylines.
Verify the current adapter revision and toolchain before use.
These references do not provide a general semantic-PMI writer or drawing parser.
They do not prove complete constraint-solver transport or universal unit, orientation, or GD&T support.
The general review register required here remains a contract and verification target, including editable, transferable markers.
Existing case-specific assumption metadata alone do not prove its complete implementation.

Keep run evidence outside the skill package. Supply permitted evidence through the run manifest.
For new geometry, relations, note types, or marker classes, explicitly extend and test the adapter scope.
If the reverse adapter is missing, keep the existing master.
Deliver the candidate with its missing capability identified.
Parser success is not EXPRESS certification or evidence of support in other CAD systems.
