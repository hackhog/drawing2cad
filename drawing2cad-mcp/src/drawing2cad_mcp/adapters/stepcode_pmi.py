"""Check the nominal PMI profile from STEPcode's independently parsed inventory.

This module does not parse STEP bytes and does not use OCCT. These explicit graph
checks do not evaluate EXPRESS WHERE rules or geometric measurement accuracy.
"""

import math
import re


def _attribute(row: dict, name: str) -> str:
    values = {a["value"].rstrip("\x00") for a in row["attributes"] if a["name"] == name}
    if len(values) != 1:
        raise ValueError(f"Missing or ambiguous {name} on entity #{row['id']}.")
    return values.pop()


def _reference(value: str) -> int:
    if not re.fullmatch(r"#[1-9][0-9]*", value):
        raise ValueError("The nominal PMI profile requires a direct entity reference.")
    return int(value[1:])


def _references(value: str) -> list[int]:
    if not re.fullmatch(r"\(#[1-9][0-9]*(?:,#[1-9][0-9]*)*\)", value):
        raise ValueError("The nominal PMI profile requires a nonempty reference list.")
    return [int(ref[1:]) for ref in value[1:-1].split(",")]


def _string(value: str) -> str:
    if not re.fullmatch(r"'(?:[^']|'')*'", value):
        raise ValueError("The nominal PMI profile requires a STEP string.")
    text = value[1:-1].replace("''", "'")
    output = []
    position = 0
    while position < len(text):
        if text[position] != "\\":
            output.append(text[position])
            position += 1
        elif text.startswith("\\\\", position):
            output.append("\\")
            position += 2
        elif text.startswith(("\\X2\\", "\\X4\\"), position):
            width = int(text[position + 2])
            end = text.find("\\X0\\", position + 4)
            if end < 0:
                raise ValueError("The STEP string has an incomplete Unicode escape.")
            raw = bytes.fromhex(text[position + 4:end])
            output.append(raw.decode("utf-16-be" if width == 2 else "utf-32-be"))
            position = end + 4
        elif text.startswith("\\X\\", position):
            output.append(bytes.fromhex(text[position + 3:position + 5]).decode("latin-1"))
            position += 5
        else:
            raise ValueError("The nominal PMI profile does not support this STEP string escape.")
    return "".join(output)


def verify_nominal_pmi(report: dict, expected: list[dict] | None = None,
                       product_name: str | None = None) -> dict:
    """Check dimensions, mm units, product links, and face membership.

    `expected` uses resolved `{id, kind, value}` records from the build contract.
    Parser or inventory failure never becomes a passed semantic check.
    """
    result = {"check": "independent_nominal_pmi_graph", "status": "fail",
              "profile": "drawing2cad.nominal-pmi-graph/1", "dimensions": [],
              "scope": "Nominal diameter and linear-distance values, millimetres, identifiers, product links, and face membership.",
              "geometric_value_verification": "not_tested", "full_express_validation": "not_tested",
              "graphical_appearance": "not_tested"}
    try:
        result["dimensions"] = _verify(report, expected, product_name)
        result["dimension_count"] = len(result["dimensions"])
        result["product_graph"] = "pass" if result["dimensions"] else "not_tested"
        result["status"] = "pass"
    except (KeyError, TypeError, ValueError, IndexError) as error:
        result["reason"] = str(error)[:2000]
    return result


def _verify(report: dict, expected: list[dict] | None, product_name: str | None) -> list[dict]:
    if report.get("status") != "pass" or not report.get("pmi_inventory_complete"):
        raise ValueError("A complete, passed independent schema read is required.")
    counts = report["entity_counts"]
    unsupported = [name for name in counts if "TOLERANCE" in name or name.startswith("DATUM")
                   or (name.startswith(("DIMENSIONAL_SIZE", "DIMENSIONAL_LOCATION", "ANGULAR_SIZE", "ANGULAR_LOCATION"))
                       and name not in {"DIMENSIONAL_SIZE", "DIMENSIONAL_LOCATION"})]
    if unsupported:
        raise ValueError("Unsupported PMI types: " + ", ".join(sorted(unsupported)))
    rows = report["pmi_inventory"]
    by_id = {row["id"]: row for row in rows}
    if len(by_id) != len(rows):
        raise ValueError("The independent inventory contains duplicate entity identifiers.")

    def of_type(kind):
        return [row for row in rows if kind in row["types"]]

    def target(row, attribute, kind):
        found = by_id[_reference(_attribute(row, attribute))]
        if kind not in found["types"]:
            raise ValueError(f"Entity #{row['id']} has a wrong {attribute} target.")
        return found

    def exactly_one(items, name):
        if len(items) != 1:
            raise ValueError("The nominal PMI profile requires exactly one " + name + ".")
        return items[0]

    dims = of_type("DIMENSIONAL_SIZE") + of_type("DIMENSIONAL_LOCATION")
    if not dims:
        if expected:
            raise ValueError("Expected nominal PMI is missing.")
        return []
    root = exactly_one(of_type("ADVANCED_BREP_SHAPE_REPRESENTATION"), "BREP representation")
    binding = exactly_one([r for r in of_type("SHAPE_DEFINITION_REPRESENTATION")
                           if _reference(_attribute(r, "used_representation")) == root["id"]], "product-to-BREP binding")
    product_shape = target(binding, "definition", "PRODUCT_DEFINITION_SHAPE")
    definition = target(product_shape, "definition", "PRODUCT_DEFINITION")
    formation = target(definition, "formation", "PRODUCT_DEFINITION_FORMATION")
    product = target(formation, "of_product", "PRODUCT")
    if product_name is not None and _string(_attribute(product, "name")) != product_name:
        raise ValueError("The independent product name does not match the build contract.")
    solid = exactly_one([by_id[i] for i in _references(_attribute(root, "items"))
                         if i in by_id and "MANIFOLD_SOLID_BREP" in by_id[i]["types"]], "solid in the BREP representation")
    shell = target(solid, "outer", "CLOSED_SHELL")
    faces = set(_references(_attribute(shell, "cfs_faces")))
    if any("ADVANCED_FACE" not in by_id[i]["types"] for i in faces):
        raise ValueError("The nominal PMI profile requires explicit advanced faces.")
    context = target(root, "context_of_items", "GLOBAL_UNIT_ASSIGNED_CONTEXT")
    context_units = set(_references(_attribute(context, "units")))
    links = of_type("DIMENSIONAL_CHARACTERISTIC_REPRESENTATION")
    if len(links) != len(dims):
        raise ValueError("Nominal dimensions and characteristic representations are not one-to-one.")
    records = []
    for dim in dims:
        diameter = "DIMENSIONAL_SIZE" in dim["types"]
        kind = "diameter" if diameter else "linear"
        name = "diameter" if diameter else "linear distance"
        if _string(_attribute(dim, "name")) != name:
            raise ValueError("Unsupported nominal dimension kind.")
        link = exactly_one([r for r in links if _reference(_attribute(r, "dimension")) == dim["id"]], "characteristic representation for each dimension")
        representation = target(link, "representation", "SHAPE_DIMENSION_REPRESENTATION")
        if _reference(_attribute(representation, "context_of_items")) != context["id"]:
            raise ValueError("The dimension and BREP use different representation contexts.")
        # STEPcode checks each reference. Its inventory omits descriptive evidence
        # and construction payload text, which this nominal graph check does not use.
        items = [by_id[i] for i in _references(_attribute(representation, "items")) if i in by_id]
        measure = exactly_one([r for r in items if "LENGTH_MEASURE_WITH_UNIT" in r["types"]], "nominal length measure")
        if "MEASURE_REPRESENTATION_ITEM" not in measure["types"]:
            raise ValueError("The length measure is not a representation item.")
        numeric = re.fullmatch(r"(?:POSITIVE_)?LENGTH_MEASURE\(([+\-0-9.Ee]+)\)", _attribute(measure, "value_component"))
        if not numeric or not math.isfinite(value := float(numeric[1])) or value <= 0:
            raise ValueError("The nominal length value is invalid.")
        unit = target(measure, "unit_component", "LENGTH_UNIT")
        if ("SI_UNIT" not in unit["types"] or _attribute(unit, "prefix") != "MILLI"
                or _attribute(unit, "name") != "METRE" or unit["id"] not in context_units):
            raise ValueError("The dimension must use the BREP millimetre unit.")
        identifier = exactly_one([r for r in items if "DESCRIPTIVE_REPRESENTATION_ITEM" in r["types"]
                                  and _string(_attribute(r, "name")) == "drawing2cad dimension id"], "dimension identifier")
        dimension_id = _string(_attribute(identifier, "description"))
        aspect_names = ["applies_to"] if diameter else ["relating_shape_aspect", "related_shape_aspect"]
        associated_faces = []
        for aspect_name in aspect_names:
            aspect = target(dim, aspect_name, "SHAPE_ASPECT")
            if _reference(_attribute(aspect, "of_shape")) != product_shape["id"] or _attribute(aspect, "product_definitional") != "T":
                raise ValueError("The dimension is detached from the BREP product.")
            usage = exactly_one([r for r in of_type("GEOMETRIC_ITEM_SPECIFIC_USAGE")
                                 if _reference(_attribute(r, "definition")) == aspect["id"]], "geometric usage for each aspect")
            face = target(usage, "identified_item", "ADVANCED_FACE")
            if _reference(_attribute(usage, "used_representation")) != root["id"] or face["id"] not in faces:
                raise ValueError("The dimension face is outside the product solid.")
            associated_faces.append(face["id"])
        if len(set(associated_faces)) != len(associated_faces):
            raise ValueError("A linear dimension must reference two distinct faces.")
        records.append({"id": dimension_id, "kind": kind, "value": value, "unit": "mm",
                        "dimension_entity": dim["id"], "face_entities": associated_faces,
                        "product_entity": product["id"]})
    actual = {record["id"]: record for record in records}
    if len(actual) != len(records):
        raise ValueError("Nominal dimension identifiers are not unique.")
    if expected is not None:
        planned = {row["id"]: row for row in expected}
        if len(planned) != len(expected) or set(planned) != set(actual):
            raise ValueError("Nominal identifiers do not match the build contract.")
        for name, row in actual.items():
            if (row["kind"] != planned[name]["kind"] or
                    not math.isclose(row["value"], planned[name]["value"], rel_tol=0, abs_tol=1e-6)):
                raise ValueError("Nominal value or kind does not match the build contract: " + name)
    return records
