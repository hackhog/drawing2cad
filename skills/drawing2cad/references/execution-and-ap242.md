# MCP execution and AP242 representation

## Process control without script files

1. Examine `get_rpc_status` and the available FreeCAD MCP tools. If the dispatcher is unhealthy, do not add GUI tasks to its queue.
2. Prefer `execute_code_headless` if it is available and functional. Before use, confirm that its implementation satisfies the prohibition on script files. The tested local fallback uses `execute_code` to start a separate `FreeCADCmd` process with inline code on stdin. This fallback still requires the GUI RPC bridge. Only the child process is headless. Prove `FreeCAD.GuiUp == 0` in that process.
3. Find executable programs in the installed FreeCAD environment. Do not guess an unrelated Python interpreter. PythonOCC and FreeCAD can require different interpreter or ABI contexts. Separate child processes worked in the reference run.
4. On Windows, start child processes without a visible window or shell. Use argument lists, stdin, output capture, and finite timeouts. Do not create `.py`, `.FCMacro`, `.ps1`, `.bat`, or similar executable files.
5. Each inline execution must import its dependencies and receive all inputs explicitly. A success sentinel or structured result is mandatory. `FreeCADCmd -c` can return exit code 0 after a Python exception.
6. Change GUI or document state only on the GUI thread through `execute_code`. For explicitly suitable asynchronous work, use `commit()`. Do not write concurrently to the same document or MCP namespace.

The example below executes in memory. It is documentation, not a script file:

```python
# Innerhalb des FreeCAD-MCP; cad_payload ist ein vollständiger Inline-Text.
result = subprocess.run(
    [freecadcmd_path, "-c"],
    input="exec(" + repr(cad_payload) + ")\n",
    capture_output=True, text=True, timeout=60,
    creationflags=0x08000000,  # Windows: kein sichtbares Konsolenfenster
)
assert result.returncode == 0
assert "CAD_RUN_SUCCESS:" in result.stdout
```

For the separate PythonOCC process, use `python -u -c "import sys; exec(sys.stdin.read())"` with the complete payload on stdin. Do not put long code in the Windows command line. Limit logs. Retain errors and the structured result. After a timeout, determine status or process termination first. Do not repeat writes without control.

## Tested toolchain

Reference results: FreeCAD 1.1.4, OCCT 7.8.1, Python 3.11.14, PythonOCC 7.8.1.1, and MCP addon 0.1.27. These versions were tested. The result does not cover other versions. If the toolchain changes, do small capability tests and record new evidence.

## Construction tree in STEP

In the tested OCC binding, `RWBooleanResult` reads and writes only `SolidModel` operands. `RWCsgSolid` accepts only `BooleanResult` as its root. Direct `CsgPrimitive` roots or unwrapped Boolean operands produced null references. The following structure uses standard entities. It was written and read back:

```text
CSG_SHAPE_REPRESENTATION
  CSG_SOLID
    BOOLEAN_RESULT
      EXTRUDED_FACE_SOLID
      CSG_SOLID oder EXTRUDED_FACE_SOLID
```

- Represent cylinders as extrusions of a circular `FACE_SURFACE`. Represent boxes as extrusions of rectangular profiles. These construction elements can be evaluated. They retain profile parameters and depth.
- Circular profile: `FACE_OUTER_BOUND → EDGE_LOOP → ORIENTED_EDGE → EDGE_CURVE → CIRCLE`. A closed circle uses the same start and end vertex. The circle and planar face use the same axis placement.
- Polygon profile: `FACE_OUTER_BOUND → POLY_LOOP`. Use points in representation coordinates, an associated `PLANE`, and an unambiguous traversal direction. During import, do not apply the plane placement again to points that already use global coordinates.
- Put each `BOOLEAN_RESULT` in a `CSG_SOLID`. Set both operands through `BooleanOperand.SetSolidModel()`. `CsgSelect.SetBooleanResult()` sets the applicable selection type.
- In the Befestigung case, represent a half-cylinder as the intersection of a full cylinder and a box. These additional operations are explicit. Do not describe them as original user actions.
- Connect the CSG tree to the BREP representation through `SHAPE_REPRESENTATION_RELATIONSHIP`. Use the same product and unit context. Export all references.

The adapter reads the CSG representation and resolves wrappers. It preserves shared DAG nodes and operand order. Then it reconstructs native primitive, extrusion, and Boolean objects. A single native `Part::Feature` with an assigned final shape does not satisfy editability requirements.

## Semantic PMI export

The tested method uses an XCAF document, shape and subshape labels, and `XCAFDoc_Dimension` with `XCAFDimTolObjects_DimensionObject`. `STEPCAFControl_Writer` uses dimension tolerance and name modes. If necessary, resolve the XCAF reference at the shape root first. Otherwise, subshape labels can be empty.

- `TDocStd_Document('BinXCAF')` and `TDataStd_Name.Set(label, 'name')` accepted ordinary Python strings in the tested binding. Incorrect string wrappers can cause native crashes.
- Initialize the writer once. Set `write.step.schema` to `AP242DIS` and set the length unit. Then create the writer again. Examine the schema header in the written file. A configured option alone does not prove AP242 output.
- Store a unique `source_id` as a description on each dimension. Description entries in the tested binding are 0-based.
- For `Location_Angular`, the tested writer required radians. The XCAF reader returned degrees. Examine the actual STEP unit separately. Do not convert twice.
- `Location_Oriented` with `SetDirection` caused a native crash in the tested reader. Do tests in isolated processes. Select only alternatives with test evidence.
- For derived angular dimensions, create lines between axis centers as `CONSTRUCTIVE_GEOMETRY_REPRESENTATION`. Connect `DERIVED_SHAPE_ASPECT`, `SHAPE_ASPECT_DERIVING_RELATIONSHIP`, and `GEOMETRIC_ITEM_SPECIFIC_USAGE` to the actual source faces. Do not attach an angle value to arbitrary faces.
- XCAF reader 7.8.1 shortened the provenance chain of the angle lines. Examine the derivation graph directly in the STEP entities. Also do the value round-trip test.

## Graphical PMI and FreeCAD display

Set `SetPresentation(shape, name)`, `SetPlane(gp_Ax2(...))`, and `SetPointTextAttach(gp_Pnt(...))` on the semantic dimension. Before export, convert text and dimension lines to polylines with a specified deflection. Direct B-spline control points do not give a reliable text image.

For each PMI item, examine `TESSELLATED_ANNOTATION_OCCURRENCE`, `DRAUGHTING_CALLOUT`, `ANNOTATION_PLANE`, and `DRAUGHTING_MODEL_ITEM_ASSOCIATION`. Make sure that the corresponding semantic item is correct. Counts alone are not sufficient.

For FreeCAD, the import adapter can reconstruct STEP polylines as visible geometry. It can also reconstruct semantic records with STEP source references. Native display objects do not prove that the standard FreeCAD export preserves semantic PMI. Provide view groups and sufficient contrast. After geometry changes, explicitly mark PMI as unverified. Validate its values, references, and presentation again before removal of that status.

For stable geometry anchors, do not use presentation tessellation. Determine edge bounds from a copy without a mesh. For trimmed faces, use `face.copy(True, False).optimalBoundingBox(False, False)`. Even an ordinary `BoundBox` without a mesh can return different conservative bounds for toroidal faces, depending on parameterization. In the Maschinenteil review, the optimal box removed this difference without a tolerance increase. Unique face and edge matches and the other geometric signatures remain mandatory.

Camera commands can animate. Before a visual inspection, examine the actual camera orientation. Then capture the image. An immediate screenshot after `viewTop()` or `setCameraOrientation()` can show an intermediate angle. Display different PMI and review layers separately.

## Technical primary sources

If APIs or versions change, examine the applicable sources below. They are not additional construction sources.

- [AP242 CSG shape representation](https://www.steptools.com/docs/stp_aim/html/t_csg_shape_representation.html)
- [CSG solid](https://steptools.com/docs/stp_aim/html/t_csg_solid.html)
- [Boolean result](https://steptools.com/docs/stp_aim/html/t_boolean_result.html)
- [Extruded face solid](https://steptools.com/docs/stp_aim/html/t_extruded_face_solid.html)
- [OCCT STEP translator](https://dev.opencascade.org/doc/overview/html/occt_user_guides__step.html)
- [FreeCAD AP242 support tracking](https://github.com/FreeCAD/FreeCAD/issues/19795)
- [FreeCAD GDT import discussion](https://github.com/FreeCAD/FreeCAD/issues/29796)
