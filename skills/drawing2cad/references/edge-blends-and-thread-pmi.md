# Constant-radius fillets and thread designations

This extension applies to models with actual fillet operations. It also applies to a thread designation without fully specified thread geometry. The basic requirements in `validation.md` still apply. Use the applicable model contract. Do not transfer dimensions from the Maschinenteil reference case to other drawings.

## Fillets in the constructive STEP graph

AP242 describes the operation with `SOLID_WITH_CONSTANT_RADIUS_EDGE_BLEND(name, rationale, base_solid, blended_edges, radius)`. `blended_edges` contains unique `EDGE_CURVE` references. Preserve the constructive base. An intermediate BREP solid alone does not replace it.

The installed OCCT 7.8.1 bindings do not expose this entity as a typed class. The standard-conforming record can still occur in the Part 21 graph. A custom parser must read the record and all Boolean operations that depend on it. Never treat unknown operands as empty shapes or completed final solids. Add standard entities that the binding cannot process only after ordinary OCCT serialization. This sequence prevents the writer from discarding references.

`PROCEDURAL_SHAPE_REPRESENTATION_SEQUENCE` in a `PROCEDURAL_SHAPE_REPRESENTATION` describes the construction sequence. `EXPLICIT_PROCEDURAL_SHAPE_REPRESENTATION_RELATIONSHIP` connects it to the evaluated final BREP. A fillet must not occur directly as an item of a `CSG_SHAPE_REPRESENTATION`. Its permitted item types are more restrictive.

For edge selection, export the actual base shape immediately before each fillet as an auxiliary BREP. Use the transfer finder to identify `EDGE_CURVE` entities for the selected TopoDS edges. Add only the auxiliary BREP and its dependencies to the final STEP model. Do not add another product solid. `EXPLICIT_PROCEDURAL_GEOMETRIC_REPRESENTATION_ITEM_RELATIONSHIP` connects the preceding construction sequence to this topology.

During import, identify the stored edges geometrically on the reconstructed base. Combine properties such as curve type, length, endpoints, and distance from the stored curve. Each association must be unique. Missing or ambiguous matches are errors. Entity IDs and FreeCAD edge numbers are not stable geometric identities. Cylinder seams can divide one geometric arc into multiple topological edges. Do not conceal these changes through silent removal of edges.

The ordinary STEP geometry import must still return exactly the expected final solid. Parser success alone proves neither this result nor correct reconstruction. Fresh import runs, geometric difference tests, and a parameter change test are mandatory. Report a complete EXPRESS conformity test separately.

Primary sources: [Constant-radius edge blend](https://www.steptools.com/docs/stp_aim/html/t_solid_with_constant_radius_edge_blend.html), [procedural sequence](https://www.steptools.com/docs/stp_aim/html/t_procedural_shape_representation_sequence.html), [explicit result relationship](https://www.steptools.com/docs/stp_aim/html/t_explicit_procedural_shape_representation_relationship.html).

## M10 as a semantic designation

[metric-thread-chamfers.md](metric-thread-chamfers.md) contains the complete table from the user link, with 35 sizes from M1 to M68. It also contains short notes about typical chamfers. Determine exact chamfer widths separately.

If only `M10` is specified and a simplified representation is agreed, create a nominal cylinder. Add a semantic text property linked to its geometry. A suitable standard chain is `SHAPE_ASPECT` → `PROPERTY_DEFINITION` → `PROPERTY_DEFINITION_REPRESENTATION` → `DESCRIPTIVE_REPRESENTATION_ITEM`. The graphical label must refer to the same property.

This designation is not a fully parameterized `THREAD` feature entity. Do not derive additional values from the simplified cylinder. First resolve a standardized thread designation before classifying a value as missing. For a metric ISO coarse thread, `M10` specifies the coarse pitch of 1.5 mm. This pitch is derived from the designation and the applicable standard. It is neither a separately drawn dimension nor an invented assumption. The official FreeCAD table includes `M10x1.5` in the `ISO metric regular` series. ISO 965-1 describes omission of the coarse pitch from the designation. In the model contract, retain the original text `M10`, resolved values, and applicable standard with its edition separately. If the standard association is unclear, mark this interpretation. Do not replace `M10` with a numeric Ø10 dimension that appears to come directly from the drawing.

An omitted tolerance class is not automatically a blocking uncertainty. First examine standard requirements and application context. Distinguish an idealized nominal profile for visualization from geometry with selected manufacturing limit dimensions. Specify tolerance position, actual thread length, runout, relief, and end chamfer only when evidence supports them. Evidence must come from the drawing, an explicitly applied standard, or a confirmed assumption. A nominal profile with PMI does not prove a specific manufactured fit. For current standard interpretation, examine the applicable edition. ISO 965-1:2026 replaced the 2013 edition. A historical designation reference alone does not validate a complete design to the 2026 edition.

In the Maschinenteil reference case, the user-confirmed representation remains an envelope cylinder with M10 PMI. The new option for detailed geometry does not automatically cancel that decision. The undimensioned end chamfer remains marked as uncertain. Do not generate it from the thread designation.

Retain confirmed assumptions as assumptions in the master file. Count and validate them separately from original drawing dimensions. General drawing notes require semantic properties with their actual scope. For example, this applies to the note “nicht bemaßte Radien R=1” (undimensioned radii R=1). Do not infer a fillet on every edge from that note.

## Actual thread geometry and an editable thread operation

Report three capabilities separately:

1. **Geometry:** FreeCAD can create an actual screw thread with a profile along a helix. It can use a parametric helix operation. Alternatively, it can use a helix, profile, sweep, and Boolean operation. In principle, the resulting faces and edges can be transferred as BREP in STEP AP242. This produces a visible helical thread. A sequence of rings or a labeled cylinder is not equivalent geometry. This general capability is documented. A successful export and fresh import of the specific geometry still require evidence.
2. **Semantics:** The STEP `THREAD` feature defines thread meaning with associated parameters. These include outside diameter, form, direction, internal or external thread, and fit class. Apply the rules for `SHAPE_REPRESENTATION_WITH_PARAMETERS`, associated faces, and the actual AP242 edition. A `THREAD` entity alone creates neither helical faces nor a native CAD operation. Do not describe the existing M10 text property as an implemented `THREAD` feature.
3. **Parametric reconstruction:** An ordinary STEP BREP import restores the thread surface. An editable thread operation requires an adapter. That adapter must translate the complete definition into native profile, helix, sweep, or thread features and preserve their dependencies. The current skill adapter supports rectangular and circular extrusions, Boolean operations, and constant-radius edge fillets. Helix, sweep, and `THREAD` reconstruction are not yet implemented or tested.

An adapter extension must encode the profile definition, unit, axis, placement, pitch or lead, and number of starts reproducibly. It must also encode direction, axial extent, and selected start and end treatment. Connect thread meaning and the actual evaluated operations to the same final BREP. Reject unknown thread operations as unsupported. Do not replace them with a final solid and still claim editability. Test fresh STEP-only reconstruction, solid validity, geometry equivalence, and pitch and length changes. Include recomputation, restoration, saving, and reopening in these tests. If geometry changes, validate PMI and review anchors again.

Primary sources:

- [FreeCAD: actual threads with a helix and profile](https://github.com/FreeCAD/FreeCAD-documentation/blob/main/wiki/Thread_for_Screw_Tutorial.md)
- [FreeCAD: parametric Additive Helix](https://github.com/FreeCAD/FreeCAD-documentation/blob/main/wiki/PartDesign_AdditiveHelix.md)
- [FreeCAD source: ISO coarse thread table, M10x1.5](https://github.com/FreeCAD/FreeCAD/blob/main/src/Mod/PartDesign/App/FeatureHole.cpp)
- [ISO 261:1998: general plan for ISO metric threads](https://www.iso.org/standard/4165.html)
- [ISO 965-1:2013, designation in Section 12.2; historical primary source](https://www.finesz.com/pic/ISO965-1.pdf)
- [ISO 965-1:2026: current edition and replacement of the 2013 edition](https://www.iso.org/standard/87889.html)
- [OCCT: STEP translator, BREP geometry, and AP242 output schema](https://occt3d.com/dev/doc/overview/html/occt_user_guides__step.html)
- [STEP THREAD feature and associated parameter rules](https://www.steptools.com/docs/stp_aim/html/t_thread.html)
