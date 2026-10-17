# Inline AP242 procedural construction adapter

This is an optional FreeCAD development-adapter reference. It is not a dependency of the backend-neutral skill. Prefer the maintained tools in [managed-workflow.md](managed-workflow.md) when they cover the operation. Revalidate any remaining inline fallback before use.


Calculate edge fingerprints from `e.copy(True, False).BoundBox`, without copied triangulation. Display triangulation can change bounding-box extremes. Keep the 1e-6 matching tolerance and curve-distance checks in both directions.

This reference contains reusable adapter code only. It supplies no part data, historical results, or case-specific test functions. The generic representation label below replaces a former case-specific label. Revalidate the changed code before use. No live CAD test was run during this cleanup.

This document contains inline MCP code. It is not an executable script file. Send the Python blocks through the FreeCAD proxy of `drawing2cad-mcp`. Supply them to an isolated headless FreeCADCmd process through standard input. Do not save them as .py files.

The supported subset contains:

- Axis-aligned rectangular extrusions.
- Full circular extrusions along +Z or +X.
- Refined union, difference, and intersection.
- Constant-radius edge blends with exact evaluated base EDGE_CURVE anchors.

Only millimetres are supported. The bounded Part21 parser does not use eval. Unknown construction operators, ambiguous edges, unit mismatches, or geometry mismatches stop processing. The final product BREP is a verification reference. Do not use it as a construction placeholder.

A standard importer can show the BREP without editable operations. The adapter rebuilds native editable operations. Full EXPRESS validation and interoperability with other CAD adapters are not claimed.

## Export

Append the procedural graph after semantic and graphical PMI serialization. Do not pass the appended procedural graph through an OCC rewrite. This OCC version does not type the edge-blend or procedural entities. Existing input entity text is preserved exactly. Auxiliary BREP geometry has no separate product root.

```python
import re as sth_p21_re
import math as sth_p21_math

class P21Ref(int): pass
class P21Enum(str): pass
class P21Binary(str): pass
class P21Derived: pass
P21_DERIVED=P21Derived()
class P21Typed:
    def __init__(self,name,args):
        self.name=str(name).upper()
        self.args=list(args)
    def __repr__(self):
        return 'P21Typed('+repr(self.name)+','+repr(self.args)+')'
class P21Records(dict):
    def __init__(self):
        super().__init__()
        self.raw_rhs={}
class _SthP21Parser:
    number=sth_p21_re.compile(r'[+-]?(?:(?:\d+\.\d*)|(?:\.\d+)|(?:\d+))(?:[Ee][+-]?\d+)?')
    name=sth_p21_re.compile(r'[A-Za-z_][A-Za-z0-9_-]*')
    enum=sth_p21_re.compile(r'\.([A-Za-z_][A-Za-z0-9_]*)\.')
    def __init__(self,text,max_bytes,max_records,max_nodes,max_depth,max_string):
        if not isinstance(text,str):raise TypeError('Part21 input must be str')
        if len(text)>max_bytes:raise ValueError('Part21 text exceeds size bound')
        self.text=text;self.n=len(text);self.pos=0;self.look=None;self.last_end=0
        self.max_records=max_records;self.max_nodes=max_nodes;self.max_depth=max_depth
        self.max_string=max_string;self.nodes=0
    def error(self,message,pos=None):
        raise ValueError('Part21 '+message+' at offset '+str(self.pos if pos is None else pos))
    def token(self):
        t=self.text;n=self.n;p=self.pos
        while p<n:
            if t[p].isspace():p+=1;continue
            if t.startswith('/*',p):
                e=t.find('*/',p+2)
                if e<0:self.error('unterminated comment',p)
                p=e+2;continue
            break
        start=p
        if p>=n:self.pos=p;return ('EOF',None,p,p)
        c=t[p]
        if c in "(),;=*$":
            self.pos=p+1;return (c,c,p,p+1)
        if c=="'":
            p+=1;chars=[]
            while p<n:
                if t[p]=="'":
                    if p+1<n and t[p+1]=="'":chars.append("'");p+=2
                    else:
                        p+=1;self.pos=p;return ('STRING',''.join(chars),start,p)
                else:chars.append(t[p]);p+=1
                if len(chars)>self.max_string:self.error('string exceeds bound',start)
            self.error('unterminated string',start)
        if c=='"':
            e=t.find('"',p+1)
            if e<0:self.error('unterminated binary',p)
            value=t[p+1:e]
            if len(value)>self.max_string or not sth_p21_re.fullmatch(r'[0-3][0-9A-Fa-f]*',value):
                self.error('invalid binary literal',p)
            self.pos=e+1;return ('BINARY',value.upper(),p,e+1)
        if c=='#':
            p+=1;e=p
            while e<n and t[e].isdigit():e+=1
            if e==p or e-p>20:self.error('invalid entity reference',start)
            value=int(t[p:e])
            if value<=0:self.error('entity reference must be positive',start)
            self.pos=e;return ('REF',value,start,e)
        if c=='.':
            m=self.enum.match(t,p)
            if m:
                self.pos=m.end();return ('ENUM',m.group(1).upper(),p,m.end())
        if c in '+-.0123456789':
            m=self.number.match(t,p)
            if not m:self.error('invalid numeric token',p)
            raw=m.group(0)
            if len(raw)>256:self.error('numeric token exceeds bound',p)
            if any(x in raw for x in '.eE'):
                value=float(raw)
                if not sth_p21_math.isfinite(value):self.error('non-finite number',p)
            else:value=int(raw)
            self.pos=m.end();return ('NUMBER',value,p,m.end())
        m=self.name.match(t,p)
        if m:
            if len(m.group(0))>256:self.error('identifier exceeds bound',p)
            self.pos=m.end();return ('NAME',m.group(0).upper(),p,m.end())
        self.error('unexpected character '+repr(c),p)
    def peek(self):
        if self.look is None:self.look=self.token()
        return self.look
    def pop(self):
        out=self.peek();self.look=None;self.last_end=out[3];return out
    def expect(self,kind,value=None):
        out=self.pop()
        if out[0]!=kind or (value is not None and out[1]!=value):
            self.error('expected '+repr((kind,value))+'; got '+repr(out[:2]),out[2])
        return out
    def bump(self,depth):
        self.nodes+=1
        if self.nodes>self.max_nodes:self.error('node count exceeds bound')
        if depth>self.max_depth:self.error('nesting depth exceeds bound')
    def args(self,depth):
        self.bump(depth)
        self.expect('(');out=[]
        if self.peek()[0]==')':self.pop();return out
        while True:
            out.append(self.value(depth+1))
            if self.peek()[0]==')':self.pop();return out
            self.expect(',')
    def value(self,depth):
        self.bump(depth);tok=self.peek();kind,val=tok[:2]
        if kind=='(' :return self.args(depth+1)
        self.pop()
        if kind=='REF':return P21Ref(val)
        if kind=='ENUM':return P21Enum(val)
        if kind=='BINARY':return P21Binary(val)
        if kind=='STRING' or kind=='NUMBER':return val
        if kind=='$':return None
        if kind=='*':return P21_DERIVED
        if kind=='NAME':
            if '-' in val:self.error('invalid typed value name',tok[2])
            return P21Typed(val,self.args(depth+1))
        self.error('expected value; got '+repr(tok[:2]),tok[2])
    def entity(self):
        self.bump(0)
        if self.peek()[0]=='NAME':
            typ=self.pop()[1]
            if '-' in typ:self.error('invalid entity name')
            return typ,self.args(1)
        self.expect('(');parts=[]
        while self.peek()[0]!=')':
            typ=self.expect('NAME')[1]
            if '-' in typ:self.error('invalid complex component name')
            parts.append(P21Typed(typ,self.args(1)))
            if len(parts)>self.max_nodes:self.error('complex component bound')
        self.expect(')')
        if not parts:self.error('empty complex entity')
        return '__COMPLEX__',parts
    def find_data(self):
        nesting=0
        while True:
            tok=self.pop()
            if tok[0]=='EOF':self.error('DATA section missing')
            if tok[0]=='(':
                nesting+=1
                if nesting>self.max_depth:self.error('header nesting bound')
            elif tok[0]==')':
                nesting-=1
                if nesting<0:self.error('unbalanced header')
            elif nesting==0 and tok[0]=='NAME' and tok[1]=='DATA':
                if self.peek()[0]=='(':self.args(1)
                self.expect(';');return
    def parse(self):
        self.find_data();out=P21Records()
        while True:
            token=self.peek()
            if token[0]=='NAME' and token[1]=='ENDSEC':
                self.pop();self.expect(';');break
            ident=self.expect('REF')[1]
            if ident in out:self.error('duplicate entity #'+str(ident))
            if len(out)>=self.max_records:self.error('record count exceeds bound')
            self.expect('=');start=self.peek()[2]
            out[ident]=self.entity();end=self.last_end
            out.raw_rhs[ident]=self.text[start:end]
            self.expect(';')
        # Detect unsupported additional DATA sections without reading their entities.
        nesting=0
        while self.peek()[0]!='EOF':
            tok=self.pop()
            if tok[0]=='(':nesting+=1
            elif tok[0]==')':nesting-=1
            if nesting>self.max_depth or nesting<0:self.error('invalid trailer nesting')
            if nesting==0 and tok[0]=='NAME' and tok[1]=='DATA':
                self.error('multiple DATA sections are unsupported')
        if nesting:self.error('unbalanced trailer')
        return out

def sth_p21_parse(text,max_bytes=33554432,max_records=200000,max_nodes=2000000,max_depth=128,max_string=1048576):
    bounds=[max_bytes,max_records,max_nodes,max_depth,max_string]
    if any(not isinstance(x,int) or x<=0 for x in bounds):raise ValueError('Part21 bounds must be positive integers')
    if max_depth>256:raise ValueError('Part21 max_depth must be <=256')
    return _SthP21Parser(text,*bounds).parse()

def sth_p21_refs(value):
    refs=set();stack=[(value,0)];seen=0
    while stack:
        item,depth=stack.pop();seen+=1
        if seen>2000000 or depth>256:raise ValueError('Part21 reference traversal exceeds bounds')
        if isinstance(item,P21Ref):refs.add(int(item))
        elif isinstance(item,P21Typed):stack.extend((x,depth+1) for x in item.args)
        elif isinstance(item,dict):stack.extend((x,depth+1) for x in item.values())
        elif isinstance(item,(list,tuple)):stack.extend((x,depth+1) for x in item)
    return refs

def sth_p21_validate_refs(records):
    missing=sth_p21_refs(records)-set(records)
    if missing:raise ValueError('Part21 dangling references: '+str(sorted(missing)[:100]))
    return True

def sth_p21_dump(value,_depth=0):
    if _depth>256:raise ValueError('Part21 dump nesting bound')
    if isinstance(value,P21Ref):
        if int(value)<=0:raise ValueError('Part21 reference must be positive')
        return '#'+str(int(value))
    if isinstance(value,P21Enum):
        if not sth_p21_re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*',value):raise ValueError('Invalid Part21 enum')
        return '.'+value.upper()+'.'
    if isinstance(value,P21Binary):
        if not sth_p21_re.fullmatch(r'[0-3][0-9A-Fa-f]*',value):raise ValueError('Invalid Part21 binary')
        return '"'+value.upper()+'"'
    if isinstance(value,P21Typed):
        if not sth_p21_re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*',value.name):raise ValueError('Invalid typed name')
        return value.name.upper()+sth_p21_dump(value.args,_depth+1)
    if isinstance(value,P21Derived):return '*'
    if value is None:return '$'
    if isinstance(value,bool):raise TypeError('Use P21Enum for logical values')
    if isinstance(value,int):return str(value)
    if isinstance(value,float):
        if not sth_p21_math.isfinite(value):raise ValueError('Part21 non-finite number')
        text=format(value,'.17g').upper()
        return text if '.' in text or 'E' in text else text+'.'
    if isinstance(value,str):return "'"+value.replace("'","''")+"'"
    if isinstance(value,(list,tuple)):return '('+','.join(sth_p21_dump(x,_depth+1) for x in value)+')'
    raise TypeError('Unsupported Part21 value '+type(value).__name__)

def sth_p21_record(ident,typ,args):
    if not isinstance(ident,int) or isinstance(ident,bool) or ident<=0:raise ValueError('Invalid entity id')
    if typ=='__COMPLEX__':
        if not args or not all(isinstance(x,P21Typed) for x in args):raise ValueError('Invalid complex entity')
        rhs='('+' '.join(sth_p21_dump(x) for x in args)+')'
    else:
        if not sth_p21_re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*',typ):raise ValueError('Invalid entity name')
        if not isinstance(args,(list,tuple)):raise ValueError('Entity args must be a sequence')
        rhs=typ.upper()+sth_p21_dump(args)
    return '#'+str(ident)+'='+rhs+';'

import FreeCAD as sth_em_A, Part as sth_em_Part
import math as sth_em_math
from OCC.Core.BRepTools import breptools as sth_em_breptools
from OCC.Core.STEPControl import STEPControl_Reader as sth_em_Reader
from OCC.Core.StepData import StepData_StepModel as sth_em_Model, StepData_StepWriter as sth_em_Writer, StepData_Protocol as sth_em_Protocol
from OCC.Core.TransferBRep import transferbrep as sth_em_transferbrep

def sth_edge_fingerprint(e):
    bb=e.copy(True,False).BoundBox
    xyz=lambda v:[v.x,v.y,v.z]
    r={'length':e.Length,'center':xyz(e.CenterOfMass),'bounds':[bb.XMin,bb.YMin,bb.ZMin,bb.XMax,bb.YMax,bb.ZMax],'curve':type(e.Curve).__name__,'vertices':[xyz(v.Point) for v in e.Vertexes]}
    if hasattr(e.Curve,'Radius'):r['radius']=e.Curve.Radius
    return r

def sth_edge_fingerprint_equal(a,b,tol=1e-6):
    if a['curve']!=b['curve'] or abs(a['length']-b['length'])>tol:return False
    if any(abs(x-y)>tol for k in ['center','bounds'] for x,y in zip(a[k],b[k])):return False
    if ('radius' in a)!=('radius' in b):return False
    if 'radius' in a and abs(a['radius']-b['radius'])>tol:return False
    if len(a['vertices'])!=len(b['vertices']):return False
    dist=lambda p,q:sth_em_math.sqrt(sum((x-y)**2 for x,y in zip(p,q)))
    ds=[min(dist(p,q) for q in b['vertices']) for p in a['vertices']]
    ds.extend(min(dist(p,q) for q in a['vertices']) for p in b['vertices'])
    return max(ds+[0])<=tol

def sth_occ_to_part(shape):
    if shape.IsNull():raise ValueError('Null OCC shape')
    f=sth_em_Part.Shape()
    f.importBrepFromString(sth_em_breptools.WriteToString(shape,True))
    return f

def sth_match_native_edge(reference,candidates,tol=1e-6,samples=33):
    fp=sth_edge_fingerprint(reference)
    found=[]
    for i,e in enumerate(candidates,1):
        if not sth_edge_fingerprint_equal(fp,sth_edge_fingerprint(e),tol):continue
        ds=[sth_em_Part.Vertex(p).distToShape(e)[0] for p in reference.discretize(Number=samples)]
        ds.extend(sth_em_Part.Vertex(p).distToShape(reference)[0] for p in e.discretize(Number=samples))
        d=max(ds+[0])
        if d<=tol:found.append((i,e,d))
    if len(found)!=1:raise ValueError('Expected unique edge; matches='+str([i for i,e,d in found]))
    return found[0]

def sth_reader_edge(reader,edge_id,base_brep_id=None):
    model=reader.StepModel()
    entity=model.Value(edge_id)
    if not entity.IsKind('StepShape_EdgeCurve'):raise ValueError('Not EDGE_CURVE #'+str(edge_id))
    if base_brep_id is not None:
        base=model.Value(base_brep_id)
        if not base.IsKind('StepShape_ManifoldSolidBrep'):raise ValueError('Anchor not MANIFOLD_SOLID_BREP')
        if not reader.TransferEntity(base):raise ValueError('Auxiliary BREP transfer failed')
    tp=reader.WS().TransferReader().TransientProcess()
    shape=sth_em_transferbrep.ShapeResult(tp,entity)
    if shape.IsNull():raise ValueError('STEP edge has no transferred geometry #'+str(edge_id))
    fc=sth_occ_to_part(shape)
    if len(fc.Edges)!=1:raise ValueError('STEP anchor did not transfer to one edge')
    return fc.Edges[0]

def sth_export_edge_entities(writer,fingerprints,tol=1e-6):
    # Finds real exported EDGE_CURVEs even when writer shape healing changed topology.
    # One isolated base-BREP writer per operation; no product outputs/files created.
    model=sth_em_Model.DownCast(writer.WS().Model())
    sw=sth_em_Writer(model);sw.SendModel(sth_em_Protocol.DownCast(model.Protocol()))
    text='\n'.join(sw.Line(i).ToCString() for i in range(1,sw.NbLines()+1))
    reader=sth_em_Reader()
    if int(reader.ReadStream('fillet-edge-anchors',text))!=1:raise ValueError('STEP self read failed')
    rm=reader.StepModel()
    breps=[i for i in range(1,rm.NbEntities()+1) if rm.Value(i).IsKind('StepShape_ManifoldSolidBrep')]
    if len(breps)!=1:raise ValueError('Expected exactly one auxiliary BREP, got '+str(breps))
    if not reader.TransferEntity(rm.Value(breps[0])):raise ValueError('Anchor BREP transfer failed')
    candidates=[]
    for i in range(1,rm.NbEntities()+1):
        if rm.Value(i).IsKind('StepShape_EdgeCurve'):
            e=sth_reader_edge(reader,i)
            candidates.append((i,e,sth_edge_fingerprint(e)))
    result=[]
    for fp in fingerprints:
        matches=[(i,e) for i,e,actual in candidates if sth_edge_fingerprint_equal(fp,actual,tol)]
        if len(matches)!=1:raise ValueError('Expected unique STEP edge for '+str(fp)+'; matches='+str([i for i,e in matches]))
        i,e=matches[0]
        original=model.Value(i)
        if not original.IsKind('StepShape_EdgeCurve'):raise ValueError('STEP serialization renumbered unexpected entity')
        result.append(original)
    return result

def sth_export_aux_brep(shape_path,fingerprints,tol=1e-6):
    from OCC.Core.STEPControl import STEPControl_Writer,STEPControl_AsIs
    fc=sth_em_Part.Shape();fc.read(shape_path)
    if fc.isNull() or not fc.isValid():raise ValueError('Invalid auxiliary shape '+shape_path)
    occ=sth_em_breptools.ReadFromString(fc.exportBrepToString())
    writer=STEPControl_Writer()
    if int(writer.Transfer(occ,STEPControl_AsIs))!=1:raise ValueError('Auxiliary STEP export failed')
    selected=sth_export_edge_entities(writer,fingerprints,tol)
    model=sth_em_Model.DownCast(writer.WS().Model())
    breps=[model.Value(i) for i in range(1,model.NbEntities()+1) if model.Value(i).IsKind('StepShape_ManifoldSolidBrep')]
    if len(breps)!=1:raise ValueError('Expected one auxiliary solid BREP')
    return {'model':model,'brep':breps[0],'selected_edges':selected,'writer':writer}


import os,json,hashlib,math
import FreeCAD as A,Part
from OCC.Core.STEPControl import STEPControl_Writer,STEPControl_Reader
from OCC.Core.Interface import Interface_Static

def sth_step_text(model):
    sw=sth_em_Writer(model)
    sw.SendModel(sth_em_Protocol.DownCast(model.Protocol()))
    return '\n'.join(sw.Line(i).ToCString() for i in range(1,sw.NbLines()+1))

def sth_entity_closure(records,roots):
    todo=list(roots);seen=set()
    while todo:
        i=int(todo.pop())
        if i in seen:continue
        if i not in records:raise ValueError('Missing STEP #'+str(i))
        seen.add(i);todo.extend(sth_p21_refs(records[i][1]))
    return seen

def sth_remap_value(v,mapping):
    if isinstance(v,P21Ref):return P21Ref(mapping[int(v)])
    if isinstance(v,P21Typed):return P21Typed(v.name,[sth_remap_value(x,mapping) for x in v.args])
    if isinstance(v,(tuple,list)):return [sth_remap_value(x,mapping) for x in v]
    return v

def sth_export_constructive(step_path,contract_path,build_path,out_path):
    original=open(step_path,'r',encoding='utf-8',newline='').read()
    records=sth_p21_parse(original);sth_p21_validate_refs(records)
    reps=[i for i,(t,a) in records.items() if t=='ADVANCED_BREP_SHAPE_REPRESENTATION']
    if len(reps)!=1:raise ValueError('Expected one main BREP representation')
    if any(t=='PROCEDURAL_SHAPE_REPRESENTATION' for t,a in records.values()):raise ValueError('Input already has construction')
    mainrep=reps[0];context=records[mainrep][1][2]
    contract=json.load(open(contract_path,encoding='utf-8'))
    report=json.load(open(build_path,encoding='utf-8'))
    if contract['contract_sha256']!=report['contract_sha256']:raise ValueError('Contract/build mismatch')
    if contract['units']['length']!='mm':raise ValueError('Only millimetres supported')
    operations=contract['operations']
    if len({o['id'] for o in operations})!=len(operations):raise ValueError('Duplicate operation names')
    fillets={f['id']:f for f in report['fillets']}
    out=[];nextid=max(records)+1;nodeids={};ordered=[];anchors=[]
    def add(t,a):
        nonlocal nextid
        n=nextid;nextid+=1
        out.append(sth_p21_record(n,t,a))
        return P21Ref(n)
    def direction(v):return add('DIRECTION',['',[float(x) for x in v]])
    def point(v):return add('CARTESIAN_POINT',['',[float(x) for x in v]])
    def face_plane(center,axis,u):
        cp=point(center);nz=direction(axis);nx=direction(u)
        placement=add('AXIS2_PLACEMENT_3D',['',cp,nz,nx])
        plane=add('PLANE',['',placement])
        return cp,nz,placement,plane
    init=STEPControl_Writer()
    Interface_Static.SetCVal('write.step.schema','AP242DIS')
    for op in operations:
        name=op['id'];kind=op['type']
        if kind=='cylinder':
            center=op['center'];axis=op['axis']
            if axis not in ([0,0,1],[1,0,0]):raise ValueError('Unsupported cylinder direction')
            u=[1,0,0] if axis==[0,0,1] else [0,1,0]
            cp,nz,placement,plane=face_plane(center,axis,u)
            circle=add('CIRCLE',['',placement,float(op['radius'])])
            vp=add('VERTEX_POINT',['',point([center[j]+op['radius']*u[j] for j in range(3)])])
            edge=add('EDGE_CURVE',['',vp,vp,circle,P21Enum('T')])
            oriented=add('ORIENTED_EDGE',['',P21_DERIVED,P21_DERIVED,edge,P21Enum('T')])
            loop=add('EDGE_LOOP',['',[oriented]])
            bound=add('FACE_OUTER_BOUND',['',loop,P21Enum('T')])
            face=add('FACE_SURFACE',[name+' circular profile',[bound],plane,P21Enum('T')])
            result=add('EXTRUDED_FACE_SOLID',[name,face,nz,float(op['depth'])])
        elif kind=='box':
            p=op['origin'];l=float(op['length']);w=float(op['width'])
            cp,nz,placement,plane=face_plane(p,[0,0,1],[1,0,0])
            pts=[cp,point([p[0]+l,p[1],p[2]]),point([p[0]+l,p[1]+w,p[2]]),point([p[0],p[1]+w,p[2]])]
            loop=add('POLY_LOOP',['',pts]);bound=add('FACE_OUTER_BOUND',['',loop,P21Enum('T')])
            face=add('FACE_SURFACE',[name+' rectangular profile',[bound],plane,P21Enum('T')])
            result=add('EXTRUDED_FACE_SOLID',[name,face,nz,float(op['height'])])
        elif kind in ('union','difference','intersection'):
            if not op.get('refine',False):raise ValueError('This adapter requires refined boolean policy')
            result=add('BOOLEAN_RESULT',[name,P21Enum(kind.upper()),nodeids[op['base']],nodeids[op['tool']]])
            result=add('CSG_SOLID',[name,result])
        elif kind=='fillet':
            f=fillets[name]
            if f['base']!=op['base'] or abs(f['radius']-op['radius'])>1e-10:raise ValueError('Fillet report mismatch')
            path=os.path.join(os.path.dirname(build_path),'intermediate_brep',op['base']+'.brep')
            aux=sth_export_aux_brep(path,f['edge_fingerprints'])
            auxtext=sth_step_text(aux['model']);auxrecords=sth_p21_parse(auxtext)
            baseid=aux['model'].Number(aux['brep'])
            edgeids=[aux['model'].Number(e) for e in aux['selected_edges']]
            selected=sth_entity_closure(auxrecords,[baseid])
            if not set(edgeids).issubset(selected):raise ValueError('Selected edges outside base BREP')
            remap={i:nextid+k for k,i in enumerate(sorted(selected))}
            nextid+=len(remap)
            for i in sorted(selected):
                t,a=auxrecords[i]
                out.append(sth_p21_record(remap[i],t,sth_remap_value(a,remap)))
            if not ordered or nodeids[op['base']] not in ordered:raise ValueError('Invalid fillet base order')
            prefix=ordered[:ordered.index(nodeids[op['base']])+1]
            seq=add('PROCEDURAL_SHAPE_REPRESENTATION_SEQUENCE',[name+' base construction',prefix,[],'Construction through fillet operand'])
            anchor=add('EXPLICIT_PROCEDURAL_GEOMETRIC_REPRESENTATION_ITEM_RELATIONSHIP',[name+' base topology','Evaluated reference topology for edge selection',seq,P21Ref(remap[baseid])])
            result=add('SOLID_WITH_CONSTANT_RADIUS_EDGE_BLEND',[name,'Drawing specified constant radius; selected edges of evaluated base',nodeids[op['base']],[P21Ref(remap[e]) for e in edgeids],float(op['radius'])])
            anchors.append({'fillet':name,'solid':int(result),'base_brep':remap[baseid],'edges':[remap[e] for e in edgeids]})
        else:raise ValueError('Unsupported operation '+kind)
        nodeids[name]=result;ordered.append(result)
    if contract['root']!=operations[-1]['id']:raise ValueError('Root must end sequence')
    seq=add('PROCEDURAL_SHAPE_REPRESENTATION_SEQUENCE',['Complete editable construction',ordered,[],'Ordered standard operations; final element is result'])
    proc=add('PROCEDURAL_SHAPE_REPRESENTATION',['Editable construction',[seq],context])
    rel=add('EXPLICIT_PROCEDURAL_SHAPE_REPRESENTATION_RELATIONSHIP',['Constructive and evaluated shape','Construction of the single product shape',proc,P21Ref(mainrep)])
    suffix='\n'+'\n'.join(out)+'\n'
    end=original.rfind('ENDSEC;')
    if end<0:raise ValueError('Missing DATA end')
    combined=original[:end]+suffix+original[end:]
    checked=sth_p21_parse(combined);sth_p21_validate_refs(checked)
    if len(checked)!=len(records)+len(out):raise ValueError('Entity count mismatch')
    # Preserve the complete supplied PMI/BREP prefix; append only standard entities.
    if combined[:end]!=original[:end]:raise ValueError('Input changed')
    open(out_path,'w',encoding='utf-8',newline='\n').write(combined)
    result={'path':out_path,'input_sha256':hashlib.sha256(original.encode()).hexdigest(),'sha256':hashlib.sha256(combined.encode()).hexdigest(),'contract_sha256':contract['contract_sha256'],'source_sha256':report['source_sha256'],'operations':len(ordered),'entities':len(checked),'appended_entities':len(out),'fillets':anchors,'root':int(ordered[-1]),'main_representation':mainrep,'context':int(context),'all_references_resolve':True,'base_input_preserved':True}
    return result

```

Entry point: `sth_export_constructive(step_path, contract_path, build_report_path, output_step_path)`. The initial export uses the approved contract and exact intermediate BREP topology. The import below requires only the resulting STEP.

## STEP-only import and verification

```python
import re as sth_p21_re
import math as sth_p21_math

class P21Ref(int): pass
class P21Enum(str): pass
class P21Binary(str): pass
class P21Derived: pass
P21_DERIVED=P21Derived()
class P21Typed:
    def __init__(self,name,args):
        self.name=str(name).upper()
        self.args=list(args)
    def __repr__(self):
        return 'P21Typed('+repr(self.name)+','+repr(self.args)+')'
class P21Records(dict):
    def __init__(self):
        super().__init__()
        self.raw_rhs={}
class _SthP21Parser:
    number=sth_p21_re.compile(r'[+-]?(?:(?:\d+\.\d*)|(?:\.\d+)|(?:\d+))(?:[Ee][+-]?\d+)?')
    name=sth_p21_re.compile(r'[A-Za-z_][A-Za-z0-9_-]*')
    enum=sth_p21_re.compile(r'\.([A-Za-z_][A-Za-z0-9_]*)\.')
    def __init__(self,text,max_bytes,max_records,max_nodes,max_depth,max_string):
        if not isinstance(text,str):raise TypeError('Part21 input must be str')
        if len(text)>max_bytes:raise ValueError('Part21 text exceeds size bound')
        self.text=text;self.n=len(text);self.pos=0;self.look=None;self.last_end=0
        self.max_records=max_records;self.max_nodes=max_nodes;self.max_depth=max_depth
        self.max_string=max_string;self.nodes=0
    def error(self,message,pos=None):
        raise ValueError('Part21 '+message+' at offset '+str(self.pos if pos is None else pos))
    def token(self):
        t=self.text;n=self.n;p=self.pos
        while p<n:
            if t[p].isspace():p+=1;continue
            if t.startswith('/*',p):
                e=t.find('*/',p+2)
                if e<0:self.error('unterminated comment',p)
                p=e+2;continue
            break
        start=p
        if p>=n:self.pos=p;return ('EOF',None,p,p)
        c=t[p]
        if c in "(),;=*$":
            self.pos=p+1;return (c,c,p,p+1)
        if c=="'":
            p+=1;chars=[]
            while p<n:
                if t[p]=="'":
                    if p+1<n and t[p+1]=="'":chars.append("'");p+=2
                    else:
                        p+=1;self.pos=p;return ('STRING',''.join(chars),start,p)
                else:chars.append(t[p]);p+=1
                if len(chars)>self.max_string:self.error('string exceeds bound',start)
            self.error('unterminated string',start)
        if c=='"':
            e=t.find('"',p+1)
            if e<0:self.error('unterminated binary',p)
            value=t[p+1:e]
            if len(value)>self.max_string or not sth_p21_re.fullmatch(r'[0-3][0-9A-Fa-f]*',value):
                self.error('invalid binary literal',p)
            self.pos=e+1;return ('BINARY',value.upper(),p,e+1)
        if c=='#':
            p+=1;e=p
            while e<n and t[e].isdigit():e+=1
            if e==p or e-p>20:self.error('invalid entity reference',start)
            value=int(t[p:e])
            if value<=0:self.error('entity reference must be positive',start)
            self.pos=e;return ('REF',value,start,e)
        if c=='.':
            m=self.enum.match(t,p)
            if m:
                self.pos=m.end();return ('ENUM',m.group(1).upper(),p,m.end())
        if c in '+-.0123456789':
            m=self.number.match(t,p)
            if not m:self.error('invalid numeric token',p)
            raw=m.group(0)
            if len(raw)>256:self.error('numeric token exceeds bound',p)
            if any(x in raw for x in '.eE'):
                value=float(raw)
                if not sth_p21_math.isfinite(value):self.error('non-finite number',p)
            else:value=int(raw)
            self.pos=m.end();return ('NUMBER',value,p,m.end())
        m=self.name.match(t,p)
        if m:
            if len(m.group(0))>256:self.error('identifier exceeds bound',p)
            self.pos=m.end();return ('NAME',m.group(0).upper(),p,m.end())
        self.error('unexpected character '+repr(c),p)
    def peek(self):
        if self.look is None:self.look=self.token()
        return self.look
    def pop(self):
        out=self.peek();self.look=None;self.last_end=out[3];return out
    def expect(self,kind,value=None):
        out=self.pop()
        if out[0]!=kind or (value is not None and out[1]!=value):
            self.error('expected '+repr((kind,value))+'; got '+repr(out[:2]),out[2])
        return out
    def bump(self,depth):
        self.nodes+=1
        if self.nodes>self.max_nodes:self.error('node count exceeds bound')
        if depth>self.max_depth:self.error('nesting depth exceeds bound')
    def args(self,depth):
        self.bump(depth)
        self.expect('(');out=[]
        if self.peek()[0]==')':self.pop();return out
        while True:
            out.append(self.value(depth+1))
            if self.peek()[0]==')':self.pop();return out
            self.expect(',')
    def value(self,depth):
        self.bump(depth);tok=self.peek();kind,val=tok[:2]
        if kind=='(' :return self.args(depth+1)
        self.pop()
        if kind=='REF':return P21Ref(val)
        if kind=='ENUM':return P21Enum(val)
        if kind=='BINARY':return P21Binary(val)
        if kind=='STRING' or kind=='NUMBER':return val
        if kind=='$':return None
        if kind=='*':return P21_DERIVED
        if kind=='NAME':
            if '-' in val:self.error('invalid typed value name',tok[2])
            return P21Typed(val,self.args(depth+1))
        self.error('expected value; got '+repr(tok[:2]),tok[2])
    def entity(self):
        self.bump(0)
        if self.peek()[0]=='NAME':
            typ=self.pop()[1]
            if '-' in typ:self.error('invalid entity name')
            return typ,self.args(1)
        self.expect('(');parts=[]
        while self.peek()[0]!=')':
            typ=self.expect('NAME')[1]
            if '-' in typ:self.error('invalid complex component name')
            parts.append(P21Typed(typ,self.args(1)))
            if len(parts)>self.max_nodes:self.error('complex component bound')
        self.expect(')')
        if not parts:self.error('empty complex entity')
        return '__COMPLEX__',parts
    def find_data(self):
        nesting=0
        while True:
            tok=self.pop()
            if tok[0]=='EOF':self.error('DATA section missing')
            if tok[0]=='(':
                nesting+=1
                if nesting>self.max_depth:self.error('header nesting bound')
            elif tok[0]==')':
                nesting-=1
                if nesting<0:self.error('unbalanced header')
            elif nesting==0 and tok[0]=='NAME' and tok[1]=='DATA':
                if self.peek()[0]=='(':self.args(1)
                self.expect(';');return
    def parse(self):
        self.find_data();out=P21Records()
        while True:
            token=self.peek()
            if token[0]=='NAME' and token[1]=='ENDSEC':
                self.pop();self.expect(';');break
            ident=self.expect('REF')[1]
            if ident in out:self.error('duplicate entity #'+str(ident))
            if len(out)>=self.max_records:self.error('record count exceeds bound')
            self.expect('=');start=self.peek()[2]
            out[ident]=self.entity();end=self.last_end
            out.raw_rhs[ident]=self.text[start:end]
            self.expect(';')
        # Detect unsupported additional DATA sections without reading their entities.
        nesting=0
        while self.peek()[0]!='EOF':
            tok=self.pop()
            if tok[0]=='(':nesting+=1
            elif tok[0]==')':nesting-=1
            if nesting>self.max_depth or nesting<0:self.error('invalid trailer nesting')
            if nesting==0 and tok[0]=='NAME' and tok[1]=='DATA':
                self.error('multiple DATA sections are unsupported')
        if nesting:self.error('unbalanced trailer')
        return out

def sth_p21_parse(text,max_bytes=33554432,max_records=200000,max_nodes=2000000,max_depth=128,max_string=1048576):
    bounds=[max_bytes,max_records,max_nodes,max_depth,max_string]
    if any(not isinstance(x,int) or x<=0 for x in bounds):raise ValueError('Part21 bounds must be positive integers')
    if max_depth>256:raise ValueError('Part21 max_depth must be <=256')
    return _SthP21Parser(text,*bounds).parse()

def sth_p21_refs(value):
    refs=set();stack=[(value,0)];seen=0
    while stack:
        item,depth=stack.pop();seen+=1
        if seen>2000000 or depth>256:raise ValueError('Part21 reference traversal exceeds bounds')
        if isinstance(item,P21Ref):refs.add(int(item))
        elif isinstance(item,P21Typed):stack.extend((x,depth+1) for x in item.args)
        elif isinstance(item,dict):stack.extend((x,depth+1) for x in item.values())
        elif isinstance(item,(list,tuple)):stack.extend((x,depth+1) for x in item)
    return refs

def sth_p21_validate_refs(records):
    missing=sth_p21_refs(records)-set(records)
    if missing:raise ValueError('Part21 dangling references: '+str(sorted(missing)[:100]))
    return True

def sth_p21_dump(value,_depth=0):
    if _depth>256:raise ValueError('Part21 dump nesting bound')
    if isinstance(value,P21Ref):
        if int(value)<=0:raise ValueError('Part21 reference must be positive')
        return '#'+str(int(value))
    if isinstance(value,P21Enum):
        if not sth_p21_re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*',value):raise ValueError('Invalid Part21 enum')
        return '.'+value.upper()+'.'
    if isinstance(value,P21Binary):
        if not sth_p21_re.fullmatch(r'[0-3][0-9A-Fa-f]*',value):raise ValueError('Invalid Part21 binary')
        return '"'+value.upper()+'"'
    if isinstance(value,P21Typed):
        if not sth_p21_re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*',value.name):raise ValueError('Invalid typed name')
        return value.name.upper()+sth_p21_dump(value.args,_depth+1)
    if isinstance(value,P21Derived):return '*'
    if value is None:return '$'
    if isinstance(value,bool):raise TypeError('Use P21Enum for logical values')
    if isinstance(value,int):return str(value)
    if isinstance(value,float):
        if not sth_p21_math.isfinite(value):raise ValueError('Part21 non-finite number')
        text=format(value,'.17g').upper()
        return text if '.' in text or 'E' in text else text+'.'
    if isinstance(value,str):return "'"+value.replace("'","''")+"'"
    if isinstance(value,(list,tuple)):return '('+','.join(sth_p21_dump(x,_depth+1) for x in value)+')'
    raise TypeError('Unsupported Part21 value '+type(value).__name__)

def sth_p21_record(ident,typ,args):
    if not isinstance(ident,int) or isinstance(ident,bool) or ident<=0:raise ValueError('Invalid entity id')
    if typ=='__COMPLEX__':
        if not args or not all(isinstance(x,P21Typed) for x in args):raise ValueError('Invalid complex entity')
        rhs='('+' '.join(sth_p21_dump(x) for x in args)+')'
    else:
        if not sth_p21_re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*',typ):raise ValueError('Invalid entity name')
        if not isinstance(args,(list,tuple)):raise ValueError('Entity args must be a sequence')
        rhs=typ.upper()+sth_p21_dump(args)
    return '#'+str(ident)+'='+rhs+';'

import FreeCAD as sth_em_A, Part as sth_em_Part
import math as sth_em_math
from OCC.Core.BRepTools import breptools as sth_em_breptools
from OCC.Core.STEPControl import STEPControl_Reader as sth_em_Reader
from OCC.Core.StepData import StepData_StepModel as sth_em_Model, StepData_StepWriter as sth_em_Writer, StepData_Protocol as sth_em_Protocol
from OCC.Core.TransferBRep import transferbrep as sth_em_transferbrep

def sth_edge_fingerprint(e):
    bb=e.copy(True,False).BoundBox
    xyz=lambda v:[v.x,v.y,v.z]
    r={'length':e.Length,'center':xyz(e.CenterOfMass),'bounds':[bb.XMin,bb.YMin,bb.ZMin,bb.XMax,bb.YMax,bb.ZMax],'curve':type(e.Curve).__name__,'vertices':[xyz(v.Point) for v in e.Vertexes]}
    if hasattr(e.Curve,'Radius'):r['radius']=e.Curve.Radius
    return r

def sth_edge_fingerprint_equal(a,b,tol=1e-6):
    if a['curve']!=b['curve'] or abs(a['length']-b['length'])>tol:return False
    if any(abs(x-y)>tol for k in ['center','bounds'] for x,y in zip(a[k],b[k])):return False
    if ('radius' in a)!=('radius' in b):return False
    if 'radius' in a and abs(a['radius']-b['radius'])>tol:return False
    if len(a['vertices'])!=len(b['vertices']):return False
    dist=lambda p,q:sth_em_math.sqrt(sum((x-y)**2 for x,y in zip(p,q)))
    ds=[min(dist(p,q) for q in b['vertices']) for p in a['vertices']]
    ds.extend(min(dist(p,q) for q in a['vertices']) for p in b['vertices'])
    return max(ds+[0])<=tol

def sth_occ_to_part(shape):
    if shape.IsNull():raise ValueError('Null OCC shape')
    f=sth_em_Part.Shape()
    f.importBrepFromString(sth_em_breptools.WriteToString(shape,True))
    return f

def sth_match_native_edge(reference,candidates,tol=1e-6,samples=33):
    fp=sth_edge_fingerprint(reference)
    found=[]
    for i,e in enumerate(candidates,1):
        if not sth_edge_fingerprint_equal(fp,sth_edge_fingerprint(e),tol):continue
        ds=[sth_em_Part.Vertex(p).distToShape(e)[0] for p in reference.discretize(Number=samples)]
        ds.extend(sth_em_Part.Vertex(p).distToShape(reference)[0] for p in e.discretize(Number=samples))
        d=max(ds+[0])
        if d<=tol:found.append((i,e,d))
    if len(found)!=1:raise ValueError('Expected unique edge; matches='+str([i for i,e,d in found]))
    return found[0]

def sth_reader_edge(reader,edge_id,base_brep_id=None):
    model=reader.StepModel()
    entity=model.Value(edge_id)
    if not entity.IsKind('StepShape_EdgeCurve'):raise ValueError('Not EDGE_CURVE #'+str(edge_id))
    if base_brep_id is not None:
        base=model.Value(base_brep_id)
        if not base.IsKind('StepShape_ManifoldSolidBrep'):raise ValueError('Anchor not MANIFOLD_SOLID_BREP')
        if not reader.TransferEntity(base):raise ValueError('Auxiliary BREP transfer failed')
    tp=reader.WS().TransferReader().TransientProcess()
    shape=sth_em_transferbrep.ShapeResult(tp,entity)
    if shape.IsNull():raise ValueError('STEP edge has no transferred geometry #'+str(edge_id))
    fc=sth_occ_to_part(shape)
    if len(fc.Edges)!=1:raise ValueError('STEP anchor did not transfer to one edge')
    return fc.Edges[0]

def sth_export_edge_entities(writer,fingerprints,tol=1e-6):
    # Finds real exported EDGE_CURVEs even when writer shape healing changed topology.
    # One isolated base-BREP writer per operation; no product outputs/files created.
    model=sth_em_Model.DownCast(writer.WS().Model())
    sw=sth_em_Writer(model);sw.SendModel(sth_em_Protocol.DownCast(model.Protocol()))
    text='\n'.join(sw.Line(i).ToCString() for i in range(1,sw.NbLines()+1))
    reader=sth_em_Reader()
    if int(reader.ReadStream('fillet-edge-anchors',text))!=1:raise ValueError('STEP self read failed')
    rm=reader.StepModel()
    breps=[i for i in range(1,rm.NbEntities()+1) if rm.Value(i).IsKind('StepShape_ManifoldSolidBrep')]
    if len(breps)!=1:raise ValueError('Expected exactly one auxiliary BREP, got '+str(breps))
    if not reader.TransferEntity(rm.Value(breps[0])):raise ValueError('Anchor BREP transfer failed')
    candidates=[]
    for i in range(1,rm.NbEntities()+1):
        if rm.Value(i).IsKind('StepShape_EdgeCurve'):
            e=sth_reader_edge(reader,i)
            candidates.append((i,e,sth_edge_fingerprint(e)))
    result=[]
    for fp in fingerprints:
        matches=[(i,e) for i,e,actual in candidates if sth_edge_fingerprint_equal(fp,actual,tol)]
        if len(matches)!=1:raise ValueError('Expected unique STEP edge for '+str(fp)+'; matches='+str([i for i,e in matches]))
        i,e=matches[0]
        original=model.Value(i)
        if not original.IsKind('StepShape_EdgeCurve'):raise ValueError('STEP serialization renumbered unexpected entity')
        result.append(original)
    return result

def sth_export_aux_brep(shape_path,fingerprints,tol=1e-6):
    from OCC.Core.STEPControl import STEPControl_Writer,STEPControl_AsIs
    fc=sth_em_Part.Shape();fc.read(shape_path)
    if fc.isNull() or not fc.isValid():raise ValueError('Invalid auxiliary shape '+shape_path)
    occ=sth_em_breptools.ReadFromString(fc.exportBrepToString())
    writer=STEPControl_Writer()
    if int(writer.Transfer(occ,STEPControl_AsIs))!=1:raise ValueError('Auxiliary STEP export failed')
    selected=sth_export_edge_entities(writer,fingerprints,tol)
    model=sth_em_Model.DownCast(writer.WS().Model())
    breps=[model.Value(i) for i in range(1,model.NbEntities()+1) if model.Value(i).IsKind('StepShape_ManifoldSolidBrep')]
    if len(breps)!=1:raise ValueError('Expected one auxiliary solid BREP')
    return {'model':model,'brep':breps[0],'selected_edges':selected,'writer':writer}


import os,re,json,hashlib,math
import FreeCAD as A,Part
from OCC.Core.STEPControl import STEPControl_Reader
from OCC.Core.TransferBRep import transferbrep

def sth_entity_closure(records,roots):
    todo=list(roots);seen=set()
    while todo:
        i=int(todo.pop())
        if i in seen:continue
        if i not in records:raise ValueError('Missing STEP #'+str(i))
        seen.add(i);todo.extend(sth_p21_refs(records[i][1]))
    return seen

def sth_decode_step(step_path):
    text=open(step_path,'r',encoding='utf-8',newline='').read()
    records=sth_p21_parse(text);sth_p21_validate_refs(records)
    def get(ref,kind=None):
        if not isinstance(ref,P21Ref):raise ValueError('Reference expected')
        t,a=records[int(ref)]
        if kind and t!=kind:raise ValueError('Expected '+kind+', got '+t)
        return a
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
    sequence=sa[1]
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
            axis=xyz(a[2],'DIRECTION');depth=float(a[3])
            if depth<=0 or not same(axis,pz):raise ValueError('Non-normal or negative extrusion unsupported')
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
                ca=get(ec[3],'CIRCLE');center,normal,u=placement(ca[1]);radius=float(ca[2])
                if radius<=0 or not same(center,po) or not same(normal,pz) or not same(u,px):raise ValueError('Circle plane mismatch')
                if not (same(axis,[0,0,1]) or same(axis,[1,0,0])):raise ValueError('Unsupported circular axis')
                vertex=xyz(get(ec[1],'VERTEX_POINT')[1],'CARTESIAN_POINT')
                if not same(vertex,[center[j]+radius*u[j] for j in range(3)]):raise ValueError('Circle vertex mismatch')
                op.update(type='cylinder',center=center,axis=axis,radius=radius,depth=depth)
            else:raise ValueError('Unsupported face loop '+lt)
        elif t=='CSG_SOLID':
            ba=get(a[1],'BOOLEAN_RESULT')
            if ba[0]!=name or str(ba[1]) not in ('UNION','DIFFERENCE','INTERSECTION'):raise ValueError('Unsupported boolean')
            if int(ba[2]) not in byentity or int(ba[3]) not in byentity:raise ValueError('Boolean operand must precede result')
            op.update(type=str(ba[1]).lower(),base=byentity[int(ba[2])]['id'],tool=byentity[int(ba[3])]['id'],refine=True)
        elif t=='SOLID_WITH_CONSTANT_RADIUS_EDGE_BLEND':
            base=int(a[2])
            if base not in byentity or base not in anchors:raise ValueError('Fillet base/anchor missing')
            radius=float(a[4]);edges=list(map(int,a[3]))
            if radius<=0 or not edges or len(set(edges))!=len(edges):raise ValueError('Invalid fillet selection')
            closure=sth_entity_closure(records,[anchors[base]])
            if not set(edges).issubset(closure):raise ValueError('Fillet edge outside anchored base')
            for e in edges:get(P21Ref(e),'EDGE_CURVE')
            op.update(type='fillet',base=byentity[base]['id'],radius=radius,step_edges=edges,base_brep=anchors[base])
        else:raise ValueError('Unsupported construction entity '+t)
        operations.append(op);names[name]=op;byentity[int(ref)]=op
    # No disconnected operations may silently disappear.
    needed=set()
    def visit(name):
        if name in needed:return
        needed.add(name);op=names[name]
        for k in ('base','tool'):
            if k in op:visit(op[k])
    visit(operations[-1]['id'])
    if needed!=set(names):raise ValueError('Disconnected construction operations')
    return {'text':text,'records':records,'operations':operations,'root':operations[-1]['id'],'sha256':hashlib.sha256(text.encode()).hexdigest(),'units':'mm','main_representation':int(links[0][3])}

def sth_shape_metrics(shape):
    bb=shape.BoundBox
    return {'valid':bool(shape.isValid()),'solids':len(shape.Solids),'volume_mm3':shape.Volume,'bbox_mm':[bb.XLength,bb.YLength,bb.ZLength]}

def sth_symdiff(a,b):
    return a.cut(b).Volume+b.cut(a).Volume

def sth_rebuild_step(step_path,fcstd_path=None,docname='AP242NativeRebuild'):
    decoded=sth_decode_step(step_path)
    reader=STEPControl_Reader()
    if int(reader.ReadStream('AP242 master',decoded['text']))!=1:raise ValueError('STEP read failed')
    model=reader.StepModel()
    roots=reader.NbRootsForTransfer()
    if roots!=1:raise ValueError('Expected one product transfer root; got '+str(roots))
    reader.TransferRoots()
    reference=sth_occ_to_part(reader.OneShape())
    ordinal={int(model.IdentLabel(model.Value(i))):i for i in range(1,model.NbEntities()+1)}
    if len(ordinal)!=model.NbEntities():raise ValueError('Ambiguous STEP labels')
    doc=A.newDocument(docname);objects={};proof=[];fillet_proofs=[]
    try:
        for op in decoded['operations']:
            kind=op['type'];name=op['id']
            if kind=='cylinder':
                o=doc.addObject('Part::Cylinder',name);o.Radius=op['radius'];o.Height=op['depth'];o.Angle=360
                o.Placement=A.Placement(A.Vector(*op['center']),A.Rotation(A.Vector(0,0,1),A.Vector(*op['axis'])))
            elif kind=='box':
                o=doc.addObject('Part::Box',name);o.Length=op['length'];o.Width=op['width'];o.Height=op['height'];o.Placement.Base=A.Vector(*op['origin'])
            elif kind in ('union','difference','intersection'):
                o=doc.addObject({'union':'Part::Fuse','difference':'Part::Cut','intersection':'Part::Common'}[kind],name)
                o.Base=objects[op['base']];o.Tool=objects[op['tool']];o.Refine=True
            elif kind=='fillet':
                base=objects[op['base']]
                entity=model.Value(ordinal[op['base_brep']])
                if not reader.TransferEntity(entity):raise ValueError('Fillet base transfer failed')
                tp=reader.WS().TransferReader().TransientProcess()
                anchor=sth_occ_to_part(transferbrep.ShapeResult(tp,entity))
                base_error=sth_symdiff(anchor,base.Shape)
                if base_error>1e-5:raise ValueError('Construction/base topology mismatch '+name+': '+str(base_error))
                selected=[];errors=[]
                for eid in op['step_edges']:
                    e=sth_reader_edge(reader,ordinal[eid])
                    index,native,error=sth_match_native_edge(e,base.Shape.Edges)
                    selected.append((index,op['radius'],op['radius']));errors.append(error)
                if len({e[0] for e in selected})!=len(selected):raise ValueError('Duplicate native fillet edge')
                o=doc.addObject('Part::Fillet',name);o.Base=base;o.Edges=selected
                fillet_proofs.append({'id':name,'base':op['base'],'radius':op['radius'],'step_edge_ids':op['step_edges'],'native_edges':[x[0] for x in selected],'anchor_symmetric_difference_mm3':base_error,'maximum_edge_distance_mm':max(errors)})
            else:raise ValueError(kind)
            o.addProperty('App::PropertyInteger','SourceStepEntity','STEP origin');o.SourceStepEntity=op['source_entity']
            o.addProperty('App::PropertyString','SourceStepType','STEP origin');o.SourceStepType=kind
            doc.recompute()
            if o.Shape.isNull() or not o.Shape.isValid() or not o.Shape.Solids:raise ValueError('Invalid operation '+name)
            if 'Error' in o.State:raise ValueError('Recompute error '+name)
            objects[name]=o;proof.append({'id':name,'native_type':o.TypeId,'step_entity':op['source_entity'],'valid':True,'volume_mm3':o.Shape.Volume})
        root=objects[decoded['root']]
        comparison=sth_symdiff(reference,root.Shape)
        if comparison>1e-5 or len(root.Shape.Solids)!=1:raise ValueError('Final STEP reconstruction mismatch '+str(comparison))
        for o in objects.values():
            if o.ViewObject:o.ViewObject.Visibility=(o is root)
        report={'GuiUp':A.GuiUp,'step_sha256':decoded['sha256'],'operations':len(objects),'root':root.Name,'single_product_transfer_roots':roots,'units':'mm','boolean_refine_policy':True,'native_operations':proof,'fillets':fillet_proofs,'shape':sth_shape_metrics(root.Shape),'reference':sth_shape_metrics(reference),'symmetric_difference_mm3':comparison,'operation_graph_sha256':hashlib.sha256(json.dumps(decoded['operations'],sort_keys=True,separators=(',',':')).encode()).hexdigest(),'source_inputs':[os.path.abspath(step_path)],'native_source_or_contract_used':False}
        if fcstd_path:doc.saveAs(fcstd_path)
        return doc,root,objects,report,decoded
    except:
        A.closeDocument(doc.Name)
        raise

```

Entry point: `sth_rebuild_step(step_path, fcstd_path=None)`. It returns the document, final feature, feature map, proof report, and decoded neutral operations.

## Verification for the current input

Define parameter-change tests in the run test policy before reconstruction.
Use operation IDs and expected results from independent permitted evidence.
Do not use values from a previous part or infer an expected result from the changed model.

1. Reconstruct from STEP alone in a new headless process.
2. Compare the operation graph, nominal parameters, and geometry with independent expected data.
3. Change one permitted parameter and recompute all dependent operations.
4. Compare the changed geometry with the expected result under the defined tolerances.
5. Restore the parameter and verify the original geometry.
6. Apply the selected change again, recompute, and verify the expected changed geometry.
7. Export an edited AP242 candidate with the updated operation graph.
8. Import that candidate in another new headless process.
9. Verify construction, parameters, geometry, original PMI, and review markers separately.

Record `GuiUp=0`, input and output hashes, tool versions, and actual test results.
A successful geometry reconstruction does not prove automatic PMI updates after an edit.
This reference contains no ready-made case oracle and no current release evidence.

## Reuse boundary

The export and import functions implement only the stated entity subset.
They preserve existing PMI entities during the initial append operation.
They do not create semantic PMI from a drawing or update PMI after parameter changes.
A separately verified PMI writer is necessary for those operations.

The adapter restores explicit operations and nominal parameters. It does not claim:

- Recovery of undeclared design constraints.
- Universal topological naming under arbitrary edits.
- Full EXPRESS validation.
- Tested adapters for other CAD systems.
