"""Decode the documented procedural subset without a CAD kernel."""

import hashlib
import math
import re
from .p21 import P21Ref, P21Enum, P21Typed, sth_p21_parse, sth_p21_validate_refs, sth_p21_refs

def sth_entity_closure(records,roots):
    todo=list(roots);seen=set()
    while todo:
        i=int(todo.pop())
        if i in seen:continue
        if i not in records:raise ValueError('Missing STEP #'+str(i))
        seen.add(i);todo.extend(sth_p21_refs(records[i][1]))
    return seen

def decode_procedural(text, records=None):
    if records is None: records=sth_p21_parse(text)
    sth_p21_validate_refs(records)
    def get(ref,kind=None):
        if not isinstance(ref,P21Ref):raise ValueError('Reference expected')
        t,a=records[int(ref)]
        if kind and t!=kind:raise ValueError('Expected '+kind+', got '+t)
        return a
    def scalar(v):
        if isinstance(v, (bool, P21Ref)) or not isinstance(v, (int, float)) or not math.isfinite(v):
            raise ValueError('Expected finite numeric scalar')
        return float(v)
    def references(values):
        if not isinstance(values,list) or not all(isinstance(v,P21Ref) for v in values):
            raise ValueError('Expected entity reference list')
        return values
    def truth(v):return isinstance(v,P21Enum) and str(v)=='T'
    def xyz(ref,typ):
        a=get(ref,typ);v=a[1]
        if len(v)!=3 or not all(isinstance(x,(int,float)) and not isinstance(x,P21Ref) and math.isfinite(x) for x in v):raise ValueError('Invalid vector')
        return [float(x) for x in v]
    def same(a,b,tol=1e-8):return len(a)==len(b) and max([abs(x-y) for x,y in zip(a,b)]+[0])<=tol
    def placement(ref):
        a=get(ref,'AXIS2_PLACEMENT_3D')
        return xyz(a[1],'CARTESIAN_POINT'),xyz(a[2],'DIRECTION'),xyz(a[3],'DIRECTION')
    reps=[i for i,(t,a) in records.items() if t=='PROCEDURAL_SHAPE_REPRESENTATION']
    if len(reps)!=1:raise ValueError('Exactly one procedural construction required')
    pa=records[reps[0]][1]
    if len(pa[1])!=1:raise ValueError('One construction sequence required')
    sa=get(pa[1][0],'PROCEDURAL_SHAPE_REPRESENTATION_SEQUENCE')
    sequence=references(sa[1])
    if sa[2] or not sequence or len(set(map(int,sequence)))!=len(sequence):raise ValueError('Suppressed/duplicate/empty sequence unsupported')
    links=[a for t,a in records.values() if t=='EXPLICIT_PROCEDURAL_SHAPE_REPRESENTATION_RELATIONSHIP' and a[2]==P21Ref(reps[0])]
    if len(links)!=1:raise ValueError('One evaluated-shape relationship required')
    mainrep=get(links[0][3],'ADVANCED_BREP_SHAPE_REPRESENTATION')
    if mainrep[2]!=pa[2]:raise ValueError('Representation contexts differ')
    # This implementation supports millimetre contexts only and fails closed otherwise.
    context_ids=sth_entity_closure(records,[int(pa[2])])
    millimetres=False
    for i in context_ids:
        t,a=records[i]
        parts=a if t=='__COMPLEX__' else [P21Typed(t,a)]
        names={p.name for p in parts if isinstance(p,P21Typed)}
        if 'LENGTH_UNIT' in names:
            si=[p.args for p in parts if isinstance(p,P21Typed) and p.name=='SI_UNIT']
            if len(si)==1 and si[0]==[P21Enum('MILLI'),P21Enum('METRE')]:millimetres=True
            else:raise ValueError('Length unit must be millimetres')
    if not millimetres:raise ValueError('No supported length unit')
    anchors={}
    for t,a in records.values():
        if t!='EXPLICIT_PROCEDURAL_GEOMETRIC_REPRESENTATION_ITEM_RELATIONSHIP':continue
        prefix=get(a[2],'PROCEDURAL_SHAPE_REPRESENTATION_SEQUENCE')
        if prefix[2] or not prefix[1]:raise ValueError('Unsupported anchor sequence')
        references(prefix[1])
        n=len(prefix[1])
        if prefix[1]!=sequence[:n]:raise ValueError('Anchor is not construction prefix')
        get(a[3],'MANIFOLD_SOLID_BREP')
        base=int(prefix[1][-1])
        if base in anchors:raise ValueError('Duplicate base topology')
        anchors[base]=int(a[3])
    operations=[];names={};byentity={}
    for ref in sequence:
        t,a=records[int(ref)]
        name=a[0]
        if not isinstance(name,str) or not re.fullmatch('[A-Za-z][A-Za-z0-9_]{0,79}',name) or name in names:raise ValueError('Invalid/duplicate operation name')
        op={'id':name,'source_entity':int(ref)}
        if t=='EXTRUDED_FACE_SOLID':
            fa=get(a[1],'FACE_SURFACE')
            if len(fa[1])!=1 or not truth(fa[3]):raise ValueError('Unsupported profile face')
            bound=get(fa[1][0],'FACE_OUTER_BOUND')
            if not truth(bound[2]):raise ValueError('Reversed outer bound unsupported')
            plane=get(fa[2],'PLANE');po,pz,px=placement(plane[1])
            axis=xyz(a[2],'DIRECTION');depth=scalar(a[3])
            if not math.isfinite(depth) or depth<=0 or not same(axis,pz):raise ValueError('Non-normal or negative extrusion unsupported')
            lt,la=records[int(bound[1])]
            if lt=='POLY_LOOP':
                pts=[xyz(x,'CARTESIAN_POINT') for x in la[1]]
                if len(pts)!=4 or not same(axis,[0,0,1]):raise ValueError('Only axis-aligned rectangular polygon supported')
                mins=[min(p[j] for p in pts) for j in range(3)]
                maxs=[max(p[j] for p in pts) for j in range(3)]
                l=maxs[0]-mins[0];w=maxs[1]-mins[1]
                expected=[mins,[maxs[0],mins[1],mins[2]],[maxs[0],maxs[1],mins[2]],[mins[0],maxs[1],mins[2]]]
                if l<=0 or w<=0 or maxs[2]-mins[2]>1e-8 or any(not same(p,q) for p,q in zip(pts,expected)):raise ValueError('Profile is not supported rectangle')
                if not same(po,mins) or not same(px,[1,0,0]):raise ValueError('Rectangle plane mismatch')
                op.update(type='box',origin=mins,length=l,width=w,height=depth)
            elif lt=='EDGE_LOOP':
                if len(la[1])!=1:raise ValueError('Only complete circular loop supported')
                oe=get(la[1][0],'ORIENTED_EDGE')
                if not truth(oe[4]):raise ValueError('Reversed circle unsupported')
                ec=get(oe[3],'EDGE_CURVE')
                if ec[1]!=ec[2] or not truth(ec[4]):raise ValueError('Incomplete circular edge')
                ca=get(ec[3],'CIRCLE');center,normal,u=placement(ca[1]);radius=scalar(ca[2])
                if not math.isfinite(radius) or radius<=0 or not same(center,po) or not same(normal,pz) or not same(u,px):raise ValueError('Circle plane mismatch')
                if not (same(axis,[0,0,1]) or same(axis,[1,0,0])):raise ValueError('Unsupported circular axis')
                vertex=xyz(get(ec[1],'VERTEX_POINT')[1],'CARTESIAN_POINT')
                if not same(vertex,[center[j]+radius*u[j] for j in range(3)]):raise ValueError('Circle vertex mismatch')
                op.update(type='cylinder',center=center,axis=axis,radius=radius,depth=depth)
            else:raise ValueError('Unsupported face loop '+lt)
        elif t=='CSG_SOLID':
            ba=get(a[1],'BOOLEAN_RESULT')
            if ba[0]!=name or str(ba[1]) not in ('UNION','DIFFERENCE','INTERSECTION'):raise ValueError('Unsupported boolean')
            if not all(isinstance(v,P21Ref) for v in ba[2:4]):raise ValueError('Expected Boolean operand references')
            if int(ba[2]) not in byentity or int(ba[3]) not in byentity:raise ValueError('Boolean operand must precede result')
            op.update(type=str(ba[1]).lower(),base=byentity[int(ba[2])]['id'],tool=byentity[int(ba[3])]['id'],refine=True)
        elif t=='SOLID_WITH_CONSTANT_RADIUS_EDGE_BLEND':
            if not isinstance(a[2],P21Ref):raise ValueError('Expected fillet base reference')
            base=int(a[2])
            if base not in byentity or base not in anchors:raise ValueError('Fillet base/anchor missing')
            radius=scalar(a[4]);edges=list(map(int,references(a[3])))
            if not math.isfinite(radius) or radius<=0 or not edges or len(set(edges))!=len(edges):raise ValueError('Invalid fillet selection')
            closure=sth_entity_closure(records,[anchors[base]])
            if not set(edges).issubset(closure):raise ValueError('Fillet edge outside anchored base')
            for e in edges:get(P21Ref(e),'EDGE_CURVE')
            op.update(type='fillet',base=byentity[base]['id'],radius=radius,step_edges=edges,base_brep=anchors[base])
        else:raise ValueError('Unsupported construction entity '+t)
        operations.append(op);names[name]=op;byentity[int(ref)]=op
    # No disconnected operations may silently disappear.
    needed=set();todo=[operations[-1]['id']]
    while todo:
        name=todo.pop()
        if name in needed:continue
        needed.add(name);op=names[name]
        todo.extend(op[k] for k in ('base','tool') if k in op)
    if needed!=set(names):raise ValueError('Disconnected construction operations')
    return {'text':text,'records':records,'operations':operations,'root':operations[-1]['id'],'sha256':hashlib.sha256(text.encode()).hexdigest(),'units':'mm','main_representation':int(links[0][3])}

