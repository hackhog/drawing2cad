"""Nominal AP242 semantic dimensions for uniquely selected analytic faces.

Invoke CAD functions only in a restricted worker. This profile does not support
geometric tolerances, datum systems, threads, or arbitrary PMI imports.
"""
from __future__ import annotations

import math
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, model_validator
from ..part_schema import ClosedModel, Identifier, Scalar, Vector3, ValueRef, parse_description, resolve

PMI_SCHEMA_VERSION = "drawing2cad.pmi/1"
Axis = Literal["X", "Y", "Z"]


class FaceTarget(ClosedModel):
    surface: Literal["plane", "cylinder"]
    axis: Axis
    origin: Vector3
    radius: Scalar | None = None

    @model_validator(mode="after")
    def surface_fields(self):
        if (self.surface == "cylinder") != (self.radius is not None):
            raise ValueError("A cylinder requires radius. A plane must not have radius.")
        return self


class Annotation(ClosedModel):
    origin: Vector3
    normal: Axis
    x_axis: Axis
    text_height: Annotated[float, Field(gt=0, le=100, allow_inf_nan=False)] = 2.5

    @model_validator(mode="after")
    def perpendicular_axes(self):
        if self.normal == self.x_axis:
            raise ValueError("Annotation axes must be perpendicular.")
        return self


class SemanticDimension(ClosedModel):
    id: Identifier
    kind: Literal["diameter", "linear"]
    feature_id: Identifier
    evidence_ids: Annotated[list[Identifier], Field(min_length=1, max_length=100)]
    value: Scalar
    targets: Annotated[list[FaceTarget], Field(min_length=1, max_length=2)]
    annotation: Annotation
    uncertainty_acknowledged: bool = False

    @model_validator(mode="after")
    def target_types(self):
        if self.kind == "diameter":
            if len(self.targets) != 1 or self.targets[0].surface != "cylinder":
                raise ValueError("A diameter requires one cylinder target.")
        elif len(self.targets) != 2 or any(t.surface != "plane" for t in self.targets) or self.targets[0].axis != self.targets[1].axis:
            raise ValueError("A linear dimension requires two parallel plane targets.")
        return self


class PmiSpecification(ClosedModel):
    schema_version: Literal[PMI_SCHEMA_VERSION] = PMI_SCHEMA_VERSION
    dimensions: Annotated[list[SemanticDimension], Field(max_length=128)]

    @model_validator(mode="after")
    def unique_ids(self):
        ids = [d.id for d in self.dimensions]
        if len(set(ids)) != len(ids):
            raise ValueError("PMI dimension identifiers must be unique.")
        return self


def pmi_schema():
    """Return the closed nominal PMI contract without loading a CAD library."""
    result = PmiSpecification.model_json_schema()
    result["x-scope"] = {
        "units": "mm", "kinds": ["diameter", "linear"],
        "association": "unique analytic face selection; no persistent face indices",
        "selector_origin": "Plane: normal offset; cylinder: axis line. In-plane and axial coordinates do not disambiguate separate faces.",
        "unsupported": ["GD&T", "datums", "thread semantics", "arbitrary PMI import"],
        "target_cad_opening": "not_tested", "full_express_validation": "not_tested",
    }
    return result


def parse_pmi(value):
    return value if isinstance(value, PmiSpecification) else PmiSpecification.model_validate(value)


def validate_pmi(value, description):
    """Validate feature, evidence, parameter, and uncertainty references."""
    spec = parse_pmi(value)
    part = parse_description(description) if isinstance(description, dict) else description
    features = {f.id: f for f in part.features}
    evidence = {e.id: e for e in part.evidence}
    parameters = {p.name: p for p in part.parameters}
    for dim in spec.dimensions:
        if dim.feature_id not in features:
            raise ValueError(f"Unknown PMI feature: {dim.feature_id}")
        if any(eid not in evidence or eid not in features[dim.feature_id].evidence_ids for eid in dim.evidence_ids):
            raise ValueError(f"PMI evidence must belong to its feature: {dim.id}")
        if any(evidence[eid].status == "unresolved" or evidence[eid].review_status == "rejected" for eid in dim.evidence_ids):
            raise ValueError(f"Unresolved or rejected PMI evidence: {dim.id}")
        uncertain = any(evidence[eid].status in {"assumed", "inferred"} for eid in dim.evidence_ids)
        if uncertain and not dim.uncertainty_acknowledged:
            raise ValueError(f"PMI uncertainty needs explicit acknowledgement: {dim.id}")
        scalars = [dim.value, *dim.annotation.origin]
        for target in dim.targets:
            scalars.extend(target.origin)
            if target.radius is not None:
                scalars.append(target.radius)
        for scalar in scalars:
            if isinstance(scalar, ValueRef):
                if scalar.parameter not in parameters or parameters[scalar.parameter].unit != "mm":
                    raise ValueError("PMI parameters must exist and use mm.")
            if not math.isfinite(resolve(scalar, part)):
                raise ValueError("PMI values must be finite.")
        if resolve(dim.value, part) <= 0:
            raise ValueError("PMI dimensions must be greater than zero.")
        if any(t.radius is not None and resolve(t.radius, part) <= 0 for t in dim.targets):
            raise ValueError("PMI cylinder radii must be greater than zero.")
    return spec, part


def _axis(name):
    return tuple(float(name == a) for a in "XYZ")


def _select_face(shape, target, part):
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.GeomAbs import GeomAbs_Plane, GeomAbs_Cylinder
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopAbs import TopAbs_FACE
    from OCP.TopoDS import TopoDS
    origin = tuple(resolve(v, part) for v in target.origin)
    index = "XYZ".index(target.axis)
    radius = resolve(target.radius, part) if target.radius is not None else None
    matches = []
    iterator = TopExp_Explorer(shape, TopAbs_FACE)
    while iterator.More():
        face = TopoDS.Face(iterator.Current())
        surface = BRepAdaptor_Surface(face, True)
        geometry = None
        if target.surface == "plane" and surface.GetType() == GeomAbs_Plane:
            geometry = surface.Plane()
        if target.surface == "cylinder" and surface.GetType() == GeomAbs_Cylinder:
            geometry = surface.Cylinder()
        if geometry is not None:
            direction = geometry.Axis().Direction()
            location = geometry.Location()
            parallel = abs(abs(direction.Coord(index + 1)) - 1) < 1e-8
            if target.surface == "plane":
                correct = abs(location.Coord(index + 1) - origin[index]) < 1e-6
            else:
                correct = abs(geometry.Radius() - radius) < 1e-6 and all(abs(location.Coord(i + 1) - origin[i]) < 1e-6 for i in range(3) if i != index)
            if parallel and correct:
                matches.append(face)
        iterator.Next()
    if len(matches) != 1:
        raise ValueError(f"PMI target must select exactly one face; selected {len(matches)}.")
    return matches[0]


# Simple stroke glyphs make presentation independent of system fonts.
_SEGMENTS = [((0, 1), (.6, 1)), ((.6, 1), (.6, .5)), ((.6, .5), (.6, 0)),
             ((.6, 0), (0, 0)), ((0, 0), (0, .5)), ((0, .5), (0, 1)), ((0, .5), (.6, .5))]
_DIGITS = {"0": "012345", "1": "12", "2": "01643", "3": "01236", "4": "5612", "5": "05623", "6": "056234", "7": "012", "8": "0123456", "9": "012356", "-": "6"}


def _presentation(dim, value, part, faces):
    from OCP.BRep import BRep_Builder
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeEdge
    from OCP.TopoDS import TopoDS_Compound
    from OCP.gp import gp_Pnt
    origin = tuple(resolve(v, part) for v in dim.annotation.origin)
    x = _axis(dim.annotation.x_axis)
    n = _axis(dim.annotation.normal)
    y = (n[1]*x[2]-n[2]*x[1], n[2]*x[0]-n[0]*x[2], n[0]*x[1]-n[1]*x[0])
    h = dim.annotation.text_height
    compound = TopoDS_Compound()
    builder = BRep_Builder()
    builder.MakeCompound(compound)
    strokes = []
    text = ("D" if dim.kind == "diameter" else "") + format(value, ".6f").rstrip("0").rstrip(".")
    if dim.uncertainty_acknowledged:
        text = "?" + text
    for offset, char in enumerate(text):
        if char in _DIGITS:
            glyph = [_SEGMENTS[int(i)] for i in _DIGITS[char]]
        elif char == ".":
            glyph = [((.2, 0), (.25, 0))]
        elif char == "D":
            # Circle and diagonal form the diameter symbol.
            glyph = [((.3+.3*math.cos(i*math.pi/8), .5+.5*math.sin(i*math.pi/8)), (.3+.3*math.cos((i+1)*math.pi/8), .5+.5*math.sin((i+1)*math.pi/8))) for i in range(16)] + [((-.05, -.1), (.65, 1.1))]
        else:
            glyph = [((0, .8), (.2, 1)), ((.2, 1), (.6, .8)), ((.6, .8), (.3, .5)), ((.3, .5), (.3, .3)), ((.3, 0), (.35, 0))]
        strokes.extend([((a[0]+offset*.9, a[1]), (b[0]+offset*.9, b[1])) for a, b in glyph])
    for a, b in strokes:
        points = [gp_Pnt(*(origin[i] + h*(p[0]*x[i]+p[1]*y[i]) for i in range(3))) for p in (a, b)]
        builder.Add(compound, BRepBuilderAPI_MakeEdge(*points).Edge())
    # Attach each leader to a measured point on the actual trimmed target face.
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeVertex
    from OCP.BRepExtrema import BRepExtrema_DistShapeShape
    attachment = tuple(origin[i] - .3*h*y[i] for i in range(3))
    for face in faces:
        distance = BRepExtrema_DistShapeShape(BRepBuilderAPI_MakeVertex(gp_Pnt(*attachment)).Vertex(), face)
        distance.Perform()
        if not distance.IsDone() or distance.NbSolution() < 1:
            raise ValueError("Cannot attach a graphical leader to the PMI face.")
        point = distance.PointOnShape2(1)
        endpoint = tuple(point.Coord(i+1) for i in range(3))
        length = math.dist(endpoint, attachment)
        if length <= h:
            raise ValueError("Move the PMI text away from the selected face.")
        along = tuple((attachment[i] - endpoint[i])/length for i in range(3))
        side = (along[1]*n[2]-along[2]*n[1], along[2]*n[0]-along[0]*n[2], along[0]*n[1]-along[1]*n[0])
        side_length = math.sqrt(sum(v*v for v in side))
        side = tuple(v/side_length for v in side) if side_length > 1e-8 else x
        arrow = [tuple(endpoint[i] + h*(.5*along[i] + sign*.15*side[i]) for i in range(3)) for sign in (-1, 1)]
        for start, end in [(attachment, endpoint), (endpoint, arrow[0]), (endpoint, arrow[1])]:
            builder.Add(compound, BRepBuilderAPI_MakeEdge(gp_Pnt(*start), gp_Pnt(*end)).Edge())
    return compound, text, len(strokes) + 3*len(faces)


def export_ap242(shape, destination: Path, product_name: str, pmi=None, description=None):
    """Export real AP242 through XDE, with measured and face-associated PMI."""
    from OCP.IFSelect import IFSelect_RetDone
    from OCP.Interface import Interface_Static
    from OCP.STEPCAFControl import STEPCAFControl_Writer
    from OCP.TCollection import TCollection_ExtendedString, TCollection_HAsciiString
    from OCP.TDataStd import TDataStd_Name
    from OCP.TDocStd import TDocStd_Document
    from OCP.XCAFDoc import XCAFDoc_DocumentTool, XCAFDoc_Dimension
    from OCP.XCAFDimTolObjects import XCAFDimTolObjects_DimensionObject, XCAFDimTolObjects_DimensionType
    from OCP.gp import gp_Ax2, gp_Dir, gp_Pnt
    wrapped = getattr(shape, "wrapped", shape)
    spec, part = validate_pmi(pmi, description) if pmi is not None else (PmiSpecification(dimensions=[]), None)
    document = TDocStd_Document(TCollection_ExtendedString("drawing2cad AP242"))
    XCAFDoc_DocumentTool.SetLengthUnit_s(document, 0.001)
    shapes = XCAFDoc_DocumentTool.ShapeTool_s(document.Main())
    dimensions = XCAFDoc_DocumentTool.DimTolTool_s(document.Main())
    root = shapes.AddShape(wrapped, False)
    TDataStd_Name.Set_s(root, TCollection_ExtendedString(product_name))
    report = []
    for dim in spec.dimensions:
        faces = [_select_face(wrapped, target, part) for target in dim.targets]
        value = resolve(dim.value, part)
        if dim.kind == "diameter":
            measured = 2 * resolve(dim.targets[0].radius, part)
        else:
            index = "XYZ".index(dim.targets[0].axis)
            measured = abs(resolve(dim.targets[0].origin[index], part) - resolve(dim.targets[1].origin[index], part))
        if abs(value - measured) > 1e-6 or measured <= 0:
            raise ValueError(f"PMI value does not match selected geometry: {dim.id}")
        labels = [shapes.AddSubShape(root, face) for face in faces]
        if any(label.IsNull() for label in labels):
            raise ValueError("PMI association is not a subshape of the exported solid.")
        label = dimensions.AddDimension()
        TDataStd_Name.Set_s(label, TCollection_ExtendedString("PMI " + dim.id))
        obj = XCAFDimTolObjects_DimensionObject()
        kind = "Size_Diameter" if dim.kind == "diameter" else "Location_LinearDistance"
        obj.SetType(getattr(XCAFDimTolObjects_DimensionType, "XCAFDimTolObjects_DimensionType_" + kind))
        obj.SetValue(value)
        obj.SetSemanticName(TCollection_HAsciiString(dim.id))
        obj.AddDescription(TCollection_HAsciiString(dim.id), TCollection_HAsciiString("drawing2cad dimension id"))
        for evidence in part.evidence:
            if evidence.id in dim.evidence_ids:
                obj.AddDescription(TCollection_HAsciiString(evidence.status + ": " + evidence.reason),
                                   TCollection_HAsciiString("drawing2cad evidence " + evidence.id))
        origin = tuple(resolve(v, part) for v in dim.annotation.origin)
        obj.SetPlane(gp_Ax2(gp_Pnt(*origin), gp_Dir(*_axis(dim.annotation.normal)), gp_Dir(*_axis(dim.annotation.x_axis))))
        obj.SetPointTextAttach(gp_Pnt(*origin))
        presentation, text, strokes = _presentation(dim, value, part, faces)
        obj.SetPresentation(presentation, TCollection_HAsciiString(dim.id + ": " + text + " mm"))
        XCAFDoc_Dimension.Set_s(label).SetObject(obj)
        if len(labels) == 1:
            dimensions.SetDimension(labels[0], label)
        else:
            dimensions.SetDimension(labels[0], labels[1], label)
        report.append({"id": dim.id, "kind": dim.kind, "value": value, "measured": measured, "unit": "mm", "feature_id": dim.feature_id,
                       "evidence_ids": dim.evidence_ids, "uncertainty_acknowledged": dim.uncertainty_acknowledged, "face_count": len(faces), "presentation_strokes": strokes})
    writer = STEPCAFControl_Writer()
    writer.SetDimTolMode(True)
    Interface_Static.SetCVal_s("write.step.schema", "AP242DIS")
    Interface_Static.SetCVal_s("write.step.unit", "MM")
    if not writer.Transfer(document) or writer.Write(str(destination)) != IFSelect_RetDone:
        raise ValueError("AP242 XDE export failed.")
    return {"schema": "AP242", "dimensions": report, "target_cad_opening": "not_tested", "full_express_validation": "not_tested"}


def _edge_segments(shape):
    from OCP.TopExp import TopExp, TopExp_Explorer
    from OCP.TopAbs import TopAbs_EDGE
    from OCP.TopoDS import TopoDS
    from OCP.BRep import BRep_Tool
    from OCP.BRepAdaptor import BRepAdaptor_Curve
    from OCP.GeomAbs import GeomAbs_Line
    segments = []
    edges = TopExp_Explorer(shape, TopAbs_EDGE)
    while edges.More():
        edge = TopoDS.Edge(edges.Current())
        if BRepAdaptor_Curve(edge).GetType() != GeomAbs_Line:
            raise ValueError("The nominal PMI presentation must contain straight strokes.")
        points = [BRep_Tool.Pnt_s(v) for v in (TopExp.FirstVertex_s(edge), TopExp.LastVertex_s(edge))]
        segments.append(sorted([tuple(p.Coord(i) for i in (1, 2, 3)) for p in points]))
        edges.Next()
    return sorted(segments)


def read_ap242_pmi(path: Path, *, _with_geometry=False):
    """Read XDE values, face associations, and graphical shapes from STEP."""
    from OCP.IFSelect import IFSelect_RetDone
    from OCP.STEPCAFControl import STEPCAFControl_Reader
    from OCP.TCollection import TCollection_ExtendedString
    from OCP.TDocStd import TDocStd_Document
    from OCP.XCAFDoc import XCAFDoc_DocumentTool, XCAFDoc_DimTolTool, XCAFDoc_Dimension, XCAFDoc_ShapeTool
    from OCP.collections import Sequence_TDF_Label
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopAbs import TopAbs_EDGE, TopAbs_FACE, TopAbs_SOLID
    from OCP.TopoDS import TopoDS
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.GeomAbs import GeomAbs_Plane, GeomAbs_Cylinder
    document = TDocStd_Document(TCollection_ExtendedString("drawing2cad PMI read"))
    reader = STEPCAFControl_Reader()
    reader.SetGDTMode(True)
    if reader.ReadFile(str(path)) != IFSelect_RetDone or not reader.Transfer(document):
        raise ValueError("AP242 XDE read failed.")
    shape_tool = XCAFDoc_DocumentTool.ShapeTool_s(document.Main())
    roots = Sequence_TDF_Label()
    shape_tool.GetFreeShapes(roots)
    product_shapes = []
    for index in range(1, roots.Length()+1):
        candidate = XCAFDoc_ShapeTool.GetShape_s(roots.Value(index))
        if TopExp_Explorer(candidate, TopAbs_SOLID).More():
            product_shapes.append(candidate)
    tool = XCAFDoc_DocumentTool.DimTolTool_s(document.Main())
    labels = Sequence_TDF_Label()
    tool.GetDimensionLabels(labels)
    result = []
    for i in range(1, labels.Length()+1):
        label = labels.Value(i)
        obj = XCAFDoc_Dimension.Set_s(label).GetObject()
        first, second = Sequence_TDF_Label(), Sequence_TDF_Label()
        XCAFDoc_DimTolTool.GetRefShapeLabel_s(label, first, second)
        references = []
        face_objects = []
        for seq in (first, second):
            for j in range(1, seq.Length()+1):
                face = XCAFDoc_ShapeTool.GetShape_s(seq.Value(j))
                face_objects.append(face)
                record = {"is_face": not face.IsNull() and face.ShapeType() == TopAbs_FACE}
                if record["is_face"]:
                    surface = BRepAdaptor_Surface(TopoDS.Face(face), True)
                    geometry = None
                    if surface.GetType() == GeomAbs_Plane:
                        record["surface"] = "plane"
                        geometry = surface.Plane()
                    elif surface.GetType() == GeomAbs_Cylinder:
                        record["surface"] = "cylinder"
                        geometry = surface.Cylinder()
                        record["radius"] = geometry.Radius()
                    if geometry is not None:
                        record["origin"] = [geometry.Location().Coord(k) for k in (1, 2, 3)]
                        record["direction"] = [geometry.Axis().Direction().Coord(k) for k in (1, 2, 3)]
                references.append(record)
        presentation = obj.GetPresentation()
        count = 0
        if not presentation.IsNull():
            edges = TopExp_Explorer(presentation, TopAbs_EDGE)
            while edges.More():
                count += 1
                edges.Next()
        notes = {obj.GetDescriptionName(k).ToCString(): obj.GetDescription(k).ToCString()
                 for k in range(obj.NbDescriptions())}
        result.append({"id": notes.get("drawing2cad dimension id", ""), "type": int(obj.GetType()), "value": obj.GetValue(),
                       "references": references, "presentation_edges": count, "has_plane": obj.HasPlane(),
                       "descriptions": notes})
        if _with_geometry:
            result[-1]["_geometry"] = {"references": face_objects, "products": product_shapes, "presentation": presentation}
    return result



def verify_ap242_pmi(path: Path, pmi, description):
    """Compare imported nominal PMI with the embedded contract, in a fresh worker."""
    from .p21 import sth_p21_parse, sth_p21_validate_refs
    records = sth_p21_parse(Path(path).read_text(encoding="utf-8"))
    sth_p21_validate_refs(records)
    kinds = set()
    for kind, args in records.values():
        if kind == "__COMPLEX__":
            kinds.update(item.name for item in args)
        else:
            kinds.add(kind)
    nominal = {"DIMENSIONAL_SIZE", "DIMENSIONAL_LOCATION"}
    unsupported = {kind for kind in kinds if "TOLERANCE" in kind or kind.startswith("DATUM")
                   or (kind.startswith(("DIMENSIONAL_SIZE", "DIMENSIONAL_LOCATION", "ANGULAR_SIZE", "ANGULAR_LOCATION")) and kind not in nominal)}
    if unsupported:
        raise ValueError("Unsupported semantic PMI entities: " + ", ".join(sorted(unsupported)))
    spec, part = validate_pmi(pmi, description)
    actual = read_ap242_pmi(path, _with_geometry=True)
    if len(actual) != len(spec.dimensions):
        raise ValueError("Imported PMI count does not match its contract.")
    by_id = {item["id"]: item for item in actual}
    if len(by_id) != len(actual) or set(by_id) != {d.id for d in spec.dimensions}:
        raise ValueError("Imported PMI identifiers do not match its contract.")
    reports = []
    for dim in spec.dimensions:
        item = by_id[dim.id]
        if item["type"] != (15 if dim.kind == "diameter" else 2) or abs(item["value"] - resolve(dim.value, part)) > 1e-6:
            raise ValueError(f"Imported PMI type or value mismatch: {dim.id}")
        if len(item["references"]) != len(dim.targets):
            raise ValueError(f"Imported PMI association count mismatch: {dim.id}")
        geometry = item["_geometry"]
        if len(geometry["products"]) != 1:
            raise ValueError("PMI requires exactly one imported product body.")
        selected_faces = [_select_face(geometry["products"][0], target, part) for target in dim.targets]
        if any(not selected.IsSame(actual_face) for selected, actual_face in zip(selected_faces, geometry["references"])):
            raise ValueError(f"Imported PMI face is not the selected product subshape: {dim.id}")
        for ref, target in zip(item["references"], dim.targets):
            index = "XYZ".index(target.axis)
            origin = [resolve(v, part) for v in target.origin]
            if not ref["is_face"] or ref.get("surface") != target.surface or abs(abs(ref["direction"][index])-1) > 1e-8:
                raise ValueError(f"Imported PMI face type or direction mismatch: {dim.id}")
            positions = [index] if target.surface == "plane" else [i for i in range(3) if i != index]
            if any(abs(ref["origin"][i]-origin[i]) > 1e-6 for i in positions):
                raise ValueError(f"Imported PMI face location mismatch: {dim.id}")
            if target.radius is not None and abs(ref["radius"]-resolve(target.radius, part)) > 1e-6:
                raise ValueError(f"Imported PMI cylinder radius mismatch: {dim.id}")
        if dim.kind == "diameter":
            measured = 2 * item["references"][0]["radius"]
        else:
            index = "XYZ".index(dim.targets[0].axis)
            measured = abs(item["references"][0]["origin"][index] - item["references"][1]["origin"][index])
        if abs(item["value"] - measured) > 1e-6 or measured <= 0:
            raise ValueError(f"Imported PMI value does not measure its associated faces: {dim.id}")
        if not item["has_plane"] or item["presentation_edges"] < 4:
            raise ValueError(f"Imported PMI graphical presentation is missing: {dim.id}")
        expected_presentation, _, _ = _presentation(dim, item["value"], part, selected_faces)
        expected_segments = _edge_segments(expected_presentation)
        actual_segments = _edge_segments(geometry["presentation"])
        if len(expected_segments) != len(actual_segments):
            raise ValueError(f"Imported PMI graphical stroke count does not match: {dim.id}")
        for expected_segment in expected_segments:
            match = next((index for index, actual_segment in enumerate(actual_segments)
                          if any(all(math.dist(a, b) <= 1e-5 for a, b in zip(expected_segment, candidate))
                                 for candidate in (actual_segment, actual_segment[::-1]))), None)
            if match is None:
                raise ValueError(f"Imported PMI graphical strokes do not match: {dim.id}")
            actual_segments.pop(match)
        expected_notes = {"drawing2cad evidence " + e.id: e.status + ": " + e.reason
                          for e in part.evidence if e.id in dim.evidence_ids}
        expected_notes["drawing2cad dimension id"] = dim.id
        if item["descriptions"] != expected_notes:
            raise ValueError(f"Imported PMI evidence notes do not match: {dim.id}")
        statuses = {e.id: e.status for e in part.evidence}
        reports.append({"id": dim.id, "value": item["value"], "unit": "mm", "kind": dim.kind,
                        "feature_id": dim.feature_id, "evidence_statuses": {eid: statuses[eid] for eid in dim.evidence_ids},
                        "uncertainty_acknowledged": dim.uncertainty_acknowledged,
                        "geometry_association": "pass", "graphical_shape_readback": "pass",
                        "presentation_edges": item["presentation_edges"]})
    return {"status": "pass", "dimensions": reports, "scope": "nominal diameter and parallel-plane distance",
            "target_cad_opening": "not_tested", "external_conformance": "not_tested", "graphical_viewer_acceptance": "not_tested"}
