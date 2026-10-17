# Inline readers: adapter components

> Historical adapter reference. The current MCP has no FreeCAD proxy.
> The calls below are unavailable and are not current instructions.
> Code and recorded hashes are retained for provenance and maintained reader origins.
> Use [the current workflow](managed-workflow.md) for supported MCP operations.
> Earlier drawing-first statements below do not apply to the current workflow.


## Historical record

The following adapter procedure is retained as historical evidence. It is not a current execution path.


These code blocks document inline calls through the FreeCAD proxy of `drawing2cad-mcp`. Do not create script files from them. Define the functions in a fresh Python process. Supply the path, expected representation, and expected PMI count explicitly.

The blocks read STEP and create declarative data. They do not create CAD documents. Use the skill for the native rebuild and its geometric verification.

The execution environment must provide compatible OCC bindings. Record their versions in the run manifest. Test these blocks in a new process with the current adapter inputs. This reference contains no part data or case evidence. Do not use MCP variables left from earlier calls.

## CSG to neutral records

The reader supports exactly one named CSG representation with one root. It supports Boolean wrappers and planar extrusions from a polygon or closed circle. It rejects other constructions.

Solid nodes are returned in dependency order. CSG wrappers are not additional native features. Polygon points are already in representation coordinates. Normalized output lengths are in mm.

The function examines basic structure, units, and profiles. Separate checks must examine self-intersection, full EXPRESS conformity, and geometry equivalence. This function alone does not verify them.

```python
def read_step_csg(path, representation_name):
    import math, hashlib
    from OCC.Core.STEPControl import STEPControl_Reader
    from OCC.Core.IFSelect import IFSelect_RetDone
    from OCC.Core.StepShape import StepShape_CsgShapeRepresentation, StepShape_CsgSolid, StepShape_BooleanResult, StepShape_ExtrudedFaceSolid, StepShape_FaceSurface, StepShape_PolyLoop, StepShape_EdgeLoop, StepShape_EdgeCurve
    from OCC.Core.StepGeom import StepGeom_CartesianPoint, StepGeom_Plane, StepGeom_Circle, StepGeom_GeomRepContextAndGlobUnitAssCtxAndGlobUncertaintyAssCtx, StepGeom_GeometricRepresentationContextAndGlobalUnitAssignedContext
    from OCC.Core.STEPConstruct import STEPConstruct_UnitContext
    from OCC.Core.StepData import StepData_Factors
    r = STEPControl_Reader()
    if r.ReadFile(path) != IFSelect_RetDone:
        raise ValueError("STEP parser failed")
    m = r.StepModel()
    reps = []
    for i in range(1, m.NbEntities()+1):
        e = m.Value(i)
        if e.IsKind("StepShape_CsgShapeRepresentation"):
            rep = StepShape_CsgShapeRepresentation.DownCast(e)
            if rep.Name().ToCString() == representation_name:
                reps.append(rep)
    if len(reps) != 1:
        raise ValueError("Expected exactly one named CSG representation")
    rep = reps[0]
    ctx = rep.ContextOfItems()
    if ctx.IsKind("StepGeom_GeomRepContextAndGlobUnitAssCtxAndGlobUncertaintyAssCtx"):
        uc = StepGeom_GeomRepContextAndGlobUnitAssCtxAndGlobUncertaintyAssCtx.DownCast(ctx).GlobalUnitAssignedContext()
    elif ctx.IsKind("StepGeom_GeometricRepresentationContextAndGlobalUnitAssignedContext"):
        uc = StepGeom_GeometricRepresentationContextAndGlobalUnitAssignedContext.DownCast(ctx).GlobalUnitAssignedContext()
    else:
        raise ValueError("Unsupported CSG unit context")
    units = STEPConstruct_UnitContext()
    if units.ComputeFactors(uc, StepData_Factors()) != 0 or not units.LengthDone():
        raise ValueError("Could not resolve STEP length unit")
    scale = units.LengthFactor()
    if not math.isfinite(scale) or scale <= 0:
        raise ValueError("Invalid STEP length factor")
    def eid(e):
        return "#" + str(m.IdentLabel(e))
    def named(e):
        h = e.Name()
        return h.ToCString() if h else ""
    def point(e):
        p = StepGeom_CartesianPoint.DownCast(e)
        if p is None or p.NbCoordinates() != 3:
            raise ValueError("Expected 3D Cartesian point")
        out = [float(p.CoordinatesValue(i))*scale for i in (1,2,3)]
        if not all(math.isfinite(v) for v in out):
            raise ValueError("Nonfinite coordinates")
        return out
    def unit(values):
        n = math.sqrt(sum(v*v for v in values))
        if not math.isfinite(n) or n <= 1e-15:
            raise ValueError("Invalid direction")
        return [v/n for v in values]
    def direction(e):
        if e.NbDirectionRatios() != 3:
            raise ValueError("Expected 3D direction")
        return unit([float(e.DirectionRatiosValue(i)) for i in (1,2,3)])
    def dot(a,b):
        return sum(x*y for x,y in zip(a,b))
    def sub(a,b):
        return [x-y for x,y in zip(a,b)]
    def placement(p):
        origin = point(p.Location())
        normal = direction(p.Axis()) if p.HasAxis() else [0.,0.,1.]
        refx = direction(p.RefDirection()) if p.HasRefDirection() else [1.,0.,0.]
        return origin,normal,refx
    nodes, memo, active, wrappers = [], {}, set(), {}
    def walk(e):
        if e is None:
            raise ValueError("Unresolved CSG operand")
        key = eid(e)
        if key in memo:
            return memo[key]
        if key in active:
            raise ValueError("Cyclic CSG graph at " + key)
        active.add(key)
        if e.IsKind("StepShape_CsgSolid"):
            cs = StepShape_CsgSolid.DownCast(e)
            br = cs.TreeRootExpression().BooleanResult()
            if br is None:
                raise ValueError("Unsupported CSG primitive root at " + key)
            result = walk(br)
            wrappers[key] = result
            memo[key] = result
            active.remove(key)
            return result
        if e.IsKind("StepShape_BooleanResult"):
            b = StepShape_BooleanResult.DownCast(e)
            ops = {0:"difference",1:"intersection",2:"union"}
            op = ops.get(int(b.Operator()))
            if op is None:
                raise ValueError("Unknown Boolean operator")
            left = b.FirstOperand().SolidModel()
            right = b.SecondOperand().SolidModel()
            rec = {"id":key,"name":named(b),"type":"boolean","operation":op,"base":walk(left),"tool":walk(right)}
        elif e.IsKind("StepShape_ExtrudedFaceSolid"):
            ex = StepShape_ExtrudedFaceSolid.DownCast(e)
            face = StepShape_FaceSurface.DownCast(ex.SweptFace())
            if face is None or face.NbBounds() != 1:
                raise ValueError("Expected single-bound planar extrusion")
            surf = face.FaceGeometry()
            if not surf.IsKind("StepGeom_Plane"):
                raise ValueError("Nonplanar swept face")
            plane = StepGeom_Plane.DownCast(surf)
            origin,normal,refx = placement(plane.Position())
            bound = face.BoundsValue(1)
            loop = bound.Bound()
            axis = direction(ex.ExtrudedDirection())
            depth = float(ex.Depth())*scale
            if not math.isfinite(depth) or depth <= 0:
                raise ValueError("Invalid extrusion depth")
            rec = {"id":key,"name":named(ex),"axis":axis,"depth":depth,
                   "normal":normal,"plane_origin":origin,
                   "bound_orientation":bool(bound.Orientation()),"face_same_sense":bool(face.SameSense()),
                   "profile_id":eid(loop)}
            if loop.IsKind("StepShape_PolyLoop"):
                poly = StepShape_PolyLoop.DownCast(loop)
                pts = [point(poly.PolygonValue(i)) for i in range(1,poly.NbPolygon()+1)]
                if len(pts)>1 and sum(v*v for v in sub(pts[0],pts[-1])) < 1e-20:
                    pts.pop()
                if len(pts)<3 or any(abs(dot(sub(p,origin),normal))>1e-7 for p in pts):
                    raise ValueError("Degenerate or nonplanar polygon")
                rec.update(type="polygon_extrusion",points=pts)
            elif loop.IsKind("StepShape_EdgeLoop"):
                el = StepShape_EdgeLoop.DownCast(loop)
                if el.NbEdgeList()!=1:
                    raise ValueError("Only full-circle edge loops supported")
                oe = el.EdgeListValue(1)
                edge = StepShape_EdgeCurve.DownCast(oe.EdgeElement())
                if edge is None or m.Number(edge.EdgeStart()) != m.Number(edge.EdgeEnd()):
                    raise ValueError("Circle profile must be closed")
                geo = edge.EdgeGeometry()
                if not geo.IsKind("StepGeom_Circle"):
                    raise ValueError("Unsupported edge-loop profile")
                ci = StepGeom_Circle.DownCast(geo)
                cp = ci.Position().Axis2Placement3d()
                if cp is None:
                    raise ValueError("Expected 3D circle placement")
                center,cnormal,crefx = placement(cp)
                radius = float(ci.Radius())*scale
                if radius<=0 or not math.isfinite(radius):
                    raise ValueError("Invalid circle radius")
                if abs(abs(dot(cnormal,axis))-1)>1e-10 or abs(abs(dot(cnormal,normal))-1)>1e-10 or abs(dot(sub(center,origin),normal))>1e-7:
                    raise ValueError("Oblique or misplaced circular extrusion is not a cylinder")
                rec.update(type="cylinder",center=center,radius=radius,ref_direction=crefx,circle_id=eid(ci))
            else:
                raise ValueError("Unsupported profile at " + eid(loop))
        else:
            raise ValueError("Unsupported solid type " + e.DynamicType().Name())
        nodes.append(rec)
        memo[key] = key
        active.remove(key)
        return key
    roots=[]
    for i in range(1,rep.NbItems()+1):
        item=rep.ItemsValue(i)
        if item.IsKind("StepShape_CsgSolid") or item.IsKind("StepShape_ExtrudedFaceSolid") or item.IsKind("StepShape_BooleanResult"):
            roots.append(walk(item))
    if len(roots)!=1:
        raise ValueError("Expected exactly one CSG solid root")
    with open(path,"rb") as stream:
        source_sha256=hashlib.sha256(stream.read()).hexdigest()
    return {"source":path,"source_sha256":source_sha256,"representation":named(rep),
            "representation_id":eid(rep),"root":roots[0],"units_to_mm":scale,
            "nodes":nodes,"wrapper_to_node":wrappers}
```

In the same fresh process, call `tree = read_step_csg(master_path, representation_name)`. The result contains `nodes`, `root`, `units_to_mm`, `source_sha256`, and wrapper mappings.

Build the native model as follows:

- For `cylinder`, create an editable cylinder with center, axis, radius, and depth.
- For `polygon_extrusion`, create an editable closed profile and extrusion. For rectangles, examine orthogonality and corner points before using native boxes.
- For `boolean`, create a union, ordered difference, or intersection. Link `base` and `tool` through node IDs.
- Apply `profile_id`, `normal`, `bound_orientation`, and `face_same_sense`, and do a check of the result. Do not silently reinterpret an unsupported orientation.
- Identify native objects with a stable logical ID and the imported STEP reference. Recompute after construction and after an edit test.

## PMI values, associations, and polylines

The reader implements nominal size, distance, and angle dimensions within the profile below. Each dimension has `source_id`, one associated draughting callout, and tessellated polylines. Verify these functions with permitted inputs before release.

Do not claim a general GD&T, datum, or tolerance implementation. If a contract requires these features, extend the implementation and verify them.

Lexical processing is necessary because some tessellation arrays appear only as opaque pointers in the tested SWIG binding. The adapter tokenizes STEP content. It never evaluates that content as a program.

The adapter is intended for the controlled export profile. It does not support every representation permitted by the standard. During the contract comparison, retain checks for additional PMI outside this profile. Do not silently omit these PMI.

```python
def read_step_pmi(path, expected_count=None):
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
            if t.startswith("'"): return t[1:-1].replace("''", "'")
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
            'source':metadata.get('source',''),'semantic_entity':dim_id,
            'representation_entity':repr_id,'dimension_relation_entity':dcr_id,
            'shape_aspects':source_refs,'source_aspect_entities':all_aspects,
            'geometric_item_entities':source_items}
    if set(measure_map) != dimension_inventory: raise ValueError('Dimension without supported characteristic representation')
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
    return output
```

Call `pmi = read_step_pmi(master_path, expected_count=contract_pmi_count)`. Then compare the expected ID sets, semantics, and target references with the contract. Examine all polylines in their planes and display them graphically. `expected_count=None` permits a variable count. It does not replace a completeness check.

For native display, rebuild each nondegenerate point sequence with `Part.makePolygon`. Combine the sequences for each PMI in a compound. Link the metadata separately to this display object. Group displays by annotation plane.

The authoritative semantics remain in AP242. A native text or shape display alone is not a semantic re-export.
