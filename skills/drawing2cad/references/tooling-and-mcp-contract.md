# Tool inventory, common MCP interface, and CAD service design

Date: 2026-10-17. `drawing2cad-mcp` in the project folder of the same name combines PDF preparation and the existing FreeCAD MCP. See [drawing2cad-mcp.md](drawing2cad-mcp.md) for use instructions. The live catalog contains local PDF tools and dynamically forwarded `freecad_*` tools. The 17 FreeCAD calls below preserve the upstream snapshot from 2026-10-16. The `cad_*` tools in Sections 6–9 remain a **design proposal, not an implementation**. AP242 functions remain documented inline components. There is no general drawing parser or universal parametric STEP service.

[model-agnostic-workflow.md](model-agnostic-workflow.md) defines the process and mandatory evidence. [model-contract.md](model-contract.md) defines model content. Use the FreeCAD tools of the common MCP for CAD work. Inline Python is permitted. Do not create ad hoc `.py`, `.FCMacro`, `.ps1`, `.bat`, or other executable model helper files. The versioned Python server requested by the user is a separate software component. Its PDF path allowlist does not constrain arbitrary Python code in the FreeCAD proxy.

## 1. Evidence and inventory limits

The table below documents the FreeCAD tools available on 2026-10-16. For each new run, request the live catalog with descriptions and input schemas. The proxy uses the current upstream interface. Generated catalog files are local run artifacts. They are not part of the versioned skill.

Determine versions and paths again for each host. Recorded host paths are not installation requirements that apply worldwide. [execution-and-ap242.md](execution-and-ap242.md) documents tested reference versions, including PythonOCC `7.8.1.1`. Verify their availability separately on a new host.

Write new inventories, host snapshots, and test reports to the ignored project `output/` folder. Historical files under `references/tooling/` can exist locally. They are also ignored and are not required by the skill. This reference and the linked workflow documents contain the authoritative execution rules, adapter entry points, and interface designs.

The inventory distinguishes `advertised` (tool available), `observed` (local observation), and `verified_subset` (evidence from a named test). It also distinguishes `untested` and `unsupported`. A tool description alone proves neither successful execution nor full functionality. Reference models supply test evidence only. Never transfer dimensions, object names, PMI counts, or layouts from other drawings into a new model task.

## 2. FreeCAD upstream snapshot and proxy mapping

Through `drawing2cad-mcp`, `execute_code` becomes `freecad_execute_code`. `get_rpc_status` becomes `freecad_get_rpc_status`. The client namespace before the tool name depends on the host. Input schemas and MCP result content still come from the existing FreeCAD server. The prefix is not a new CAD implementation. If the upstream is unavailable, PDF tools remain usable. Verify CAD access separately. Do not configure the historical calls below as a second agent interface required at the same time.

The common return type is `CallToolResult`, usually with text and an optional screenshot. This tool interface has no consistent domain result schema for errors and measured values. Thus, also validate structured results from the inline adapter.

The definitions below contain all parameters offered in the historical snapshot. `?` means optional. `View` is `Isometric | Front | Top | Right | Back | Left | Bottom | Dimetric | Trimetric`. `Record` means `{[key:string]:unknown}`. For the installed version, the live catalog descriptions and schemas are authoritative.

| Actual tool name | Input | Purpose and execution limit |
|---|---|---|
| `mcp__freecad__create_document` | `{name:string}` | Create a GUI document. |
| `mcp__freecad__create_object` | `{doc_name:string,obj_name:string,obj_type:string,obj_properties?:Record,analysis_name?:string\|null,include_screenshot?:boolean,view_name?:View}` | Create native objects. FEM helpers are available but are not required for AP242. |
| `mcp__freecad__edit_object` | `{doc_name:string,obj_name:string,obj_properties:Record,include_screenshot?:boolean,view_name?:View}` | Write properties. This changes document state. |
| `mcp__freecad__delete_object` | `{doc_name:string,obj_name:string,include_screenshot?:boolean,view_name?:View}` | Delete an object. Delete only objects explicitly assigned to the run. |
| `mcp__freecad__execute_code` | `{code:string,include_screenshot?:boolean,view_name?:View,timeout?:number\|null}` | Execute complete inline Python on the GUI thread. Timeout: positive finite seconds; default 90, maximum 1800. Each value applies separately to queue and execution budgets. |
| `mcp__freecad__execute_code_async` | `{code:string}` | Background thread for intensive, pure geometry calculation. **Not an isolated process.** GUI and document writes require injected `commit(fn,timeout=120)`. |
| `mcp__freecad__execute_code_headless` | `{code:string,timeout?:number}` | Advertised: separate `freecadcmd`, default timeout 600 s. Local result: `freecadcmd not found`. Compliance with the prohibition on temporary script files was unresolved. This execution path was not authorized. |
| `mcp__freecad__get_async_status` | `{job_id?:string}` | Async job status. With no ID: active jobs and up to 20 recently completed jobs. History persists only until FreeCAD stops. |
| `mcp__freecad__get_rpc_status` | `Record` (usually `{}`) | RPC and GUI dispatcher status, stalled operation, and version comparison. Does not require the GUI thread. |
| `mcp__freecad__get_object` | `{doc_name:string,obj_name:string,include_screenshot?:boolean,view_name?:View}` | Read object properties. For a read-only inventory, use `include_screenshot:false`. |
| `mcp__freecad__get_objects` | `{doc_name:string,include_screenshot?:boolean,view_name?:View}` | Read objects and properties in a document. |
| `mcp__freecad__list_documents` | `Record` (usually `{}`) | Read open document names. |
| `mcp__freecad__get_view` | `{view_name:View,width?:number\|null,height?:number\|null,focus_object?:string\|null}` | Capture the actual active view. Apply orientation and focus. Thus, this call changes state. |
| `mcp__freecad__reload_document` | `{doc_name:string}` | Close an open document and reload its file. First examine its state and unsaved changes. This is not a harmless read call. |
| `mcp__freecad__get_parts_list` | `Record` (usually `{}`) | List the parts library. This is not part of the tested reconstruction process. |
| `mcp__freecad__insert_part_from_library` | `{relative_path:string,include_screenshot?:boolean,view_name?:View}` | Insert a library part. This adds a construction source and requires task authorization. |
| `mcp__freecad__run_fem_analysis` | `{doc_name:string,analysis_name:string,timeout?:number,include_screenshot?:boolean,view_name?:View}` | CalculiX/FEM. Blocks the GUI synchronously. Do not make concurrent RPC write calls. Available but untested in this AP242 workflow. |

Screenshots are enabled by default for calls with optional `include_screenshot`. Disable them for analytical calls. `execute_code` shares a live Python namespace. Each payload must import its own dependencies, receive complete inputs, and use its own names. Serialize write calls from different agents to the same document or namespace.

## 3. Host, interpreters, libraries, and utilities

| Component | Observed version or exact path | Use and limit |
|---|---|---|
| FreeCAD | 1.1.4; commit `4fd3bf320d9566a27e60069fc8387448aaa3a094` | Native documents and operation tree. |
| OCCT | 7.8.1 | BREP, Boolean operations, fillets, and STEP/XCAF. |
| Python in FreeCAD | 3.11.14, conda-forge, MSC v.1944 AMD64 | ABI of this build. Do not substitute arbitrary system Python. |
| PythonOCC | 7.8.1.1, documented reference version | `OCC.Core.*`. Apply binding limits separately. |
| MCP addon | 0.1.27, observed | RPC bridge. This is not independent confirmation of the server package version. |
| GUI | `C:/Program Files/FreeCAD 1.1/bin/FreeCAD.exe` | Existing MCP connection and actual views. |
| Headless | `C:/Program Files/FreeCAD 1.1/bin/FreeCADCmd.exe` | Fresh `GuiUp == 0` process through stdin. |
| PythonOCC interpreter | `C:/Program Files/FreeCAD 1.1/bin/python.exe` | Separate inline PythonOCC process when necessary. Verify ABI availability for each import. |
| Operating system | `Windows-10-10.0.26200` from the Python platform string | No independent product or edition identification. |
| PDF rendering | `C:/Users/mail/.cache/codex-runtimes/codex-primary-runtime/dependencies/native/poppler/Library/bin/pdftoppm.exe` | Render authorized PDF pages. The version number was not recorded in this snapshot. |
| Document Python | `C:/Users/mail/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe` | `pypdf`, `PIL` for source reading, detail images, and image inspection. No CAD calculation outside MCP. Package versions were not recorded in the snapshot. |
| Font | `C:/Windows/Fonts/arial.ttf` | `Part.makeWireString` for new text outlines. Record font hash, deflection, and layout in the contract. For replay, use stored polylines. |

### Actual library and API roles

- **Python standard library:** `json`, `hashlib`, `os`, `re`, `math`, `subprocess`, and `sys` for stdin bridges. These support file and hash validation, P21 parsing, declarative data, and process control with finite limits. Use `exec` only for trusted, complete adapter code in memory. Never execute drawing content, STEP properties, formula strings, or JSON model fields.
- **FreeCAD/Part:** `newDocument`, `closeDocument`, `openDocument`, `doc.addObject`, `getObject`, `recompute`, `saveAs`; `Vector`, `Rotation`, `Placement`. Native operations: `Part::Box`, `Part::Cylinder`, `Part::Fuse`, `Part::Cut`, `Part::Common`, `Part::Fillet`. Shapes: `isNull`, `isValid`, `Solids`, `Volume`, `BoundBox`, `copy`, `cut`, `Edges`, `Vertexes`, `CenterOfMass`, `discretize`, `distToShape`. BREP bridge: `Shape.read`, `importBrepFromString`, `exportBrepToString`. Presentation: `makePolygon`, `makeCompound`, `makeWireString`.
- **Native metadata:** `App::DocumentObjectGroup`, `App::FeaturePython`, `App::PropertyString`, `App::PropertyInteger`, `App::PropertyLink`. PMI display also uses `Part::Feature` with stored polylines. This display geometry does not replace semantic STEP entities.
- **FreeCADGui:** `updateGui`, `activeDocument().activeView()`, `setCameraType`, `setCameraOrientation`, `fitAll`, `Selection.clearSelection`, and `ViewObject` visibility, colors, and lines. Use these only on the GUI thread. After loading a file from a headless run, use `touch` and `recompute` on solids. Update the GUI before claiming display verification.
- **PythonOCC, construction:** `STEPControl_Reader/Writer`, `STEPControl_AsIs`, `Interface_Static`, `StepData_StepModel/StepWriter/Protocol`, `TransferBRep.transferbrep`, `BRepTools.breptools`. `ReadStream`, `ReadFile`, `TransferRoots`, `TransferEntity`, `OneShape`, `StepModel`, `IdentLabel`, `ShapeResult`, `ReadFromString`, and `WriteToString` support neutral geometry and actual edge references.
- **PythonOCC, semantic and graphical PMI:** `TDocStd_Document`, `TDataStd_Name`, `TDF_Label/LabelSequence`, `XCAFDoc_DocumentTool/Dimension`, `XCAFDimTolObjects_DimensionObject`, `STEPCAFControl_Writer/Reader/GDTProperty`, `gp_Pnt/Dir/Ax2`, `TopExp_Explorer`, `TopAbs_*`, `TopoDS.topods`, `TColStd_HArray1OfReal`. Selected bindings: `StepGeom`, `StepRepr`, `StepShape`, `StepAP242`, `StepVisual`, `StepBasic`, and `STEPConstruct`. This API inventory does not claim support for all their types.
- **Added UI adapter:** `Sketcher`, `Sketcher::SketchObject`, `Part.LineSegment`, and `Sketcher.Constraint` with `Coincident`, `Horizontal`, `Vertical`, and `Distance`; `renameConstraint`, `FullyConstrained`. Also `Part::Extrusion` with `LengthFwd`; `Spreadsheet::Sheet`, `set`, `setAlias`, `mergeCells`, styles, column widths, and `setExpression`. In the documented Maschinenteil case, [inline-editable-ui-adapter.md](inline-editable-ui-adapter.md) maps six rectangular extrusions to fully constrained sketches. It connects 56 independent dimensions read from STEP to the table. This is an explicitly reconstructed control mapping. It does not claim shared pattern or placement relations, or original user history. Generate expressions from validated names and fixed adapter code. Do not import them as arbitrary executable model text.
- **Added review renderer:** `Part.makeLine`, `Part.makeCircle`, face copy without a mesh `copy(True,False)`, `App::Annotation`, `App::PropertyLinkList`, `App::PropertyLinkSubList`. Before marker creation, verify that geometry fingerprints give unique matches. See [inline-review-markers.md](inline-review-markers.md). This application schema creates separate review objects. It is not a general PMI system or an automatic anchor update system.
- **Do not claim unimplemented dependencies:** `Draft` and `Import`/`ImportGui` are not required or verified foundations of this procedural adapter. An available FreeCAD workbench does not prove a complete constraint, spreadsheet, or standard export return path. The UI extension adds its own verified subset to the base adapter.

Trimmed review faces also use `face.copy(True,False).optimalBoundingBox(False,False)`. Ordinary bounds can remain conservative and depend on parameterization, even after removal of triangulation. Before mutation, the tested profile validates millimeters, target root, namespace, unique IDs, status classes, and finite display geometry. This does not replace a universal JSON Schema validator. Image margins were also adjusted through orthographic camera height with `activeView().getCameraNode().height.getValue()/setValue()`. The Coin node supplied by FreeCAD requires no additional external process for this operation.

### Tools outside CAD execution

PDF reading, rendering, and detail images now use `drawing2cad-mcp`. `pypdf`, Poppler, and Pillow are server dependencies. Agents do not require their own shell or Python preparation code. Examine the MCP image content or returned image artifacts. `functions.exec`/`ALL_TOOLS` are one possible host orchestration interface. They are not skill dependencies. `exec_command`/PowerShell (`rg`, `Get-Content`, `ConvertFrom-Json`, `Get-FileHash`) and `apply_patch` remain tools for software and documentation maintenance and inventories. `view_image` can display local PDF raster images and CAD captures for visual inspection. `open_in_codex` opens files for delivery. It does not validate domain requirements. `load_workspace_dependencies` can locate bundled runtimes on a new host. Other agents can install the documented server dependencies normally.

`collaboration.spawn_agent`, `send_message`, `followup_task`, `list_agents`, `wait_agent`, and `interrupt_agent` coordinate separate tasks and file ownership. They are optional orchestration tools. Model reproduction does not require them. Put CAD decisions and evidence in the resume package. Do not retain them only in agent messages. Web and browser tools are necessary only for targeted primary-source or API research. They must not introduce unverified model sources or execute CAD mutations outside the MCP interface.

## 4. Tested execution without script files

The tested local CAD route remains `freecad_execute_code → FreeCAD-MCP.execute_code → subprocess → FreeCADCmd.exe -c → stdin`. It still requires a healthy GUI RPC bridge. Only the child process is headless. `drawing2cad-mcp` does not remove this upstream dependency. A standalone CAD worker without a running GUI belongs to the future `cad_*` design. Before using `freecad_execute_code_headless`, correct its program path and prove that its upstream implementation creates no script files.

The following pattern is permitted within a complete inline MCP call. Paths, `run_id`, hashes, and payload come from an authorized execution envelope. Do not save this example as a file.

```python
import subprocess as tool3_subprocess
import json as tool3_json

# tool3_payload enthält vertrauenswürdigen Adaptercode plus separat validierte Daten.
# Er importiert FreeCAD selbst, prüft GuiUp == 0 und erzeugt am Ende genau eine
# Zeile CAD_RUN_SUCCESS:<JSON mit run_id, phase, input_hashes, artifacts, metrics>.
tool3_result = tool3_subprocess.run(
    [tool3_freecadcmd_path, '-c'],
    input='exec(' + repr(tool3_payload) + ')\n',
    capture_output=True, text=True, timeout=tool3_timeout_seconds,
    creationflags=tool3_subprocess.CREATE_NO_WINDOW,
    shell=False,
)
tool3_lines = [s[len('CAD_RUN_SUCCESS:'):]
               for s in tool3_result.stdout.splitlines()
               if s.startswith('CAD_RUN_SUCCESS:')]
if tool3_result.returncode != 0 or len(tool3_lines) != 1:
    raise RuntimeError('WORKER_FAILED_OR_MISSING_RESULT')
tool3_report = tool3_json.loads(tool3_lines[0])
# Danach run_id, Eingabehashes, Artefakte und fachliche Gates prüfen.
```

`FreeCADCmd -c` can return exit code 0 after a Python exception. Exit code, exactly one matching result signal, and domain validation are all mandatory. The sentinel must identify the current run. Incidental log text must not trigger success. The separate PythonOCC call uses `[python_path, '-u', '-c', 'import sys; exec(sys.stdin.read())']` with complete code on stdin. It also uses `CREATE_NO_WINDOW`, `shell=False`, output capture, and a timeout.

The current `subprocess.run` pattern is synchronous. For long jobs, set the outer MCP budget above the child budget, including error handling. A GUI timeout does not reliably stop work. Before another write, examine `get_rpc_status`, job status if applicable, and actual outputs. Async execution does not protect document mutations. Dedicated run paths and name prefixes prevent collisions. They do not replace serialization.

## 5. Existing adapter components and verified scope

| Documented entry point | Explicit inputs → outputs | Verified limit |
|---|---|---|
| `sth_p21_parse`, `sth_p21_validate_refs` | P21 text → records and reference validation | Custom limited parser, not EXPRESS certification. Defaults: 32 MiB, 200000 records, 2000000 nodes, depth 128, string 1 MiB. |
| `sth_export_constructive(step_path,contract_path,build_path,out_path)` | PMI/BREP prefix, authorized contract, build report, and intermediate BREPs → new constructive STEP and report | mm; axis-aligned rectangles, complete circles along +Z/+X, refined Boolean operations, and constant-radius fillets with unique edge anchors. |
| `sth_decode_step(step_path)` | STEP only → neutral operation graph, root, units, and references | Exactly one procedural sequence. Explicit preceding operands. No silent loss of disconnected operations. |
| `sth_rebuild_step(step_path,fcstd_path=None,docname=...)` | STEP as the only model source → document, final feature, feature map, evidence report, and decoded operations | Native editable Part operations. Independent comparison with final BREP. No original unknown sketch constraints. |
| `sth_verify_replay(...)` | STEP and report path → measurement and change report | Regression test specific to Maschinenteil. Not a general expected-result validator. Do not transfer values or features to new parts. |
| `read_step_pmi_extended(path,expected_count=None)` | STEP only → `annotations`, `metadata_properties` | Nominal sizes, locations, and angles; thread designation as text; positive general radius specification; geometry references and stored polylines. Rejects tolerance and datum families. |
| `add_step_pmi_to_native(doc,data,source_path,root_name)`, `show_step_pmi_view(...)` | Decoded STEP PMI and native document → semantic and display objects, and view | Existing layer grouping is specific to the case. No automatic PMI reconstruction after changes. |
| `append_adapter_properties(source_path,output_path,properties)` | Existing STEP and declarative metadata → separate candidate and report | Preserves existing entities. For each property: `n+3` standard entities for `n` JSON text chunks. Maximum 4000 ASCII characters per chunk and 2 MiB total. No silent duplicates. |
| `read_adapter_properties(step_path,expected_schemas)` | STEP only and known schema IDs → declarative metadata | Validates unique properties and links, product and context association, schema, chunk order and completeness, and duplicate JSON keys. Geometry and presentation evidence require separate tests. |
| `hist3_make_box`, `hist3_apply_ui`, `hist3_rebuild_editable(step_path,fcstd_path=None,docname=...)` | STEP operation entities and their stored UI property only → native operations, selected rectangular sketches and extrusions, parameter table, and report | Documented Maschinenteil subset: six fully constrained rectangular sketches and 56 independent dimensions. No shared pattern or placement constraints, or general relation reconstruction. |
| `amb3_inject_review(doc,root,metadata)` | `drawing2cad.review-annotations/1` read from STEP and reconstructed solid → separate review groups, outlines, leaders, text, and anchor report | Front, side, and global views specific to the profile and case. Unique face fingerprints and logical feature IDs. Subsequently verify presentation and unchanged product geometry independently. |

Sources: [execution-and-ap242.md](execution-and-ap242.md), [inline-procedural-adapter.md](inline-procedural-adapter.md), [inline-property-pmi-reader.md](inline-property-pmi-reader.md), [inline-review-envelope.md](inline-review-envelope.md), [inline-editable-ui-adapter.md](inline-editable-ui-adapter.md), [inline-review-markers.md](inline-review-markers.md). For the tested subset, the documented change sequence proves `STEP → native operations → changed parameter → new STEP → fresh import`. It does not prove automatic updates to relations, PMI, or review anchors. New UI and review components also require replay and display evidence for the actual final STEP hash. Their presence in the skill does not replace that evidence.

Chunk serialization is a specific compatibility requirement. One large JSON string caused `input buffer overflow` in the observed OCCT 7.8.1 reader. Small numbered `DESCRIPTIVE_REPRESENTATION_ITEM` text chunks prevent this limit from being exceeded. The reader accepts the older single-part `application/json` format. New writers split long text and verify the complete round trip.

**Distinguish the standard from the application schema.** The evaluable operation graph uses standardized STEP operation entities. The additional keys are `drawing2cad.editable_ui.v1` / schema `drawing2cad.editable-ui/1` and `drawing2cad.review_annotations.v1` / schema `drawing2cad.review-annotations/1`. They contain application-specific JSON in `PROPERTY_DEFINITION → PROPERTY_DEFINITION_REPRESENTATION → REPRESENTATION → DESCRIPTIVE_REPRESENTATION_ITEM` containers. These are not standardized constraints or newly invented drawing PMI. They do not prove that another CAD system understands them. A stored UI relation alone does not prove a parametric relation. An adapter must validate and reconnect it, then prove it through a change test.

The optional native tree view in [inline-linear-history-view.md](inline-linear-history-view.md) adds controls from skill 0.3.1. `lin4_apply_history(doc, ordered_ids)` groups the actual original operations. `lin4_expand_history(doc, group)` displays them as a linear list. The tools remain `execute_code`, FreeCAD `App::DocumentObjectGroup`, and PySide/Qt for display. No script modules, new geometry, or additional STEP operation entities are required. For STEP-only reconstruction, the order comes from the decoded operation graph. The UI is specific to FreeCAD. The STEP graph remains platform independent within the tested scope.

## 6. Future CAD service design: common data types

All `cad_*` names and schemas below are **design proposals, not callable tools**. They are not part of the implemented PDF and FreeCAD proxy. A future domain service can expose these endpoints through versioned adapters. This would replace arbitrary Python execution with declarative inputs.

Type conventions: `Id` is a bounded stable string. `Hash` is SHA256 in 64 hexadecimal characters. `Vec3` contains three finite numbers. Reject unknown fields by default. JSON model data must not contain Python, import paths, shell commands, or executable expression strings. Represent permitted formulas as typed ASTs with named operators, dimension validation, and cycle detection.

```typescript
type ArtifactRef = { artifact_id: Id; path: string; sha256: Hash;
  role: 'construction_source'|'verification_only'|'tool_reference'|'output';
  media_type: string; pages?: number[] }; // Seiten 1-basiert
type Envelope = { schema: 'drawing2cad.request/1'; request_id: Id; run_id: Id;
  phase: string; mode: 'new_drawing'|'replay_contract'|'import_step'|'edit_model';
  source_allowlist: ArtifactRef[]; output_root: string; output_paths: string[];
  adapter: {id: Id; version: string; code_sha256: Hash};
  limits: {queue_timeout_s: number; execution_timeout_s: number;
    max_memory_mb: number; max_output_bytes: number};
  required_capabilities: CapabilityRequirement[] };
type CapabilityRequirement = {id: Id; direction: 'read'|'write'|'roundtrip';
  required: boolean; constraints: object};
type Capability = CapabilityRequirement & {status:
  'verified'|'untested'|'unsupported'|'failed'; supported_profile: object;
  evidence: ArtifactRef[]; toolchain_sha256: Hash};
type Job = {job_id: Id; request_id: Id; state:
  'queued'|'running'|'succeeded'|'failed'|'timed_out'|'cancelled'|'lost';
  phase: string; checkpoint: string|null; result_ref?: ArtifactRef;
  started_at?: string; finished_at?: string};
type Error = {code: string; message: string; pointer?: string;
  operation_id?: Id; evidence?: ArtifactRef[]; retryable: boolean};
type Result<T> = {schema: 'drawing2cad.result/1'; request_id: Id; run_id: Id;
  status: 'succeeded'|'failed'|'partial'; phase: string;
  source_inputs: ArtifactRef[]; artifacts: ArtifactRef[];
  metrics: object; warnings: Error[]; errors: Error[];
  checkpoint: string|null; claims: {[claim:string]:
    'passed'|'failed'|'not_tested'|'unsupported'}; data: T};
```

`object` fields are design abbreviations here. They do not permit arbitrary unvalidated data. Before implementation, write a closed JSON Schema with limits for each capability, metric, and policy type. The model contract, register, and validation policy refer to their own versioned schemas. A result can report `succeeded` for a technically complete partial operation. A master file claim requires the applicable `claims` and all requested acceptance criteria.

### Path and hash boundaries, and sources

Resolve each path canonically on the server. Validate directory boundaries after symlink, junction, and UNC resolution. Apply Windows case rules. Resolve relative paths only against an explicit root. Read only the exact authorized inputs. Write only to explicit output paths under `output_root`. Do not treat paths from text notes, STEP properties, or model IDs as file paths. After hash verification, send the same input bytes to the worker without modification. This prevents a change between verification and reading. Tool code and fonts use separate authorized tool references. Their geometry does not become a construction source.

During STEP-only reconstruction, the worker must receive model content exclusively from STEP. Drawing, source contract, and FCStd inputs are prohibited in that worker. Read independent expectations only in the subsequent comparison. An operating system process alone does not isolate file access. The new server must enforce the allowlist and a suitable worker sandbox. It must also record the inputs actually read.

### Request identity, jobs, and replay

Use `request_id = SHA256(canonical_request)` with specified canonicalization, for example RFC-8785/JCS with rejection of non-finite numbers. Identity includes tool name, input bytes and hashes, adapter and toolchain hashes, configuration, units, validation policy, and output destinations. Exclude transient timestamps, `run_id`, and transport fields. `run_id` identifies an actual attempt. The server calculates and verifies the identity itself.

An identical request with identical content returns the existing job or result, after verification of artifact hashes again. The same ID with different content produces `IDEMPOTENCY_CONFLICT`. Do not retry silently after a client timeout. For an intentional fresh reproduction, use `replay_nonce` as a semantic request field. A new `run_id` alone is not sufficient. Keep a job journal. Preserve status and results across restart. Mark jobs with an unknown final state as `lost`.

Start workers without GUI dependencies. Apply finite queue and execution budgets, process group or Windows Job Object termination, memory and output limits, and stdout/stderr capture. These are planned server capabilities. The current inline fallback does not provide all these guarantees. First write candidates to a destination specific to the run. Complete hash calculation and validation. Then register them atomically. Replace the last valid master file only through an explicitly requested publish operation with satisfied acceptance criteria. Cancellation must not automatically promote a candidate to master file.

## 7. Proposed granular tools

All mutations return `Job` first. The final `Result<T>` is available through status and result tools. Small read-only tests can return `Result<T>` synchronously. `E` means `Envelope`. `Ref` means `ArtifactRef`.

| Proposed name | Input schema in addition to `E` | Result schema `data` and primary condition |
|---|---|---|
| `cad_get_capabilities` | `{required:CapabilityRequirement[],refresh:boolean}`; read-only test, no model required | `{toolchain:object,capabilities:Capability[],gaps:Error[]}`; separate directions, versions, individual operations, units, PMI, markers, and renderers. |
| `cad_observe_source` | `{sources:Ref[],pages:number[],regions?:{page:number,bbox:[number,number,number,number],unit:'pdf_point'}[],render:{dpi:number},observations?:Ref}` | `{renders:Ref[],observations:Ref,unresolved:Id[]}`; distinguish rendering and extraction from agent interpretation, with provenance. Observations are not yet an authorized model contract. |
| `cad_validate_contract` | `{contract:Ref,policy:Ref,freeze:boolean}` | `{valid:boolean,contract_sha256:Hash,canonical_model_sha256:Hash,requirements:CapabilityRequirement[],issues:Error[]}`; schema, DAG, units, references, unresolved values, sources, PMI, and markers. A freeze creates a new immutable revision. |
| `cad_build_native` | `{contract:Ref,validation:Ref,native_path:string,intermediate_root:string}` | `{native:Ref,build_report:Ref,root_id:Id,feature_map:Ref}`; fresh worker. Validate the complete DAG, native operations, and intermediate geometry. |
| `cad_export_ap242` | `{contract:Ref,build:Ref,profile:Id,step_path:string,include:{construction:boolean,pmi:boolean,review:boolean}}` | `{candidate:Ref,export_report:Ref,representation_map:Ref}`; validate constructive entities, final BREP, semantics, and presentation separately. Do not claim editability from a standard BREP export. |
| `cad_rebuild_step` | `{step:Ref,native_path:string,profile:Id}` | `{native:Ref,decoded_contract:Ref,rebuild_report:Ref,feature_map:Ref}`; STEP is the only model source. Do not use the original contract as a hidden supplement. |
| `cad_edit_native` | `{base:Ref,base_sha256:Hash,changes:{feature_id:Id,parameter:Id,value:object}[],native_path:string}` | `{native:Ref,revision:Ref,change_report:Ref,invalidated_pmi:Id[],invalidated_markers:Id[]}`; typed parameters, supported edit direction, effects, and stale data. Return export remains a separate tool. |
| `cad_read_pmi` | `{step:Ref,profile:Id}` | `{pmi:Ref,semantics_report:Ref,presentation_report:Ref,unsupported_types:string[]}`; read stored semantics, targets, units, derivation, and polylines. |
| `cad_write_pmi` | `{base:Ref,pmi:Ref,profile:Id,output_step:string}` | `{candidate:Ref,pmi_report:Ref}`; declarative PMI with specific geometry anchors. Keep original specifications and review data separate. |
| `cad_read_review` | `{step:Ref,schemas:string[]}` | `{ui:Ref\|null,register:Ref\|null,markers:Ref\|null,report:Ref}`; read known application schemas. Report missing or invalid extensions. |
| `cad_write_review` | `{base:Ref,register:Ref,markers:Ref,ui?:Ref,output_step:string}` | `{candidate:Ref,review_report:Ref}`; standard containers with an application schema. Validate targets. Do not invent positions for unresolved anchors. |
| `cad_validate_model` | `{subject:Ref,expected?:Ref,policy:Ref,checks:('geometry'\|'construction'\|'relations'\|'pmi'\|'review'\|'replay'\|'edit_roundtrip')[]}` | `{validation_report:Ref,claims:object,missing_evidence:Error[]}`; actually execute the required independent worker runs. Evaluate each test group separately. |
| `cad_capture_review` | `{subject:Ref,views:{id:Id,orientation:object,visible_groups:Id[],width:number,height:number}[],renderer:Id}` | `{images:Ref[],capture_report:Ref}`; render actual geometry, PMI, and markers. Evaluate renderer capability separately. Reject unknown groups and invisible mandatory markers. |
| `cad_artifact_manifest` | `{artifacts:Ref[],reports:Ref[],contract?:Ref,previous_master?:Ref,publish:boolean}` | `{manifest:Ref,resume:Ref,current_master:Ref\|null}`; validate hashes and acceptance criteria. Manifest creation without publishing is permitted. `publish:true` replaces the master file only when requirements are satisfied. |
| `cad_job_status` | `{job_id:Id}` without a model envelope | `{job:Job}`; read-only, persistent, no GUI dependency. |
| `cad_job_result` | `{job_id:Id}` without a model envelope | `Result<T>` or structured `JOB_NOT_FINISHED`. No silent retries. |
| `cad_cancel_job` | `{job_id:Id,reason:string}` without a model envelope | `{job:Job,cancel_requested:boolean}`; cancel only the caller's own job. Quarantine partial outputs. |

The future implementation must replace generic `value`, `orientation`, and `claims` objects with closed union schemas. The editable UI contract identifies stable feature and parameter IDs and permitted values. Display labels are not API IDs. If PMI or review anchors cannot be renewed, a change returns a candidate for review and `STALE_PMI`/`STALE_REVIEW`. It does not return a fully validated master file.

## 8. Error contract

Each error contains a stable code, readable finding, evidence, and retry status. Include a JSON Pointer or feature ID when known. Partial reports remain readable. Do not classify `unsupported` or `not_tested` as success.

| Codes | Meaning and action |
|---|---|
| `SOURCE_NOT_ALLOWED`, `PATH_OUTSIDE_ALLOWLIST`, `SOURCE_HASH_MISMATCH`, `INPUT_CHANGED` | Source, path, or bytes are not authorized. Stop before mutation. |
| `SCHEMA_INVALID`, `UNRESOLVED_VALUE`, `DAG_CYCLE`, `DUPLICATE_ID`, `RELATION_UNSUPPORTED`, `UNIT_UNSUPPORTED` | Contract or relation error. Supply a specific finding. |
| `CAPABILITY_UNVERIFIED`, `UNSUPPORTED_OPERATION`, `UNSUPPORTED_PMI`, `MISSING_MARKER_TRANSPORT`, `ADAPTER_VERSION_MISMATCH` | A required capability is missing. Do not report success through a substitute BREP. |
| `AMBIGUOUS_ANCHOR`, `ANCHOR_NOT_FOUND`, `INVALID_SHAPE`, `RECOMPUTE_FAILED`, `GEOMETRY_MISMATCH`, `GRAPH_MISMATCH` | Construction, topology, or geometry validation failed. |
| `STALE_PMI`, `STALE_REVIEW`, `PRESENTATION_MISSING`, `REVIEW_MARKER_INVISIBLE` | A domain specification, reference, or visible presentation lacks evidence. |
| `STEP_PARSE_ERROR`, `STEP_REFERENCE_MISSING`, `STEP_PROFILE_UNSUPPORTED`, `PROPERTY_SCHEMA_UNKNOWN`, `LIMIT_EXCEEDED` | Parser, schema, or resource limit. Do not silently omit data. |
| `WORKER_NOT_FOUND`, `WORKER_CRASHED`, `WORKER_TIMEOUT`, `GUI_UNAVAILABLE`, `RESULT_SENTINEL_MISSING`, `OUTPUT_HASH_MISMATCH` | Execution error. Examine status and process termination. Do not publish partial outputs. |
| `IDEMPOTENCY_CONFLICT`, `JOB_NOT_FOUND`, `JOB_NOT_FINISHED`, `JOB_LOST`, `OUTPUT_CONFLICT`, `VALIDATION_GATE_FAILED` | Lifecycle or publication requirements are not satisfied. Preserve the existing master file. |

## 9. Implementation sequence and required tests

1. **Version the existing components.** Group inline components by function. Record immutable code and toolchain hashes, license and installation dependencies, supported profiles, and historical evidence. Do not use case-specific constants as general defaults. Do not claim new interoperability at this stage.
2. **Complete the data contract.** Write JSON Schemas for request, result, model, relations, sources, UI, register, markers, policy, and capture. Specify limits, hash canonicalization, stable IDs, and error codes. Implement pure validators first.
3. **Implement the worker.** Implement an MCP worker that is independent of the GUI. Include a job journal, file access boundary, stdin protocol, limits, cancellation, and atomic artifact registration. The existing GUI display can remain an optional separate service. Do not execute model code from JSON.
4. **Encapsulate limited adapters.** Start with the tested primitive, Boolean, and constant-radius fillet family, plus STEP-only reconstruction. Enable API directions separately. Then add nominal PMI, presentation, and named review and UI extensions. Advertise relation transfer and automatic anchor updates only after their own tests pass.
5. **Add independent validation.** Include a final BREP reader, P21 structure and target validation, and two fresh repeats. Also include edit and return export tests, and actual views. The validator must not supply missing source data to the STEP-only builder.
6. **Deliver the domain CAD service.** Supply granular tools, machine-readable capabilities, examples without case-specific values, and a complete handoff. Treat each additional CAD system as a new adapter with its own evidence. This future `cad_*` service is not the implemented `drawing2cad-mcp` proxy.

| Test group | Minimum cases and success criteria |
|---|---|
| Tool and host acceptance | Missing programs, different ABI or version, and inactive GUI. The worker remains fully headless. Supported profiles and errors are correct. Do not advertise a defective headless path as available. |
| No script files | Observe the filesystem from worker start to completion. No `.py`, macro, or shell files. Only declared artifacts. Stdin contains complete code. |
| Execution | Exception with exit code 0; missing, incorrect, or duplicate sentinel; kernel crash; timeout; queue overflow; oversized stdout. No false success. Bounded logs. Child process terminates. |
| Access | Path traversal, junctions, symlinks, UNC, case rules, and input replacement after hash verification. Also unauthorized files under an allowed root and paths in JSON text. Reject without access or master file changes. |
| Idempotency and jobs | Retry during an active job, same ID with different content, server restart, client cancellation, lost job, and concurrent writes. At most one publication. Recoverable status. |
| Contract | Missing or duplicate IDs, cycles, NaN/Inf, unit conflicts, unresolved required values, unauthorized sources, and unsupported relations or operations. Precise error before construction. |
| Native construction | Test each permitted primitive, orientation, Boolean operation, and constant-radius fillet separately. Include limit radii, missing or ambiguous edges, and disconnected operations. Correct native types and parameters. Reject invalid inputs. |
| STEP-only | The worker receives only STEP. Preserve DAG, operands, units, and parameters. One product root, expected valid solid, independent BREP comparison under a fixed tolerance. Do not replace missing graph data with a final solid. |
| Reproducibility | Two fresh contract builds and two fresh STEP-only imports. Compare semantic graph, parameter, PMI, and marker values, and geometry. Identical STEP bytes are not required. |
| Edit and return export | Change a supported parameter and fillet. Export again and do another fresh import. Prove the intended change and dependent effects. Test relations separately. Equal nominal values are not sufficient. |
| PMI | Validate value, unit, source, geometry target, derivation, and presentation. Include degrees and radians, missing callout, duplicate, incorrect association, unsupported datum or tolerance, and text falsely treated as diameter. |
| Review and UI | Duplicate property, unknown schema, >2-MiB payload, duplicate JSON keys, and missing, reordered, or incorrectly numbered chunks. Incorrect product or unit context, code-like text, invalid feature anchor, unresolved position. Original PMI remains unchanged. Restore visible markers from STEP. Validate them again after changes. |
| UI parameters and sketches | Complete native constraint validation for supported rectangular profiles. Equal values in STEP and table. Alias and target validation. Change a table cell, validate geometry, and restore. Do not describe independent rows as shared parameter relations. |
| Display | Actual screenshots of all required layers. Solid visible, text readable, original PMI and review separate. Reproduce stored polylines identically with a missing or different font. |
| Publication | Missing acceptance criterion, changed artifact hash, cancellation during writing. Preserve the old master file. Identify the candidate clearly. Manifest and resume package cover all actual outputs and unresolved claims. |
| External adapter | Separate positive and negative import, export, edit, PMI, and marker tests. Recognition of standard containers alone does not prove semantic or parametric support. |

This future domain CAD service would combine source and contract validation, isolated execution, and the verified operation adapter. It would also include STEP-only reconstruction, independent validation, and persistent artifact and job records. The existing PDF and FreeCAD proxy does not automatically do these tasks. Missing automatic relation and PMI processing remain explicit capability gaps until their tests pass.
