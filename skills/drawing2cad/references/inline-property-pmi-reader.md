# Inline reader: numeric PMI and semantic text properties

This is an optional FreeCAD development-adapter reference. It is not a dependency of the backend-neutral skill. Prefer the maintained tools in [managed-workflow.md](managed-workflow.md) when they cover the operation. Revalidate any remaining inline fallback before use.


This reader extends the nominal reader. It supports `PROPERTY_DEFINITION` for a thread designation and a general positive radius specification. It preserves STEP geometry references and all presentation polylines. Also compare expected IDs, values, types, references, and note meanings with the model contract. Other semantic properties, tolerances, and datum systems are not generally supported.

Execute the code only in memory through the FreeCAD proxy of `drawing2cad-mcp`. `read_step_pmi_extended(step_path, expected_count)` returns `annotations` and separate `metadata_properties`. The import requires only STEP. It does not require the original model contract or FCStd. Use the contract afterward for an independent check of expected results.

```python
def read_step_pmi_extended(path, expected_count=None):
    import re, math
    text = open(path, encoding='utf-8').read()
    statements, start, quoted, comment, i = [], 0, False, False, 0
    while i < len(text):
        if comment:
            if text.startswith('*/', i): comment = False; i += 2; continue
            i += 1; continue
        if quoted:
            if text[i] == "'":
                if i + 1 < len(text) and text[i + 1] == "'": i += 2; continue
                quoted = False
            i += 1; continue
        if text.startswith('/*', i): comment = True; i += 2; continue
        if text[i] == "'": quoted = True
        elif text[i] == ';': statements.append(text[start:i]); start = i + 1
        i += 1
    token_re = re.compile(r"\s+|/\*.*?\*/|'(?:[^']|'')*'|\#[0-9]+|\.[A-Z_][A-Z0-9_]*\.|[-+]?(?:[0-9]+\.[0-9]*|\.[0-9]+|[0-9]+)(?:[EDed][-+]?[0-9]+)?|[A-Z_][A-Z0-9_]*|[(),$*]", re.S)
    def parse(rhs):
        tokens, pos = [], 0
        for m in token_re.finditer(rhs):
            if rhs[pos:m.start()].strip(): raise ValueError('Unsupported STEP token: ' + rhs[pos:m.start()])
            token = m.group(0); pos = m.end()
            if token.isspace() or token.startswith('/*'): continue
            tokens.append(token)
        if rhs[pos:].strip(): raise ValueError('Unparsed STEP tail')
        cursor = 0
        def value():
            nonlocal cursor
            t = tokens[cursor]; cursor += 1
            if t == '(':
                values = []
                while tokens[cursor] != ')':
                    if tokens[cursor] == ',': cursor += 1; continue
                    values.append(value())
                cursor += 1
                return values
            if t.startswith("'"):
                value_s=t[1:-1].replace("''", "'")
                value_s=re.sub(r'\\X2\\([0-9A-Fa-f]+)\\X0\\',lambda m:bytes.fromhex(m.group(1)).decode('utf-16-be'),value_s)
                value_s=re.sub(r'\\X4\\([0-9A-Fa-f]+)\\X0\\',lambda m:bytes.fromhex(m.group(1)).decode('utf-32-be'),value_s)
                return value_s
            if t.startswith('#'): return {'ref': int(t[1:])}
            if t == '$': return None
            if t == '*': return {'derived': True}
            if t.startswith('.') and t.endswith('.') and t[1:2].isalpha(): return t
            if re.fullmatch(r'[A-Z_][A-Z0-9_]*', t):
                if cursor < len(tokens) and tokens[cursor] == '(':
                    return {'type': t, 'args': value()}
                return t
            return float(t.replace('D', 'E').replace('d', 'e')) if any(ch in t for ch in '.EDed') else int(t)
        result = value()
        if cursor != len(tokens): raise ValueError('Trailing STEP tokens')
        return result
    entities = {}
    for statement in statements:
        statement = statement.strip()
        m = re.match(r'^\s*(?:/\*.*?\*/\s*)*#([0-9]+)\s*=\s*(.*)$', statement, re.S)
        if m: entities[int(m.group(1))] = parse(m.group(2))
    def rid(v):
        if not isinstance(v, dict) or 'ref' not in v: raise ValueError('Expected STEP reference')
        return v['ref']
    def records(v):
        if isinstance(v, list): return [x for x in v if isinstance(x, dict) and 'type' in x]
        return [v] if isinstance(v, dict) and 'type' in v else []
    def record(n, kind=None):
        rs = records(entities[n])
        return next((r for r in rs if kind is None or r['type'] == kind), None)
    def args(n, kind=None):
        r = record(n, kind)
        if r is None: raise ValueError('Missing record '+str(kind)+' at #'+str(n))
        return r['args']
    def typed(kind):
        return [(n,r['args']) for n,v in entities.items() for r in records(v) if r['type']==kind]
    unsupported = {'GEOMETRIC_TOLERANCE','PLUS_MINUS_TOLERANCE','LIMITS_AND_FITS','DATUM','DATUM_REFERENCE','TOLERANCE_ZONE'}
    present_types = {r['type'] for e in entities.values() for r in records(e)}
    if present_types & unsupported or any('TOLERANCE' in t or t.startswith('DATUM') for t in present_types): raise ValueError('PMI profile does not support tolerance/datum entities')
    supported_dimensions = {'DIMENSIONAL_SIZE','ANGULAR_SIZE','DIMENSIONAL_LOCATION','ANGULAR_LOCATION'}
    dimension_families = {t for t in present_types if t.startswith(('DIMENSIONAL_SIZE','DIMENSIONAL_LOCATION','ANGULAR_SIZE','ANGULAR_LOCATION'))}
    if dimension_families - supported_dimensions: raise ValueError('Unsupported dimensional entity family')
    dimension_inventory = {n for n,e in entities.items() for r in records(e) if r['type'] in supported_dimensions}
    def length_scale(unit_ref):
        si = record(unit_ref, 'SI_UNIT')
        if si is None or si['args'][-1] != '.METRE.': raise ValueError('Length unit unsupported')
        prefixes = {None:1000., '.MILLI.':1., '.CENTI.':10., '.MICRO.':0.001}
        if si['args'][0] not in prefixes: raise ValueError('Length prefix unsupported')
        return prefixes[si['args'][0]]
    def graphic_scale(rep_id):
        context_id = rid(args(rep_id, 'DRAUGHTING_MODEL')[2])
        unit_ids = [rid(u) for u in args(context_id, 'GLOBAL_UNIT_ASSIGNED_CONTEXT')[0]]
        length_ids = [u for u in unit_ids if record(u, 'LENGTH_UNIT') is not None]
        if len(length_ids) != 1: raise ValueError('Ambiguous graphical length unit')
        return length_scale(length_ids[0])
    aspects, descendants, usage = {}, {}, {}
    for n,v in entities.items():
        for r in records(v):
            a = r['args']; t = r['type']
            if t in ('SHAPE_ASPECT','DERIVED_SHAPE_ASPECT','COMPOSITE_SHAPE_ASPECT','DATUM_FEATURE'):
                aspects[n] = a[0] if a else ''
            if 'SHAPE_ASPECT' in t and 'RELATIONSHIP' in t and len(a) >= 4:
                descendants.setdefault(rid(a[-2]), []).append(rid(a[-1]))
            if t == 'GEOMETRIC_ITEM_SPECIFIC_USAGE':
                target = rid(a[2]); items = a[4] if isinstance(a[4],list) else [a[4]]
                usage.setdefault(target,[]).extend(rid(x) for x in items)
    def lineage(n, visited=None):
        visited = set() if visited is None else visited
        if n in visited: return []
        visited.add(n); found = [n]
        for child in descendants.get(n,[]): found.extend(lineage(child,visited))
        return found
    planes = {}
    for n,a in typed('ANNOTATION_PLANE'):
        origin_ref, normal_ref, x_ref = args(rid(args(rid(a[2]),'PLANE')[1]),'AXIS2_PLACEMENT_3D')[1:4]
        plane = {'entity':n, 'origin':args(rid(origin_ref),'CARTESIAN_POINT')[1],
                 'normal':args(rid(normal_ref),'DIRECTION')[1] if normal_ref else [0.,0.,1.],
                 'x_axis':args(rid(x_ref),'DIRECTION')[1] if x_ref else [1.,0.,0.]}
        for callout in a[3]: planes[rid(callout)] = plane
    measure_map = {}
    for dcr_id,a in typed('DIMENSIONAL_CHARACTERISTIC_REPRESENTATION'):
        dim_id, repr_id = rid(a[0]), rid(a[1])
        ra = args(repr_id,'SHAPE_DIMENSION_REPRESENTATION')
        metadata, measure, unit_ref = {}, None, None
        for item in ra[1]:
            item_id = rid(item)
            for r in records(entities[item_id]):
                if r['type']=='DESCRIPTIVE_REPRESENTATION_ITEM': metadata[r['args'][0]]=r['args'][1]
                if r['type']=='MEASURE_WITH_UNIT':
                    if measure is not None: raise ValueError('Multiple measures cannot be collapsed to a nominal')
                    m,unit = r['args']; measure=(m['type'],m['args'][0]); unit_ref=rid(unit)
        if 'source_id' not in metadata or measure is None: raise ValueError('Dimension lacks source_id or measure')
        if dim_id in measure_map: raise ValueError('Multiple representations for one dimension')
        kind,val=measure
        if 'ANGLE' in kind:
            unit_name='deg'; val=round(math.degrees(val),10)
            si = record(unit_ref,'SI_UNIT')
            if si is None or si['args'][-1]!='.RADIAN.' or si['args'][0] is not None: raise ValueError('Angle unit unsupported')
        else:
            val=val*length_scale(unit_ref); unit_name='mm'
        if not math.isfinite(val): raise ValueError('Nonfinite nominal value')
        dim = record(dim_id); da=dim['args']; dt=dim['type']
        if dt in ('DIMENSIONAL_SIZE','ANGULAR_SIZE'): source_refs=[rid(da[0])]
        elif dt in ('DIMENSIONAL_LOCATION','ANGULAR_LOCATION'): source_refs=[rid(da[2]),rid(da[3])]
        else: raise ValueError('Dimension type unsupported: '+dt)
        all_aspects=sorted(set(x for n in source_refs for x in lineage(n)))
        titles=[aspects[n] for n in all_aspects if n in aspects and aspects[n].startswith(metadata['source_id']+' ')]
        title=titles[0][len(metadata['source_id'])+1:] if titles else metadata['source_id']
        source_items=sorted(set(item for n in all_aspects for item in usage.get(n,[])))
        if not source_items: raise ValueError('Dimension lacks geometric references')
        measure_map[dim_id]={'id':metadata['source_id'],'source_id':metadata['source_id'],
            'value':val,'unit':unit_name,'title':title,'type':dt,
            'dimension_kind':da[1] if dt=='DIMENSIONAL_SIZE' else da[0],
            'literal':metadata.get('drawing_literal',''),'meaning':metadata.get('meaning',''),
            'source':metadata.get('source',''),'semantic_entity':dim_id,
            'representation_entity':repr_id,'dimension_relation_entity':dcr_id,
            'shape_aspects':source_refs,'source_aspect_entities':all_aspects,
            'geometric_item_entities':source_items}
    if set(measure_map) != dimension_inventory: raise ValueError('Dimension without supported characteristic representation')

    extra_metadata=[]
    for pdr_id,pa in typed('PROPERTY_DEFINITION_REPRESENTATION'):
        pd_id,rep_id=rid(pa[0]),rid(pa[1])
        pd=record(pd_id,'PROPERTY_DEFINITION')
        if pd is None: continue
        rep=record(rep_id,'REPRESENTATION')
        if rep is None: continue
        metadata={};measure=None;unit_ref=None
        for item in rep['args'][1]:
            for r in records(entities[rid(item)]):
                if r['type']=='DESCRIPTIVE_REPRESENTATION_ITEM':metadata[r['args'][0]]=r['args'][1]
                if r['type']=='MEASURE_WITH_UNIT':
                    if measure is not None:raise ValueError('Multiple property measures')
                    m,unit=r['args'];measure=(m['type'],m['args'][0]);unit_ref=rid(unit)
        if 'source_id' not in metadata:
            if 'metadata_id' in metadata:extra_metadata.append({'semantic_entity':pd_id,'metadata':metadata})
            continue
        source_id=metadata['source_id']
        if 'thread designation' in metadata:
            property_kind='thread designation'
            if not metadata['thread designation'] or metadata.get('drawing_literal')!=metadata['thread designation']:raise ValueError('Thread designation mismatch')
            if measure is not None:raise ValueError('Thread designation must not be disguised as numeric diameter')
        elif measure is not None:
            property_kind='general radius'
            if 'LENGTH' not in measure[0] or not math.isfinite(measure[1]) or measure[1]<=0:raise ValueError('Invalid general radius value')
        else:raise ValueError('Unsupported semantic note '+source_id)
        source_refs=[rid(pd['args'][2])]
        if source_refs[0] not in aspects:raise ValueError('Property lacks shape aspect')
        all_aspects=sorted(set(x for n in source_refs for x in lineage(n)))
        source_items=sorted(set(item for n in all_aspects for item in usage.get(n,[])))
        if not source_items:raise ValueError('Property lacks geometric references')
        measure_map[pd_id]={'id':source_id,'source_id':source_id,'value':measure[1]*length_scale(unit_ref) if measure else None,
            'unit':'mm' if measure else None,'literal':metadata.get('drawing_literal',''),'title':metadata.get('meaning',metadata.get('drawing_literal','')),
            'meaning':metadata.get('meaning',''),'type':'PROPERTY_DEFINITION','dimension_kind':property_kind,
            'source':metadata.get('source',''),'semantic_entity':pd_id,'representation_entity':rep_id,'dimension_relation_entity':pdr_id,
            'shape_aspects':source_refs,'source_aspect_entities':all_aspects,'geometric_item_entities':source_items,'metadata':metadata}

    output=[]
    for assoc_id,a in typed('DRAUGHTING_MODEL_ITEM_ASSOCIATION'):
        dim_id=rid(a[2])
        if dim_id not in measure_map: raise ValueError('Association targets unsupported semantic entity')
        callouts=a[4] if isinstance(a[4],list) else [a[4]]
        if len(callouts)!=1: raise ValueError('Expected exactly one callout per dimension')
        call_id=rid(callouts[0]); ca=args(call_id,'DRAUGHTING_CALLOUT')
        item=dict(measure_map[dim_id]); item['association_entity']=assoc_id
        item['annotation_entity']=call_id; item['annotation_name']=ca[0]
        if not ca[0].startswith(item['id']+'_'): raise ValueError('Mismatched semantic/presentation source_id')
        item['plane']=dict(planes[call_id]); item['plane']['name']=ca[0].split('_',1)[1]
        scale = graphic_scale(rid(a[3]))
        item['plane']['origin'] = [v * scale for v in item['plane']['origin']]
        polylines=[]; tessellation_entities=[]
        for occurrence in ca[1]:
            oa=args(rid(occurrence),'TESSELLATED_ANNOTATION_OCCURRENCE')
            for geom in args(rid(oa[2]),'TESSELLATED_GEOMETRIC_SET')[1]:
                curve_id=rid(geom); ga=args(curve_id,'TESSELLATED_CURVE_SET')
                coordinates=args(rid(ga[1]),'COORDINATES_LIST')
                if coordinates[1]!=len(coordinates[2]): raise ValueError('Coordinate count mismatch')
                for indices in ga[2]:
                    if len(indices)<2 or any(j<1 or j>len(coordinates[2]) for j in indices): raise ValueError('Bad polyline indices')
                    line=[[v * scale for v in coordinates[2][j-1]] for j in indices]
                    if any(len(p)!=3 or not all(math.isfinite(c) for c in p) for p in line): raise ValueError('Invalid point')
                    polylines.append(line)
                tessellation_entities.append(curve_id)
        if not polylines: raise ValueError('Empty PMI presentation')
        item['polylines']=polylines; item['tessellation_entities']=tessellation_entities
        output.append(item)
    if set(x['semantic_entity'] for x in output) != set(measure_map): raise ValueError('Dimension lacks graphical association')
    output.sort(key=lambda x:x['id'])
    if len(set(x['id'] for x in output)) != len(output): raise ValueError('Duplicate PMI source_id')
    if expected_count is not None and len(output) != expected_count: raise ValueError('Unexpected PMI count')
    return {'annotations':output,'metadata_properties':extra_metadata}
```

## Native annotation data and optional desktop display

This component transfers STEP polylines and semantic records into a document rebuilt from STEP.
View groups use the plane names stored in the STEP annotations.
Supply optional readable labels through `plane_labels`; the skill contains no part-specific view mapping.
The caller supplies `root_name` from the decoded operation graph.

`add_step_pmi_to_native` does not import `FreeCADGui` when `GuiUp=0`.
Its headless path stores semantic data and graphical geometry in the document.
This path does not prove visible text, a rendered drawing, or a server preview.
The server must verify those outputs through a separate headless render path.

`show_step_pmi_view` is an optional desktop helper.
Supply any additional visible plane keys explicitly.
Do not use this helper as a dependency of the headless server.
Native PMI are imported nominal data. They are not sketch constraints that update automatically.

These functions changed to remove case-specific mappings and GUI dependencies from data creation.
Revalidate both paths with the current permitted inputs. No live CAD test was run during this cleanup.

```python
def add_step_pmi_to_native(doc, data, source_path, root_name, plane_labels=None):
 import FreeCAD as App, Part, json, hashlib
 root=doc.getObject(root_name)
 if root is None: raise ValueError('Missing native model root')
 plane_labels={} if plane_labels is None else dict(plane_labels)
 keys=sorted({item['plane']['name'] for item in data['annotations']})
 if any(not isinstance(key,str) or not key for key in keys):
  raise ValueError('Each annotation requires a nonempty plane name')
 if set(plane_labels)-set(keys): raise ValueError('Unknown plane label key')
 if App.GuiUp:
  for obj in doc.Objects:
   if obj.ViewObject: obj.ViewObject.Visibility=False
  root.ViewObject.Visibility=True
  root.ViewObject.ShapeColor=(0.82,0.84,0.87)
  root.ViewObject.LineColor=(0.12,0.16,0.20)
 semantic=doc.addObject('App::DocumentObjectGroup','PMISemantics')
 semantic.Label='PMI - '+str(len(data['annotations']))+' STEP annotations'
 groups={}
 for index,key in enumerate(keys,1):
  group=doc.addObject('App::DocumentObjectGroup','PMIView_%03d'%index)
  group.Label='PMI - '+plane_labels.get(key,key)
  groups[key]=group
 for item in data['annotations']:
  obj=doc.addObject('App::FeaturePython','PMISemantic_'+item['id'])
  obj.Label=item['id']+' - '+item['literal']
  fields={'DrawingText':item['literal'],
          'SemanticType':item['dimension_kind'] or item['type'],
          'NominalValue':str(item['value'])+' '+str(item['unit']) if item['value'] is not None else 'Text property',
          'Meaning':item['meaning'],
          'StepEntity':'#'+str(item['semantic_entity']),
          'StepGeometryReferences':json.dumps(item['geometric_item_entities']),
          'Status':'Imported STEP nominal state. Validate PMI before release and after geometry changes.'}
  for prop,value in fields.items():
   obj.addProperty('App::PropertyString',prop,'PMI');setattr(obj,prop,value)
  obj.addProperty('App::PropertyLink','Model','PMI');obj.Model=root
  obj.addProperty('App::PropertyString','StepRecord','PMI')
  obj.StepRecord=json.dumps({key:value for key,value in item.items() if key!='polylines'},ensure_ascii=False)
  semantic.addObject(obj)
  lines=[]
  for rawline in item['polylines']:
   points=[]
   for xyz in rawline:
    point=App.Vector(*xyz)
    if not points or (points[-1]-point).Length>1e-9: points.append(point)
   if len(points)>1: lines.append(Part.makePolygon(points))
  if not lines: raise ValueError('Empty graphical PMI: '+item['id'])
  graphic=doc.addObject('Part::Feature','PMIGraphic_'+item['id'])
  graphic.Label=obj.Label;graphic.Shape=Part.makeCompound(lines)
  graphic.addProperty('App::PropertyLink','SemanticRecord','PMI');graphic.SemanticRecord=obj
  if App.GuiUp:
   graphic.ViewObject.LineColor=(0.05,0.65,0.95)
   graphic.ViewObject.PointColor=(0.05,0.65,0.95)
   graphic.ViewObject.LineWidth=1.5
  groups[item['plane']['name']].addObject(graphic)
 provenance=doc.addObject('App::FeaturePython','AP242Source')
 with open(source_path,'rb') as stream: source_hash=hashlib.sha256(stream.read()).hexdigest()
 fields={'SourceFile':source_path,'SHA256':source_hash,
         'Metadata':json.dumps(data['metadata_properties'],ensure_ascii=False),
         'Note':'Imported AP242 data. Use a verified adapter to preserve construction and PMI during export.'}
 for prop,value in fields.items():
  provenance.addProperty('App::PropertyString',prop,'AP242');setattr(provenance,prop,value)
 root.touch();doc.recompute()
 if App.GuiUp:
  import FreeCADGui as Gui
  Gui.updateGui()
 return groups

def show_step_pmi_view(doc,data,groups,key,additional_keys=()):
 import FreeCAD as App
 if not App.GuiUp: raise RuntimeError('GUI_UNAVAILABLE')
 import FreeCADGui as Gui
 visible_keys={key,*additional_keys}
 if not visible_keys.issubset(groups): raise ValueError('Unknown PMI plane key')
 for name,group in groups.items():
  visible=name in visible_keys
  group.ViewObject.Visibility=visible
  for obj in group.Group: obj.ViewObject.Visibility=visible
 item=next(item for item in data['annotations'] if item['plane']['name']==key)
 z=App.Vector(*item['plane']['normal']);x=App.Vector(*item['plane']['x_axis']);y=z.cross(x)
 rotation=App.Rotation(x,y,z,'ZXY')
 gui_doc=Gui.getDocument(doc.Name)
 gui_doc.activeView().setCameraType('Orthographic')
 gui_doc.activeView().setCameraOrientation(rotation.Q)
 gui_doc.activeView().fitAll()
 Gui.Selection.clearSelection()
```
