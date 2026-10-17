# Model contract, schema 2

> Extended target contract for later AP242 adapter work. It is not the M1 part-description schema.
> Use the live `part_validate` schema for M1. Do not claim these fields are implemented merely because they are documented.
> Legacy FreeCAD references below are deprecated development evidence.


The contract contains declarative data, not executable code.
It separates source interpretation, construction, review, and evidence.
Schema 2 adds explicit capabilities, a complete review register, and handoff requirements to the previous contract.
It does not automatically migrate or recertify existing case fixtures.
For legacy data, record `source_schema_version`, the field mapping, and missing information.
New verification groups without evidence remain `not_tested`.

## Required fields

| Field | Content and invariant |
|---|---|
| `contract_version`, `model_id`, `revision`, `parent_revision` | Schema and model revision. A content change requires a new revision. |
| `sources[]` | Stable ID, permitted path or URI, SHA-256, pages, drawing revision, and role. A hash does not replace accessible content. |
| `toolchain`, `capability_profile` | MCP and addon, FreeCAD, OCCT, Python, PythonOCC, adapter ID, version and code hash, specific functions, and verified limits. |
| `units`, `frame` | Length and angle units, origin, orthonormal right-handed axes, drawing reference, and source of each coordinate decision. Do not use implicit GUI units. |
| `evidence[]` | ID, source, hash, page, view or detail, text or visually observed finding, reproducible region, coordinate convention, and interpretation status. |
| `parameters[]` | ID, data type, value or `null`, unit, evidence IDs, and origin: `explicit`, `derived`, `inferred`, or `unresolved`. Apply the same rules to values and positions. |
| `relations[]` | ID, declarative operator or constraint, input and output IDs, units, evidence, and actual preservation scope. An empty list promises no formulas or constraints. |
| `operations[]`, `root` | Stable IDs, type, parameter and profile references, placement, dependencies, and refinement rule. The graph must be acyclic and fully resolvable. |
| `pmi[]` | Original drawing information only: `source_id`, semantic type, value, unit, source evidence, targets, derivation references, and presentation. |
| `review_register[]`, `review_markers[]` | Every derived, assumed, or unresolved value or position, and every conflict. Include origin, status, affected IDs, anchor, and a separate visible marker. |
| `validation_policy`, `required_claims[]` | Predefined numerical tolerances, solid count, graph, PMI and marker checks, relevant change test, and required verification directions. |
| `claims` | Separate actual verification statuses from [validation.md](validation.md). Do not summarize capabilities that were only promised. |
| `canonicalization_profile`, `contract_sha256` | Documented hash method and hash of the defined model content, without self-reference. Handle run data and hash fields separately. |

An `evidence` entry distinguishes readable original text from interpretation.
OCR text or a ratio measured from an image is not an explicit dimension.
For derived information, keep the complete evidence and relation chain.
Mark unreadable characters as unresolved.
Do not average values from conflicting drawing views.

## Complete review register

Create an entry for **every** `derived`, `inferred`, or `unresolved` parameter.
Also create entries for uncertain positions, assignments, and simplified geometry.
One entry can cover several values if they have the same origin, decision, and anchor.
Its `affected_ids` must explicitly list every affected value.
A correctly calculated derived value must keep its derived classification.

| Register field | Meaning |
|---|---|
| `review_id`, `kind` | Stable ID; `derived`, `assumed`, `unresolved`, or `conflict`. |
| `affected_ids[]` | All affected parameters, relations, operations, positions, selectors, or PMI assignments. |
| `value`, `unit`, `alternatives` | Applied value or `null`; alternatives if relevant. Do not invent a number for an unresolved mandatory input. |
| `source_refs[]`, `derivation_ref`, `rationale` | Source and evidence IDs, exact calculation if applicable, and reason. If the drawing omits information, record the examined views and the omission. |
| `decision_status` | `open`, `accepted`, `rejected`, or `superseded`. For `accepted`, record the decision maker, evidence, and scope. Do not present an LLM choice as user approval. |
| `verification_status` | `not_tested`, `pass`, `fail`, or `stale`. This status is independent of the decision. Approval does not prove geometric correctness. |
| `blocking` | Specific phases or claims that cannot pass without a resolution, with reasons. |
| `anchor` | Logical construction ID, geometric selector or fingerprint, and source region. Include resolution status: `resolved`, `ambiguous`, or `unresolved`, and expected target count. |
| `marker_id`, `revision`, `history` | Separate visible review marker and traceable changes. |

`accepted` does not convert an assumption into original drawing information.
Resolved items can remain available in the history.
If a source is corrected, mark the old entry as superseded.
Create the new evidence chain.
Do not silently delete invalid assumptions from the register.

For an unresolved geometric location, record a source region and the intended logical target.
Keep its geometric anchor explicitly unresolved.
Existing unambiguous reference geometry can serve as a reference, but not as the claimed target location.
Show a visible review note with its ID and the text "Location unresolved".
If no permitted target value exists, block the dependent build.
An invented arrow on the solid does not resolve the issue.

## Visible review markers separate from original PMI

Each register entry references a marker with `marker_id`, `review_id`, readable text, target anchor, display mode, view or annotation plane, position, and leader.
The marker also records its visibility status.
Its text includes origin and status.
Useful prefixes are "DERIVED", "ASSUMED", and "UNRESOLVED".
Do not encode status through color alone.
Keep review groups and original PMI separately switchable.
Display the markers before the review handoff.

For resolved geometry, attach markers to the actual target geometry or feature ID.
For an unresolved location, use a visible review list or source view with the unresolved reference.
Record `placement_status=unresolved`.
After a CAD build, bind each marker to its newly resolved targets.
Keep the source region.
Fix marker text, anchors, and visibility with the revision.

Review markers are not original dimensions, manufacturing tolerances, or standardized semantic PMI.
Use separate `review_id`, `marker_id`, and, if applicable, `metadata_id` values.
Do not reuse a drawing PMI `source_id` for these markers.
Count and verify original PMI, review metadata, and their graphics separately.

For a self-contained STEP handoff, the selected adapter must demonstrably store and restore the register and markers from STEP alone.
The local namespaced container in [inline-review-envelope.md](inline-review-envelope.md) defines a dedicated adapter profile: `drawing2cad.review_annotations.v1`, with schema `drawing2cad.review-annotations/1`.
This profile is not equivalent to universal AP242 PMI support.
A stored JSON property string alone proves neither visible markers nor linked targets.
If the adapter lacks this function, report its status and limitation.
An external register alone does not meet the required STEP-only claim.

## Operation DAG and relations

First verify references and units.
Make sure that the graph has no cycles.
Then sort the graph topologically, with stable ID order for independent nodes.
A difference operation has ordered operands.
Keep Boolean grouping and the refinement rule unchanged during reconstruction.
These changes can affect geometry, topology, and face assignments.

Distinguish the declarative vocabulary from verified adapter support:

- `cylinder`: radius, height, and placement. Segments require a verified representation.
- `box`: three positive lengths and placement.
- `polygon_profile`: ordered, closed, planar points without self-intersection.
- `extrusion`: profile reference, normalized direction, positive depth, and solid mode.
- `union`, `difference`, `intersection`: operand references and an explicit refinement rule.
- `fillet`: construction base, constant positive radius, unambiguous edge selectors, and exported topology anchors. See [edge-blends-and-thread-pmi.md](edge-blends-and-thread-pmi.md).

At the capability gate, examine other operations and the orientations and units actually supported.
A valid JSON description is not an implemented CAD operation.

Calculate declarative relations through a restricted operator tree with explicit units and parameter references.
Examples are `add`, `sub`, `mul`, `div`, `sqrt`, and explicitly supported trigonometric functions.
Do not use `eval` on document, contract, or STEP content.
If you claim editable dependencies, those dependencies must have actual links in the native model.

For each relation, record its preservation scope with evidence: `contract_only`, `native_linked`, `neutral_encoded`, or `fresh_reconstructed`.
`neutral_encoded` is not a substitute for `fresh_reconstructed`.
Equal numbers, many Spreadsheet cells, or fully constrained primitive sketches do not prove shared family parameters, position relations, or original design intent.
If a radius change must move tangent points, that relation must exist in the contract, native model, and agreed neutral format.
Otherwise, claim only the independent parameters that were actually preserved.

The profile in [inline-review-envelope.md](inline-review-envelope.md) can add native UI mappings, labels, and display strategies through `drawing2cad.editable_ui.v1`, with schema `drawing2cad.editable-ui/1`.
Construction and construction values must still come from evaluable STEP operations.
UI metadata must not replace missing operations or hide conflicting values.

## Geometric selectors and original PMI

`Face17` or `Edge3` is only a runtime result.
Describe targets through construction origin and geometric properties.
For a cylinder, specify its axis, center, radius, and axial range.
For a plane, specify its normal, position, and boundary.
For an edge, specify its curve type, length, endpoints, and distance from the reference curve.
Symmetry or similar faces can make these properties ambiguous.
If ambiguity occurs, use additional origin information or topological adjacency.
For several holes, specify the complete ordered target set.

Each selector must match exactly the expected target count.
No matches or unintended multiple matches are errors.
Resolve selectors again after Boolean operations, fillets, fresh builds, and changes.
Use historical face numbers from a case fixture only after a complete fingerprint match.
During export, connect actual STEP references to logical IDs and selectors.
Entity IDs apply only within their file.

An original PMI record contains these separate groups:

- **Semantics:** original text, type, nominal value, unit, explicitly specified tolerance, datum or GD&T, `source_id`, and evidence.
- **Targets:** unambiguous selectors, expected target set, and derivation graph if applicable, such as a connection between two cylinder axes.
- **Graphics:** view, annotation plane, text anchor, dimension lines, extension lines or polylines, and the link to the associated semantics.

Treat nonnumeric information, such as thread designations, as semantic properties linked to actual geometry.
A simplified cylinder is not a fully parametric thread feature.
Do not invent pitch, tolerance class, material, roughness, or datums without drawing evidence.
General notes require a traceable scope.
A list of dimension texts is insufficient for reproducible presentation.
Graphic lines are not semantics.
Invisible semantics are not verified presentation.
Numerical validation tolerances are not manufacturing tolerances.

## Fixed content, hash, and run state

The canonicalization profile specifies UTF-8, key order, number encoding, Unicode handling, array order, and exact included and excluded fields.
Use the same implementation and version, or verify equivalent canonicalization.
Require finite numbers.
Exclude `contract_sha256`, changing run reports and claims, timestamps, and host-specific output paths.
Include construction, units, evidence, decisions, relations, PMI and marker specifications, and validation policy.
Do not remove all paths if this removes source identity.
Identify sources through stable IDs and content hashes.
Also calculate a separate hash of the complete contract file.

A change to fixed model content requires a new revision with its parent hash.
This rule includes the final presentation layout and decisions.
For a replay, do not recreate the contract from memory.
If an existing STEP file has no contract, create an import contract from its decodable data.
Explicitly report unknown source and relation information.

Keep run IDs, candidate paths, progress, and temporary artifacts in a separate run manifest.
The resume package in [model-agnostic-workflow.md](model-agnostic-workflow.md) identifies sources, contract, toolchain, actual results, open items, and the next executable step.
Do not hide executable payloads as purported JSON data.
