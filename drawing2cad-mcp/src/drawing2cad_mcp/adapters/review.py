"""Read and append application review metadata. This module does not export CAD."""

from .p21 import P21Ref, sth_p21_parse, sth_p21_validate_refs, sth_p21_record

def reject_constant(value):
    raise ValueError("Nonfinite JSON constant: " + value)

def finite_json_float(value):
    import math
    number=float(value)
    if not math.isfinite(number):
        raise ValueError("Nonfinite JSON number: " + value)
    return number

def read_adapter_properties(text, expected_schemas, records=None):
    import json, re
    if records is None: records = sth_p21_parse(text)
    sth_p21_validate_refs(records)
    main_links = [a for t, a in records.values()
                  if t == 'EXPLICIT_PROCEDURAL_SHAPE_REPRESENTATION_RELATIONSHIP']
    if len(main_links) != 1:
        raise ValueError('Exactly one constructive-to-BREP link required')
    main_ref = main_links[0][3]
    main_kind, main = records[int(main_ref)]
    shapes = [a for t, a in records.values()
              if t == 'SHAPE_DEFINITION_REPRESENTATION' and a[1] == main_ref]
    if main_kind != 'ADVANCED_BREP_SHAPE_REPRESENTATION' or len(shapes) != 1:
        raise ValueError('Ambiguous main product representation')
    def unique_object(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise ValueError('Duplicate JSON metadata key: ' + key)
            value[key] = item
        return value
    output = {}
    for name, schema in expected_schemas.items():
        matches = [(i, a) for i, (t, a) in records.items()
                   if t == 'PROPERTY_DEFINITION' and a[0] == name]
        if len(matches) != 1:
            raise ValueError('Expected exactly one adapter property: ' + name)
        ident, prop = matches[0]
        if prop[2] != shapes[0][0]:
            raise ValueError('Adapter property belongs to a different product')
        links = [a for t, a in records.values()
                 if t == 'PROPERTY_DEFINITION_REPRESENTATION' and a[0] == P21Ref(ident)]
        if len(links) != 1:
            raise ValueError('Ambiguous adapter property representation')
        kind, rep = records[int(links[0][1])]
        if kind != 'REPRESENTATION' or not rep[1] or len(rep[1]) > 525 or rep[2] != main[2]:
            raise ValueError('Unsupported adapter property representation')
        chunks = []
        for index, item_ref in enumerate(rep[1], 1):
            kind, item = records[int(item_ref)]
            if kind != 'DESCRIPTIVE_REPRESENTATION_ITEM':
                raise ValueError('Expected descriptive JSON item')
            if len(rep[1]) == 1 and item[0] == 'application/json':
                chunks.append(item[1])
            else:
                tag = re.fullmatch(r'application/json;chunk=([0-9]{6})/([0-9]{6})', item[0])
                if not tag or int(tag[1]) != index or int(tag[2]) != len(rep[1]) or len(item[1]) > 4000:
                    raise ValueError('Invalid, reordered or incomplete JSON chunks')
                chunks.append(item[1])
        encoded = ''.join(chunks)
        if len(encoded) > 2097152:
            raise ValueError('Adapter property exceeds supported size')
        data = json.loads(encoded, object_pairs_hook=unique_object, parse_constant=reject_constant, parse_float=finite_json_float)
        if not isinstance(data, dict) or data.get('schema') != schema:
            raise ValueError('Unsupported adapter schema for ' + name)
        output[name] = data
    return output


def append_adapter_properties(text, properties):
    import json, hashlib
    records = sth_p21_parse(text)
    sth_p21_validate_refs(records)
    links = [a for t, a in records.values()
             if t == 'EXPLICIT_PROCEDURAL_SHAPE_REPRESENTATION_RELATIONSHIP']
    if len(links) != 1:
        raise ValueError('Exactly one constructive-to-BREP link required')
    main_rep = links[0][3]
    kind, main = records[int(main_rep)]
    if kind != 'ADVANCED_BREP_SHAPE_REPRESENTATION':
        raise ValueError('Expected evaluated BREP representation')
    sdr = [a for t, a in records.values()
           if t == 'SHAPE_DEFINITION_REPRESENTATION' and a[1] == main_rep]
    if len(sdr) != 1 or records[int(sdr[0][0])][0] != 'PRODUCT_DEFINITION_SHAPE':
        raise ValueError('Ambiguous product shape')
    product_shape, context = sdr[0][0], main[2]
    new_records = []
    next_id = max(records) + 1
    schemas = {}
    for name, data in sorted(properties.items()):
        if any(t == 'PROPERTY_DEFINITION' and a[0] == name for t, a in records.values()):
            raise ValueError('Adapter property already exists: ' + name)
        if not name.startswith('drawing2cad.') or not isinstance(data, dict) or not isinstance(data.get('schema'), str):
            raise ValueError('Namespaced property and explicit schema required')
        encoded = json.dumps(data, ensure_ascii=True, sort_keys=True, separators=(',', ':'), allow_nan=False)
        if len(encoded) > 2097152:
            raise ValueError('Adapter property exceeds supported size')
        chunks = [encoded[pos:pos+4000] for pos in range(0, len(encoded), 4000)]
        p = next_id
        item_ids = list(range(p + 1, p + 1 + len(chunks)))
        r, link = p + 1 + len(chunks), p + 2 + len(chunks)
        next_id = link + 1
        new_records.append(sth_p21_record(p, 'PROPERTY_DEFINITION',
            [name, 'Adapter metadata; not original drawing PMI', product_shape]))
        for index, (i, chunk) in enumerate(zip(item_ids, chunks), 1):
            tag = 'application/json' if len(chunks) == 1 else 'application/json;chunk=%06d/%06d' % (index, len(chunks))
            new_records.append(sth_p21_record(i, 'DESCRIPTIVE_REPRESENTATION_ITEM', [tag, chunk]))
        new_records += [sth_p21_record(r, 'REPRESENTATION', [name, [P21Ref(i) for i in item_ids], context]),
                        sth_p21_record(link, 'PROPERTY_DEFINITION_REPRESENTATION', [P21Ref(p), P21Ref(r)])]
        schemas[name] = data['schema']
    end = text.rfind('ENDSEC;')
    if end < 0 or 'END-ISO-10303-21;' not in text[end:]:
        raise ValueError('Unsupported STEP file ending')
    candidate = text[:end] + '\n' + '\n'.join(new_records) + '\n' + text[end:]
    parsed = sth_p21_parse(candidate)
    sth_p21_validate_refs(parsed)
    if any(i not in parsed or sth_p21_record(i, *parsed[i]) != sth_p21_record(i, *old)
           for i, old in records.items()):
        raise ValueError('Existing STEP entities changed')
    decoded = read_adapter_properties(candidate, schemas)
    if decoded != properties:
        raise ValueError('Adapter metadata round-trip failed')
    return candidate, {'source_sha256': hashlib.sha256(text.encode('utf-8')).hexdigest(),
            'output_sha256': hashlib.sha256(candidate.encode('utf-8')).hexdigest(),
            'preserved_entities': len(records), 'added_entities': len(new_records),
            'schemas': schemas, 'exact_metadata_roundtrip': True}
