# Delivery artifacts and CAD backends

## Current support and target behavior

Use this reference to select delivery artifacts and assess backend capabilities.
The tables define requirements. They do not certify an installed implementation.

| Area | Current implementation | Target behavior |
|---|---|---|
| PDF evidence | PDF metadata, text extraction, rendering, cropping, and a limited vector profile. | Preserve source hashes and separate observations from design decisions. |
| CAD access | The MCP forwards FreeCAD tools only when the development proxy is explicitly exposed. | The MCP supplies stable domain tools with versioned schemas and capability evidence. |
| Drawing authoring | No general dimensioned-sheet authoring tool is implemented. | Create and review the editable technical drawing before the part build. |
| Construction and exchange | Maintained STEP readers inspect a limited profile. Inline backend adapters still require separate execution and validation. | Build editable operations and verify AP242 reconstruction within a declared profile. |
| PMI | Readers and API guidance do not establish a general semantic-PMI authoring service. | Verify semantic data, geometry associations, graphical presentation, and change behavior separately. |

Use [drawing-first.md](drawing-first.md) for drawing order.
Use [tooling-and-mcp-contract.md](tooling-and-mcp-contract.md) for current tools and proposed interfaces.
For optional final NX or SOLIDWORKS files, use [target-format-exports.md](target-format-exports.md).
These derivatives follow AP242 verification. They do not replace the master or its acceptance tests.

## Drawing delivery

The proposed default drawing package is an editable DXF and a PDF preview.
Use another editable format when the request or a verified adapter requires it.
The PDF is a review artifact. It does not replace the editable drawing.

| DXF content | Required evidence |
|---|---|
| Explicit 2D views and necessary sections | Stable geometry IDs and source references. Do not derive the controlling sheet from an early part build. |
| Native `DIMENSION` entities | Dimension type, measured geometry, value, units, precision, and permitted overrides. Text and line segments alone do not meet this requirement. |
| Units, scale, and projection method | Document units, sheet units, view scales, and unambiguous orientation. |
| Layers | Separate visible edges, hidden edges, centerlines, dimensions, notes, and review markers. |
| Notes and manufacturing data | Source references for material, tolerances, finish, threads, and other required data. Mark missing data explicitly. |
| Revision and review references | Drawing revision, hashes, review findings, and dimension-to-parameter mapping. |

For example, `D_LENGTH` can identify one drawing dimension.
A separate mapping can connect `D_LENGTH` to model parameter `length`.
These identifiers are generic examples. They supply no part values.

Before drawing release:

1. Reimport the DXF in a new read operation.
2. Compare dimension entities, geometry references, units, layers, notes, and values with the drawing specification.
3. Evaluate actual measurements independently of displayed text overrides.
4. Render the complete sheet and its necessary details.
5. Inspect dimension text, symbols, line types, fonts, clipping, overlaps, and marker visibility.
6. Compare the PDF preview with the same verified DXF revision.
7. Record hashes and actual results.

DXF dimension entities do not, by themselves, prove a constraint solver or associative model parameters.
Verify the selected writer, reader, dimension styles, fonts, and renderer together.

The ezdxf documentation describes dimension entities and their rendered block geometry.
Its drawing add-on supplies SVG, PDF, and raster output, with documented rendering limits.
These are candidate component capabilities, not implemented MCP support.
See the [dimension tutorial](https://ezdxf.readthedocs.io/en/stable/tutorials/linear_dimension.html)
and [drawing add-on](https://ezdxf.readthedocs.io/en/stable/addons/drawing.html).

## AP242 delivery and editability

The target AP242 master contains final BREP, required semantic PMI, graphical PMI, and supported constructive data.
A successful geometric STEP export does not prove the other content groups.

| Content group | Required evidence |
|---|---|
| Final BREP | Valid geometry, expected products, units, dimensions, and independent geometry comparison. |
| Semantic PMI | Dimension or tolerance type, value, units, modifiers, datums, and correct geometry associations. |
| Graphical PMI | Readable annotation geometry, text representation, annotation planes, views, and links to semantic items. |
| Constructive profile | Versioned supported operations, parameters, relations, units, anchors, and import/export directions. |
| Review data | Preserved origin, status, target IDs, and visible review markers, separate from original PMI. |
| Provenance | Artifact hashes, controlling drawing reference, adapter version, and actual test reports. |

A constructive profile defines the supported representation and reconstruction rules.
It does not imply that all AP242 readers support those rules.
Declare operation limits and unsupported relations before export.
Use evaluable STEP construction entities within the declared profile.
Do not treat an embedded JSON blob, named intermediate bodies, or a parameter list as proof of editable construction.

| Claim | Meaning | Required test |
|---|---|---|
| Readable parameter table | A reader can recover names, values, units, and descriptions. | Read and compare each required entry. |
| Driving parameters | A parameter controls specified geometry through recorded relations. | Change the parameter and measure all required effects. |
| Editable construction history | Native operations retain their dependencies and editable inputs. | Reconstruct the operation graph and edit a supported operation. |
| Preserved relations | Expressions or constraints remain linked after transfer. | Change an input and compare dependent values and geometry. Equal initial numbers are insufficient. |

Reconstructed history supplies evidence for the declared construction.
It does not prove unknown original authoring actions or design intent.

Perform the following tests for each required transfer profile:

1. Export only the build that passed comparison with the controlling drawing.
2. Inspect the actual AP242 schema and required entity references.
3. Start a new reconstruction worker with STEP as its only source of model content.
4. Record the files that the worker actually reads.
5. Compare reconstructed geometry, parameters, operations, relations, PMI, and review data with independent expectations.
6. Prepare and review a new drawing revision before a requested design change.
7. Apply a supported parameter change to the reconstructed operations.
8. Verify the changed geometry and all affected PMI associations and presentation.
9. Export a new candidate and reconstruct it in another fresh worker.
10. Record separate results for every content group.

A process boundary alone does not enforce input isolation.
The server must restrict worker inputs and keep independent expectations outside reconstruction.
Do not use a source contract, drawing, native file, or previous variables to replace missing STEP data.

OCCT documents AP242 dimensions, tolerances, and datums through XDE.
Its graphical-PMI reader has partial presentation support and does not handle character-based presentation.
Verify the required presentation types with the exact installed version.
See the [OCCT STEP guide](https://dev.opencascade.org/doc/overview/html/occt_user_guides__step.html)
and [STEPCAF writer API](https://dev.opencascade.org/doc/refman/html/class_s_t_e_p_c_a_f_control___writer.html).

## MCP boundary and backend selection

The skill uses only `drawing2cad-mcp` as its execution interface.
The MCP owns backend configuration, execution, artifact storage, and capability reports.
A backend can change without changes to the drawing or model contract when its supported profile remains equivalent.
Revalidate affected profiles after any backend or adapter change.

`cad_capabilities` currently reports implemented services, unavailable CAD services, and development-proxy exposure.
It does not yet supply verified CAD profile evidence.
The remaining operations below are proposals. Their names do not establish implemented tools.

| Responsibility | Proposed domain operation | Required output |
|---|---|---|
| Capability discovery | `cad_capabilities` | Backend versions, supported profiles, limits, directions, and evidence hashes. |
| Drawing creation and review | `drawing_create`, `drawing_review` | Editable sheet, rendering, findings, revision, and dimension mapping. |
| Parameter and operation graph | `model_validate`, `model_freeze` | Validated graph, relations, source references, and fixed revision hash. |
| Backend execution | `model_build`, `model_change` | Native artifact, feature map, measurements, and structured execution report. |
| STEP and PMI transfer | `step_export`, `step_reconstruct` | Candidate, decoded content, anchor map, and separate content claims. |
| Independent validation | `model_compare`, `step_validate` | Geometry, construction, relations, semantics, presentation, and reconstruction results. |

Keep backend-native types and execution code inside adapters.
Use stable logical IDs, typed data, artifact hashes, and explicit error codes at the domain boundary.
Report unsupported operations before model mutation.
A fallback must retain the same acceptance criteria.

The existing `freecad_*` tools can remain an optional legacy profile through the same MCP.
This profile exposes upstream behavior and privileges. It does not add domain gates or headless capabilities.
Do not require a second FreeCAD MCP connection in the skill.

| Candidate | Documented capabilities | Limits for this workflow |
|---|---|---|
| FreeCAD legacy profile | Native document operations and inline execution through the existing proxy. Limited reconstruction adapters are documented in this skill. | Drawing authoring, general PMI writing, headless rendering, and complete transfer still require evidence. |
| OCCT with XDE/STEPCAF | Geometry and STEP exchange with dimension and tolerance data. | Sheet composition and parameter/history reconstruction require adapters. Graphical PMI has documented limits. |
| CadQuery | Python geometry construction; STEP and 2D DXF export. | Its documentation states that exchange formats do not carry its parametric data. It does not establish complete PMI transfer. |
| build123d | Python geometry construction; sections, projections, layered DXF/SVG, and STEP export. | Documented shape export does not establish parameter graph, history, or semantic-PMI transfer. |
| HOOPS Exchange with a modeler | STEP AP242 semantic and graphical PMI export, views, and validation properties. | It is an exchange component. Its STEP writer does not export STEP drawings. General history transfer is not established. |
| Spatial modeler with 3D InterOp | Geometry SDKs for Linux, Windows, and Mac; translation of semantic and graphical PMI. | Verify exact STEP directions, PMI types, server terms, and history behavior with a scoped test. |

No backend migration is selected by this reference.
Compare candidates with the same generic fixtures and acceptance criteria before selection.
Do not infer workflow support from a product feature list.

Authoritative candidate documentation:

- [CadQuery import and export](https://cadquery.readthedocs.io/en/latest/importexport.html).
- [build123d import and export](https://build123d.readthedocs.io/en/latest/import_export.html).
- [HOOPS STEP writer](https://docs.techsoft3d.com/exchange/latest/start/format/step_writer.html).
- [Spatial modeling SDKs](https://www.spatial.com/solutions/3d-modeling).
- [Spatial 3D InterOp](https://www.spatial.com/solutions/cad-translation/3d-interop).

For deployment, review dependency licenses and commercial server terms separately.
Record the selected package versions, image identity, renderer, and supported profiles in the run manifest.
