"""Read the documented nominal PMI profile with bounded Part 21 parsing."""

import re
from .p21 import (P21Ref, P21Enum, P21Typed, P21Derived, P21Binary,
                  sth_p21_parse, sth_p21_validate_refs)


def decode_step_string(value):
    value=re.sub(r'\\X2\\([0-9A-Fa-f]+)\\X0\\', lambda m:bytes.fromhex(m[1]).decode('utf-16-be'), value)
    return re.sub(r'\\X4\\([0-9A-Fa-f]+)\\X0\\', lambda m:bytes.fromhex(m[1]).decode('utf-32-be'), value)

def read_step_pmi_extended(text, expected_count=None, records_input=None):
    import re, math
    if records_input is None: records_input = sth_p21_parse(text)
    sth_p21_validate_refs(records_input)
    def convert(value):
        if isinstance(value, P21Ref): return {'ref': int(value)}
        if isinstance(value, P21Enum): return '.' + value + '.'
        if isinstance(value, P21Typed): return {'type':value.name, 'args':convert(value.args)}
        if isinstance(value, P21Derived): return {'derived':True}
        if isinstance(value, P21Binary): raise ValueError('Binary PMI values unsupported')
        if isinstance(value, list): return [convert(x) for x in value]
        if isinstance(value, str): return decode_step_string(value)
        return value
    entities={n:convert(a) if t=='__COMPLEX__' else {'type':t,'args':convert(a)} for n,(t,a) in records_input.items()}
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
        if record(unit_ref,'LENGTH_UNIT') is None or si is None or si['args'][-1] != '.METRE.': raise ValueError('Length unit unsupported')
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
        dim = record(dim_id); da=dim['args']; dt=dim['type']
        angular=dt in ('ANGULAR_SIZE','ANGULAR_LOCATION')
        allowed={'PLANE_ANGLE_MEASURE','POSITIVE_PLANE_ANGLE_MEASURE'} if angular else {'LENGTH_MEASURE','POSITIVE_LENGTH_MEASURE'}
        if kind not in allowed:
            raise ValueError('Measure type does not match dimension family: '+kind+' for '+dt)
        if type(val) not in (int,float) or not math.isfinite(val) or (kind.startswith('POSITIVE_') and val<=0):
            raise ValueError('Invalid nominal measure value')
        if angular:
            unit_name='deg'; val=round(math.degrees(val),10)
            si = record(unit_ref,'SI_UNIT')
            if (record(unit_ref,'PLANE_ANGLE_UNIT') is None or si is None or
                    si['args'][-1]!='.RADIAN.' or si['args'][0] is not None):
                raise ValueError('Angle unit unsupported')
        else:
            val=val*length_scale(unit_ref); unit_name='mm'
        if not math.isfinite(val): raise ValueError('Nonfinite nominal value')
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
            if measure[0] not in {'LENGTH_MEASURE','POSITIVE_LENGTH_MEASURE'} or type(measure[1]) not in (int,float) or not math.isfinite(measure[1]) or measure[1]<=0:raise ValueError('Invalid general radius value')
        else:raise ValueError('Unsupported semantic note '+source_id)
        source_refs=[rid(pd['args'][2])]
        if source_refs[0] not in aspects:raise ValueError('Property lacks shape aspect')
        all_aspects=sorted(set(x for n in source_refs for x in lineage(n)))
        source_items=sorted(set(item for n in all_aspects for item in usage.get(n,[])))
        if not source_items:raise ValueError('Property lacks geometric references')
        property_value=measure[1]*length_scale(unit_ref) if measure else None
        if property_value is not None and not math.isfinite(property_value):raise ValueError('Nonfinite property value')
        measure_map[pd_id]={'id':source_id,'source_id':source_id,'value':property_value,
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
