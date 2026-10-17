# Inline-Container für Adapter- und Reviewdaten

Diese Ergänzung speichert Bedienzuordnung und Prüfmarkierungen im selben STEP-Hauptmodell. Die Konstruktion bleibt in den auswertbaren Standard-Operationsentities; die 31 ursprünglichen PMI des Maschinenteil-Falls werden nicht umdefiniert. Die Inhalte der zusätzlichen JSON-Eigenschaften sind **anwendungsspezifische Adapterdaten**, keine standardisierten parametrischen STEP-Constraints oder zusätzlichen Zeichnungsanforderungen. Ein fremder CAD-Adapter muss diese Schemata ausdrücklich implementieren.

Voraussetzung: den Parserblock aus `inline-procedural-adapter.md` inline laden. Folgenden Code ebenfalls nur im Speicher über FreeCAD-MCP ausführen. Er benötigt keine Sessionvariablen, nur die dort definierten P21-Parser-/Serializer-Funktionen. `append_adapter_properties` kopiert einen bestehenden Kandidaten unter einen neuen Namen, bewahrt alle vorhandenen Entities und hängt Standardentities je Eigenschaft an. Vorhandene Eigenschaften gleichen Namens werden nicht still überschrieben. JSON wird bei Bedarf in nummerierte Textstücke von maximal 4000 ASCII-Zeichen zerlegt. Ein einzelner großer JSON-String führte beim geprüften OCCT-7.8.1-Leser zu `input buffer overflow`; zusammengefügte kleine Stücke erhalten dieselben Daten.

```python
def read_adapter_properties(step_path, expected_schemas):
    import json, re
    records = sth_p21_parse(open(step_path, encoding='utf-8').read())
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
        data = json.loads(encoded, object_pairs_hook=unique_object)
        if not isinstance(data, dict) or data.get('schema') != schema:
            raise ValueError('Unsupported adapter schema for ' + name)
        output[name] = data
    return output


def append_adapter_properties(source_path, output_path, properties):
    import os, json, hashlib
    if os.path.normcase(os.path.abspath(source_path)) == os.path.normcase(os.path.abspath(output_path)):
        raise ValueError('Candidate must have a separate output path')
    text = open(source_path, encoding='utf-8', newline='').read()
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
    with open(output_path, 'w', encoding='utf-8', newline='') as out:
        out.write(candidate)
    decoded = read_adapter_properties(output_path, schemas)
    if decoded != properties:
        raise ValueError('Adapter metadata round-trip failed')
    return {'source_sha256': hashlib.sha256(text.encode('utf-8')).hexdigest(),
            'output_sha256': hashlib.sha256(candidate.encode('utf-8')).hexdigest(),
            'preserved_entities': len(records), 'added_entities': len(new_records),
            'schemas': schemas, 'exact_metadata_roundtrip': True}
```

Die beiden vorgesehenen Schlüssel sind `drawing2cad.editable_ui.v1` mit Schema `drawing2cad.editable-ui/1` und `drawing2cad.review_annotations.v1` mit Schema `drawing2cad.review-annotations/1`. Ihre jeweiligen Renderer müssen Payload, Referenzen, Einheiten, Feature-IDs und Geometrieanker validieren; niemals eingebetteten Code ausführen. Nach einer Änderung werden betroffene PMI und Reviewanker erneut geprüft. Ein Hash oder eine erfolgreiche JSON-Rücklesung allein beweist keine geometrisch richtige Markierung.
