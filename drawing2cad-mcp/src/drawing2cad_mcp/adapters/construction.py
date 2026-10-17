"""Bounded STEP-only construction data for the drawing2cad adapter.

The property is an application-specific declarative recipe. It is not a
standard procedural representation and does not prove native CAD history.
"""

from copy import deepcopy
import hashlib
import json
import math
import re

from .p21 import P21Ref, P21Typed, _SthP21Parser, sth_p21_parse, sth_p21_record, sth_p21_validate_refs
from ..part_schema import parse_description

PROPERTY = "drawing2cad.construction.v1"
PROFILE = "drawing2cad-construction/1"
MAX_PAYLOAD = 1024 * 1024
MAX_STEP = 32 * 1024 * 1024
CHUNK_SIZE = 3000


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)


def _digest(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _refs(value):
    if isinstance(value, P21Ref):
        yield int(value)
    elif isinstance(value, (list, tuple)):
        for child in value:
            yield from _refs(child)
    elif isinstance(value, P21Typed):
        yield from _refs(value.args)


def _records(text):
    if not isinstance(text, str) or len(text.encode("utf-8")) > MAX_STEP:
        raise ValueError("STEP input exceeds the supported size.")
    # Use lexical tokens so comments and quoted values cannot impersonate a header.
    parser = _SthP21Parser(text, MAX_STEP, 200000, 2000000, 128, 1048576)
    parser.expect("NAME", "ISO-10303-21")
    parser.expect(";")
    parser.expect("NAME", "HEADER")
    parser.expect(";")
    schemas = []
    while parser.peek()[:2] != ("NAME", "ENDSEC"):
        name = parser.expect("NAME")[1]
        args = parser.args(1)
        parser.expect(";")
        if name == "FILE_SCHEMA":
            schemas.append(args)
    schema = schemas[0][0][0] if len(schemas) == 1 and len(schemas[0]) == 1 and isinstance(schemas[0][0], list) and len(schemas[0][0]) == 1 else None
    if not isinstance(schema, str) or not re.fullmatch(r"AP242_MANAGED_MODEL_BASED_3D_ENGINEERING_MIM_LF(?:\s*\{\s*1\s+0\s+10303\s+442\s+1\s+1\s+4\s*\})?", schema):
        raise ValueError("The construction adapter requires an actual AP242 export.")
    records = sth_p21_parse(text, exchange=True)
    sth_p21_validate_refs(records)
    arities = {"PROPERTY_DEFINITION": 3, "PROPERTY_DEFINITION_REPRESENTATION": 2,
               "REPRESENTATION": 3, "DESCRIPTIVE_REPRESENTATION_ITEM": 2,
               "SHAPE_DEFINITION_REPRESENTATION": 2, "PRODUCT_DEFINITION_SHAPE": 3,
               "ADVANCED_BREP_SHAPE_REPRESENTATION": 3}
    for kind, args in records.values():
        if kind in arities and len(args) != arities[kind]:
            raise ValueError("Invalid entity argument count in construction data.")
    return records


def _binding(records):
    links = [(i, args) for i, (kind, args) in records.items()
             if kind == "SHAPE_DEFINITION_REPRESENTATION"]
    if len(links) != 1:
        raise ValueError("The adapter supports exactly one product shape.")
    _, link = links[0]
    if len(link) != 2 or not all(isinstance(value, P21Ref) for value in link):
        raise ValueError("Invalid product shape link.")
    shape_kind, shape = records[int(link[0])]
    rep_kind, rep = records[int(link[1])]
    if shape_kind != "PRODUCT_DEFINITION_SHAPE" or len(shape) != 3 or rep_kind != "ADVANCED_BREP_SHAPE_REPRESENTATION" or len(rep) != 3:
        raise ValueError("The adapter supports one advanced BREP representation.")
    if not isinstance(shape[2], P21Ref) or records[int(shape[2])][0] != "PRODUCT_DEFINITION":
        raise ValueError("The product definition is missing.")
    if not isinstance(rep[2], P21Ref):
        raise ValueError("The representation context is missing.")
    reachable, pending = set(), [int(link[1])]
    while pending:
        current = pending.pop()
        if current in reachable:
            continue
        reachable.add(current)
        pending.extend(_refs(records[current][1]))
    geometry = "\n".join(sth_p21_record(i, *records[i]) for i in sorted(reachable))
    return shape[2], rep[2], _digest(geometry)


def _check_product_name(records, product_ref, expected):
    kind, definition = records[int(product_ref)]
    if kind != "PRODUCT_DEFINITION" or len(definition) != 4 or not isinstance(definition[2], P21Ref):
        raise ValueError("Invalid linked product definition.")
    kind, formation = records[int(definition[2])]
    expected_count = {"PRODUCT_DEFINITION_FORMATION": 3, "PRODUCT_DEFINITION_FORMATION_WITH_SPECIFIED_SOURCE": 4}.get(kind)
    if expected_count is None or len(formation) != expected_count or not isinstance(formation[2], P21Ref):
        raise ValueError("Invalid linked product formation.")
    kind, product = records[int(formation[2])]
    if kind != "PRODUCT" or len(product) != 4 or not isinstance(product[1], str) or not re.fullmatch(re.escape(expected) + r"(?:-\d+)?", product[1]):
        raise ValueError("The linked product name does not match the construction description.")


def embed_construction(text: str, description: dict, *, pmi: dict | None = None) -> tuple[str, dict]:
    """Append a product-bound recipe without changes to existing STEP entities."""
    records = _records(text)
    product, context, geometry_hash = _binding(records)
    if any(kind == "PROPERTY_DEFINITION" and args[0] == PROPERTY for kind, args in records.values()):
        raise ValueError("A construction property already exists.")
    description = parse_description(description).model_dump(mode="json")
    _check_product_name(records, product, description["name"])
    if pmi is not None:
        from .semantic_pmi import validate_pmi
        pmi = validate_pmi(pmi, description)[0].model_dump(mode="json")
    payload = {"profile": PROFILE, "description": description,
               "description_sha256": _digest(_json(description)), "geometry_sha256": geometry_hash,
               "pmi": pmi, "encoding": "application_specific_declarative_recipe"}
    encoded = _json(payload)
    if len(encoded) > MAX_PAYLOAD:
        raise ValueError("Construction data exceeds the supported size.")
    chunks = [encoded[pos:pos + CHUNK_SIZE] for pos in range(0, len(encoded), CHUNK_SIZE)]
    start = max(records) + 1
    items = [start + i + 1 for i in range(len(chunks))]
    rep_id, link_id = items[-1] + 1, items[-1] + 2
    additions = [sth_p21_record(start, "PROPERTY_DEFINITION", [PROPERTY, "Application-specific construction; not standard procedural history", product])]
    for index, (ident, chunk) in enumerate(zip(items, chunks), 1):
        additions.append(sth_p21_record(ident, "DESCRIPTIVE_REPRESENTATION_ITEM", [f"application/json;chunk={index:06d}/{len(chunks):06d}", chunk]))
    additions.extend([sth_p21_record(rep_id, "REPRESENTATION", [PROPERTY, [P21Ref(i) for i in items], context]),
                      sth_p21_record(link_id, "PROPERTY_DEFINITION_REPRESENTATION", [P21Ref(start), P21Ref(rep_id)])])
    end = text.rfind("ENDSEC;")
    if end < 0 or not re.fullmatch(r"ENDSEC;\s*END-ISO-10303-21;\s*", text[end:]):
        raise ValueError("The STEP exchange structure is incomplete.")
    candidate = text[:end] + "\n" + "\n".join(additions) + "\n" + text[end:]
    decoded = read_construction(candidate)
    if decoded != payload:
        raise ValueError("Construction data did not survive the write/read check.")
    return candidate, {"profile": PROFILE, "description_sha256": payload["description_sha256"],
                       "geometry_sha256": geometry_hash, "preserved_entity_count": len(records),
                       "added_entity_count": len(additions), "standard_procedural_history": "not_supported"}


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON field in construction data.")
        result[key] = value
    return result


def _reject(value):
    raise ValueError("Nonfinite JSON value in construction data.")


def read_construction(text: str) -> dict:
    """Read and validate one recipe. This function never executes payload code."""
    records = _records(text)
    product, context, geometry_hash = _binding(records)
    properties = [(i, args) for i, (kind, args) in records.items()
                  if kind == "PROPERTY_DEFINITION" and args[0] == PROPERTY]
    if len(properties) != 1:
        raise ValueError("Exactly one construction property is required.")
    ident, prop = properties[0]
    if len(prop) != 3 or not isinstance(prop[2], P21Ref) or prop[2] != product:
        raise ValueError("Construction data belongs to another product.")
    links = [args for kind, args in records.values()
             if kind == "PROPERTY_DEFINITION_REPRESENTATION" and args[0] == P21Ref(ident)]
    if len(links) != 1 or len(links[0]) != 2 or not all(isinstance(value, P21Ref) for value in links[0]):
        raise ValueError("The construction representation link is ambiguous.")
    kind, rep = records[int(links[0][1])]
    if kind != "REPRESENTATION" or len(rep) != 3 or rep[0] != PROPERTY or not isinstance(rep[2], P21Ref) or rep[2] != context or not isinstance(rep[1], list) or not 1 <= len(rep[1]) <= (MAX_PAYLOAD // CHUNK_SIZE + 1):
        raise ValueError("Invalid construction representation.")
    chunks = []
    for index, ref in enumerate(rep[1], 1):
        if not isinstance(ref, P21Ref):
            raise ValueError("Invalid construction item reference.")
        kind, item = records[int(ref)]
        if kind != "DESCRIPTIVE_REPRESENTATION_ITEM" or len(item) != 2 or item[0] != f"application/json;chunk={index:06d}/{len(rep[1]):06d}" or not isinstance(item[1], str) or len(item[1]) > CHUNK_SIZE:
            raise ValueError("Construction chunks are missing, reordered, or oversized.")
        chunks.append(item[1])
    encoded = "".join(chunks)
    if len(encoded) > MAX_PAYLOAD:
        raise ValueError("Construction data exceeds the supported size.")
    try:
        payload = json.loads(encoded, object_pairs_hook=_unique, parse_constant=_reject)
    except (RecursionError, json.JSONDecodeError) as error:
        raise ValueError("Invalid construction JSON.") from error
    required = {"profile", "description", "description_sha256", "geometry_sha256", "encoding", "pmi"}
    if not isinstance(payload, dict) or set(payload) != required or payload["profile"] != PROFILE or payload["encoding"] != "application_specific_declarative_recipe":
        raise ValueError("Unsupported construction profile.")
    if payload["geometry_sha256"] != geometry_hash:
        raise ValueError("Construction data is not bound to this STEP geometry.")
    if _digest(_json(payload["description"])) != payload["description_sha256"]:
        raise ValueError("The construction description hash does not match.")
    normalized = parse_description(payload["description"]).model_dump(mode="json")
    _check_product_name(records, product, normalized["name"])
    if normalized != payload["description"]:
        raise ValueError("Invalid construction description or PMI collection.")
    if payload["pmi"] is not None:
        from .semantic_pmi import validate_pmi
        validate_pmi(payload["pmi"], normalized)
    return payload


def change_parameters(description: dict, changes: dict) -> dict:
    """Change named driving values. Keep source expectations for later review."""
    if not isinstance(changes, dict) or len(changes) > 1000:
        raise ValueError("Parameter changes must be a bounded object.")
    changed = deepcopy(description)
    parameters = {item["name"]: item for item in changed.get("parameters", [])}
    for name, value in changes.items():
        if name not in parameters or isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value):
            raise ValueError("Parameter changes require existing names and finite numeric values.")
        parameters[name]["value"] = value
    return parse_description(changed).model_dump(mode="json")
