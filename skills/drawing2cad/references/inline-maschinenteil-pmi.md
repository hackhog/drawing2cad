# Maschinenteil: tested inline PMI export

This evidence applies only to the approved drawing `Maschinenteil_dwg.pdf`, SHA-256 `21bdfbfe9adf3d23245759c1a3855465123ef4a60268cc54b9a1474286bf8c36`. Do not reuse its geometry or dimensions for other parts.

The Python block is documentation. Send it as a string through the FreeCAD proxy of `drawing2cad-mcp`. Supply the string to standard input of a hidden `FreeCADCmd -c` process. Do not create `.py` files, macros, or other executable script files.

## Verified result

The final visual check used model contract Revision04, SHA-256 `839f88e17b19721062b37af50882caed8b1ca9a2da343f69371d4eb4be487c01`. The PMI candidate before construction-tree addition had SHA-256 `2fbbd17f39d0be9f1c48afc78d129a82d1a08185edc3f2003af4063ae0874b8c`. The code loads the current contract file. These hashes identify the specific verified run.

FreeCAD 1.1.4 / OCCT 7.8.1 produced 29 numeric PMI, 2 manufacturing properties linked to geometry, and 31 tessellated presentations. All 31 presentations are in the STEP file. A fresh XCAF import verified all 29 values and the presentations.

The symmetric-difference solid between exported geometry and the native model has volume 0 mm³. The fixed limit is 1e-5 mm³. A separate volume integration differs by -0.0005555709 mm³. Do not interpret this integration difference as a geometry difference. Do not change the frozen geometry limit after the test.

M10 is a semantic thread designation linked to a real cylindrical face through `PROPERTY_DEFINITION_REPRESENTATION`. It is not a fully typed thread feature. Pitch and tolerance class are unknown. The general R1 note also contains a typed length dimension of 1 mm. It is linked to all modeled R1 faces. User assumptions use `metadata_id`. Original drawing PMI use `source_id`.

## Implementation details

- In this PythonOCC version, `STEPCAFControl_Writer.Write` returns `bool`. Do not compare it with `IFSelect_RetDone`. `ReadFile` still returns that status enumeration.
- Without a graphical shape, XCAF `DimensionPresentation` creates real ShapeAspects/GISUs here, but no numeric dimension. These become targets for the two manufacturing properties and the assumptions. Do not count them as additional drawing dimensions.
- For manually constructed properties, explicitly add the DraughtingModel, AnnotationPlane, Callout, and Occurrence entities with `AddWithRefs`. Adding only the association can produce an unknown Representation reference and missing planes.
- In this binding, the generic `IsKind(get_type_descriptor())` search returned unsuitable matches. Select ShapeAspect subtypes by their exact `DynamicType().Name()`. Then downcast with the applicable concrete class.
- The bolt circle and angles use Circle and Line entities derived from real hole axes. They use `SHAPE_ASPECT_DERIVING_RELATIONSHIP`, not invented physical cylindrical faces.
- The export writes `Maschinenteil_PMI_Spezifikation.json`. It contains complete face signatures, reference lists, derived reference points and geometry, planes, text anchors, dimension layout, and graphical polylines. Add this specification to the parent model contract before the final hash freeze.
- Use an independent STEP parser for the visibility check. Each of the 31 DMIA must connect the correct semantics, named callouts, AnnotationPlane, and TessellatedAnnotationOccurrence. Create the native FreeCAD view from these actual STEP polylines.

## Inline code

```python
import os, math, json, hashlib
import FreeCAD as App, Part
from OCC.Core.TDocStd import TDocStd_Document
from OCC.Core.TCollection import TCollection_HAsciiString
from OCC.Core.TDataStd import TDataStd_Name
from OCC.Core.TDF import TDF_LabelSequence,TDF_Label
from OCC.Core.XCAFDoc import XCAFDoc_DocumentTool,XCAFDoc_Dimension
from OCC.Core.XCAFDimTolObjects import *
from OCC.Core.STEPCAFControl import STEPCAFControl_Writer,STEPCAFControl_Reader,STEPCAFControl_GDTProperty
from OCC.Core.STEPControl import STEPControl_AsIs,STEPControl_Reader
from OCC.Core.Interface import Interface_Static
from OCC.Core.IFSelect import IFSelect_RetDone
from OCC.Core.gp import gp_Pnt,gp_Dir,gp_Ax2
from OCC.Core.TopExp import TopExp_Explorer
from OCC.Core.TopAbs import TopAbs_SOLID,TopAbs_FACE
from OCC.Core.TopoDS import topods
from OCC.Core.StepData import StepData_LFalse,StepData_LTrue
from OCC.Core.TColStd import TColStd_HArray1OfReal
from OCC.Core.StepGeom import *
from OCC.Core.StepRepr import *
from OCC.Core.StepShape import StepShape_AngularLocation,StepShape_DimensionalCharacteristicRepresentation,StepShape_DimensionalSize
from OCC.Core.StepAP242 import *
from OCC.Core.StepVisual import *
from OCC.Core.StepBasic import StepBasic_MeasureValueMember,StepBasic_MeasureWithUnit
from OCC.Core.STEPConstruct import stepconstruct
out='C:/Users/mail/Projects/hackhog/drawing2cad/output/cad/Maschinenteil/97778b9a'
contract=json.load(open(out+'/Maschinenteil_Modellvertrag.json',encoding='utf-8'))
native=App.openDocument(out+'/Maschinenteil_Konstruktion.FCStd')
fcshape=native.getObject('CrossBoreCut3').Shape
assert App.GuiUp==0 and fcshape.isValid() and len(fcshape.Solids)==1
assert len(fcshape.Faces)==74 and abs(fcshape.Volume-68474.48859372552)<1e-6
H=TCollection_HAsciiString
V=App.Vector
def close(a,b,tol=1e-6):return abs(a-b)<tol
def chkplane(i,axis,value):
 s=fcshape.Faces[i-1].Surface
 assert type(s).__name__=='Plane' and close(abs(s.Axis[axis]),1) and close(s.Position[axis],value),(i,axis,value)
def chkcyl(i,r,center,axis=2):
 s=fcshape.Faces[i-1].Surface
 assert type(s).__name__=='Cylinder' and close(s.Radius,r) and close(abs(s.Axis[axis]),1),(i,r)
 assert all(close(s.Center[j],center[j]) for j in range(3) if j!=axis),(i,center)
for i,ax,n in [(2,2,34),(3,2,49),(5,0,7),(6,0,-7),(7,1,0),(8,1,0),(9,0,15),(10,0,-15),(11,1,-7.5),(12,2,19),(27,1,-17.5),(29,1,17.5),(30,1,-17.5),(31,2,4),(32,1,17.5),(34,0,42),(35,0,42),(41,0,-42),(42,1,-7.5),(44,1,-7.5),(48,0,30),(49,1,7.5),(51,0,-42),(52,1,7.5),(56,0,-45),(74,2,0)]:chkplane(i,ax,n)
chkcyl(1,5,(0,9,0));chkcyl(17,25,(0,0,0))
for i,z in [(13,21.5),(14,26.5),(15,31.5)]:chkcyl(i,1.25,(0,-3.5,z),0)
flangeholes=[57,58,59,60,61,63,64,66,67,68]
for i in flangeholes:
 s=fcshape.Faces[i-1].Surface
 assert close(s.Radius,5) and close(math.hypot(s.Center.x,s.Center.y),38)
for i,x in [(62,-36),(65,36)]:chkcyl(i,2.5,(x,0,0))
for i in [54,55]:chkcyl(i,50,(0,0,0))
rootround=[18,19,20,21,22,23,24,25,26]
for i in rootround+[16]:
 s=fcshape.Faces[i-1].Surface
 assert close(s.MinorRadius if type(s).__name__=='Toroid' else s.Radius,2)
r1faces=[36,37,38,39,40,43,46,47,50,69,70,71,72,73]
for i in r1faces:
 s=fcshape.Faces[i-1].Surface
 assert close(s.MinorRadius if type(s).__name__=='Toroid' else s.Radius,1)
refs={
'MP01':([17,66],[17,64]),'MP02':([17,64],[17,63]),'MP03':(flangeholes,[]),'MP04':(flangeholes,[]),
'MP05':([54,55],[]),'MP06':([27,30],[29,32]),'MP07':([42],[49]),'MP08':([62,65],[]),
'MP09':([17],[1]),'MP10':([10],[9]),'MP11':([48],[34,35]),'MP12':([41,51],[17]),
'MP13':([17],[65]),'MP14':([56],[17]),'MP15':([74,31],[]),'MP16':([31],[12]),
'MP17':([12],[2]),'MP18':([2],[3]),'MP19':([11],[13]),'MP20':([12],[13]),
'MP21':([13],[14]),'MP22':([14],[15]),'MP23':([6],[5]),'MP24':([7,8],[1]),
'MP25':([11,7,8],[]),'MP26':([10],[9]),'MP27':(rootround,[]),'MP28':([16],[]),
'MP29':([1],[]),'MP30':([17],[]),'MP31':(r1faces,[])}
points={
'MP09':[(0,0,34),(0,9,34)],'MP12':[(-42,0,6),(0,0,6)],'MP13':[(0,0,2),(36,0,2)],
'MP14':[(-45,0,2),(0,0,2)],'MP19':[(0,-7.5,21.5),(0,-3.5,21.5)],
'MP20':[(0,-3.5,19),(0,-3.5,21.5)],'MP21':[(0,-3.5,21.5),(0,-3.5,26.5)],
'MP22':[(0,-3.5,26.5),(0,-3.5,31.5)],'MP24':[(0,0,34),(0,9,34)]}
for id,p in points.items():
 expected=next(r['value'] for r in contract['pmi'] if r['id']==id)
 assert close((V(*p[1])-V(*p[0])).Length,expected)
# Presentation is polygonized explicitly before OCC tessellation.
frames={
'front':(V(0,0,65),V(1,0,0),V(0,1,0)),
'side':(V(-65,0,0),V(0,0,1),V(0,1,0)),
'detail_A':(V(0,0,72),V(1,0,0),V(0,1,0)),
'bottom':(V(0,65,0),V(1,0,0),V(0,0,-1)),
'general_note':(V(0,0,65),V(1,0,0),V(0,1,0))}
graphics={}
def build_graphic(id,view,literal,mode,data):
 origin,u,v=frames[view];polys=[]
 def world(p):return origin+u*p[0]+v*p[1]
 def line(a,b):
  if math.hypot(a[0]-b[0],a[1]-b[1])>1e-7:polys.append([world(a),world(b)])
 def arrow(tip,inside):
  dx,dy=inside[0]-tip[0],inside[1]-tip[1];n=math.hypot(dx,dy);dx/=n;dy/=n
  q=(tip[0]+1.65*dx,tip[1]+1.65*dy)
  a=(q[0]-0.5*dy,q[1]+0.5*dx);b=(q[0]+0.5*dy,q[1]-0.5*dx)
  line(tip,a);line(a,b);line(b,tip)
 def text_at(text,p,angle=0,height=2.7):
  chars=Part.makeWireString(text,'C:/Windows/Fonts/','arial.ttf',height)
  shape=Part.makeCompound([w for char in chars for w in char])
  bb=shape.BoundBox;shape.translate(V(-.5*(bb.XMin+bb.XMax),-.5*(bb.YMin+bb.YMax),0))
  ca,sa=math.cos(angle),math.sin(angle)
  for edge in shape.Edges:
   pts=edge.discretize(Deflection=0.012)
   transformed=[]
   for pt in pts:
    transformed.append(world((p[0]+ca*pt.x-sa*pt.y,p[1]+sa*pt.x+ca*pt.y)))
   if len(transformed)>1:polys.append(transformed)
 if mode=='h':
  x1,x2,y1,y2,offset=data;a=(x1,offset);b=(x2,offset)
  line((x1,y1),(x1,offset+1 if offset>y1 else offset-1));line((x2,y2),(x2,offset+1 if offset>y2 else offset-1))
  line(a,b);arrow(a,b);arrow(b,a);label=((x1+x2)/2,offset+3.3 if offset>max(y1,y2) else offset-3.3)
  text_at(literal,label)
 elif mode=='v':
  y1,y2,x1,x2,offset=data;a=(offset,y1);b=(offset,y2)
  line((x1,y1),(offset+1 if offset>x1 else offset-1,y1));line((x2,y2),(offset+1 if offset>x2 else offset-1,y2))
  line(a,b);arrow(a,b);arrow(b,a);label=(offset+3.1 if offset>max(x1,x2) else offset-3.1,(y1+y2)/2)
  text_at(literal,label,math.pi/2)
 elif mode=='leader':
  a,b,label=data;line(a,b);line(b,(label[0]-5 if label[0]>b[0] else label[0]+5,label[1]));arrow(a,b);text_at(literal,label)
 elif mode=='angle':
  a1,a2,r=data
  p1=(r*math.cos(math.radians(a1)),r*math.sin(math.radians(a1)));p2=(r*math.cos(math.radians(a2)),r*math.sin(math.radians(a2)))
  for ang in [a1,a2]:line((38*math.cos(math.radians(ang)),38*math.sin(math.radians(ang))),((r+2)*math.cos(math.radians(ang)),(r+2)*math.sin(math.radians(ang))))
  curve=[(r*math.cos(math.radians(a1+(a2-a1)*j/35)),r*math.sin(math.radians(a1+(a2-a1)*j/35))) for j in range(36)]
  for a,b in zip(curve,curve[1:]):line(a,b)
  arrow(curve[0],curve[2]);arrow(curve[-1],curve[-3]);amid=math.radians((a1+a2)/2)
  label=((r+5)*math.cos(amid),(r+5)*math.sin(amid));text_at(literal,label,amid-math.pi/2)
 else:label=data;text_at(literal,label,height=2.8)
 if id=='MP04':
  # Graphic-only derived pitch circle; semantics refer to the real hole axes.
  for dash in range(48):
   arc=[(38*math.cos(math.radians(dash*7.5+j*3.75/6)),38*math.sin(math.radians(dash*7.5+j*3.75/6))) for j in range(7)]
   polys.append([world(p) for p in arc])
 shape=Part.makeCompound([Part.makePolygon(p) for p in polys])
 graphics[id]={'shape':shape,'polylines':[[list(p) for p in poly] for poly in polys],
  'view':view,'label_point':list(world(label)),'normal':list(u.cross(v)),'x_axis':list(u),'literal':literal}
 if id=='MP04':graphics[id]['auxiliary_graphics']={'type':'dashed derived pitch circle','radius_mm':38.,'center':[0.,0.,65.],'dash_count':48,'dash_degrees':3.75,'gap_degrees':3.75,'subdivisions_per_dash':6}
layout={
'MP01':('angle',(90,115.5,63)),'MP02':('angle',(115.5,141,63)),
'MP03':('leader',((0,43),(-10,60),(-7,77))),'MP04':('leader',((16,34.47),(23,57),(29,65))),
'MP05':('leader',((36,34.7),(51,52),(57,58))),
'MP06':('v',(-17.5,17.5,-42,-42,-66)),'MP07':('v',(-7.5,7.5,-42,-42,-54)),
'MP08':('leader',((-36,0),(-49,-13),(-61,-28))),
'MP09':('v',(0,9,0,0,20)),'MP10':('h',(-15,15,-7.5,-7.5,-58)),
'MP11':('h',(30,42,-7.5,-17.5,-58)),'MP12':('h',(-42,0,-17.5,0,-69)),
'MP13':('h',(0,36,0,0,-69)),'MP14':('h',(-45,0,0,0,-80)),
'MP15':('h',(0,4,50,50,61)),'MP16':('h',(4,19,25,23,61)),
'MP17':('h',(19,34,23,16,61)),'MP18':('h',(34,49,14,14,61)),
'MP19':('v',(-7.5,-3.5,34,31.5,58)),'MP20':('h',(19,21.5,-7.5,-3.5,-25)),
'MP21':('h',(21.5,26.5,-3.5,-3.5,-17)),'MP22':('h',(26.5,31.5,-3.5,-3.5,-17)),
'MP23':('h',(-7,7,9,9,25)),'MP24':('v',(0,9,15,0,24)),
'MP25':('v',(-7.5,0,15,15,24)),'MP26':('h',(-15,15,-7.5,-7.5,-18)),
'MP27':('leader',((25.6,-9.6),(38,-5),(50,-15))),
'MP28':('leader',((24.4,-18.4),(36,-27),(44,-30))),
'MP29':('leader',((5,-42),(21,-48),(30,-52))),
'MP30':('h',(-25,25,-14,-14,-64)),
'MP31':('text',(-8,-95))}
for row in contract['pmi']:
 mode,data=layout[row['id']];build_graphic(row['id'],row['view'],row['literal'],mode,data)
print('GRAPHICS_BUILT',len(graphics),flush=True)
shape=Part.__toPythonOCC__(fcshape.Solids[0])
xd=TDocStd_Document('BinXCAF');st=XCAFDoc_DocumentTool.ShapeTool(xd.Main());dt=XCAFDoc_DocumentTool.DimTolTool(xd.Main())
root=st.AddShape(shape,False);TDataStd_Name.Set(root,'Maschinenteil')
if st.IsReference(root):
 actual=TDF_Label();st.GetReferredShape(root,actual);root=actual
fl={};occfaces={}
shape=st.GetShape(root)
ex=TopExp_Explorer(shape,TopAbs_FACE);i=0
while ex.More():
 i+=1;occfaces[i]=topods.Face(ex.Current());fl[i]=st.AddSubShape(root,occfaces[i]);assert not fl[i].IsNull(),i
 TDataStd_Name.Set(fl[i],'Face'+str(i));ex.Next()
assert i==74
def seq(ids):
 a=TDF_LabelSequence()
 for i in ids:a.Append(fl[i])
 return a
for row in contract['pmi']:
 id=row['id']
 if id in ['MP29','MP31']:continue
 kindname=row['suggested_type']
 if id=='MP28':kindname='Size_ToroidalMinorRadius'
 dl=dt.AddDimension();obj=XCAFDimTolObjects_DimensionObject()
 obj.SetType(globals()['XCAFDimTolObjects_DimensionType_'+kindname])
 obj.SetValue(math.radians(row['value']) if row['unit']=='deg' else row['value'])
 obj.SetSemanticName(H(row['meaning']))
 for name,value in [('source_id',id),('source','Maschinenteil_dwg.pdf; drawing revision A; no tolerance supplied'),('drawing_literal',row['literal']),('drawing_view',row['view'])]:
  obj.AddDescription(H(value),H(name))
 if id in points:obj.SetPoint(gp_Pnt(*points[id][0]));obj.SetPoint2(gp_Pnt(*points[id][1]))
 g=graphics[id];obj.SetPresentation(Part.__toPythonOCC__(g['shape']),H(id+'_'+g['view']))
 obj.SetPlane(gp_Ax2(gp_Pnt(*g['label_point']),gp_Dir(*g['normal']),gp_Dir(*g['x_axis'])))
 obj.SetPointTextAttach(gp_Pnt(*g['label_point']))
 XCAFDoc_Dimension.Set(dl).SetObject(obj);TDataStd_Name.Set(dl,'DGT:Dimension '+id+' '+row['meaning'])
 dt.SetDimension(seq(refs[id][0]),seq(refs[id][1]),dl)
# Presentation-only XCAF links provide actual BREP ShapeAspects without numeric dimensions.
source_only_refs={'MP29':refs['MP29'][0],'MP31':refs['MP31'][0],
 'ASSUMPTION_PAD_THICKNESS':[28,33,31],'ASSUMPTION_CROSS_BORE':[13,14,15],'ASSUMPTION_THREAD_GEOMETRY':[1,3]}
for source_id,source_faces in source_only_refs.items():
 dl=dt.AddDimension();obj=XCAFDimTolObjects_DimensionObject()
 obj.SetType(XCAFDimTolObjects_DimensionType_DimensionPresentation)
 obj.SetSemanticName(H(source_id))
 XCAFDoc_Dimension.Set(dl).SetObject(obj);TDataStd_Name.Set(dl,'DGT:Dimension '+source_id)
 dt.SetDimension(seq(source_faces),seq([]),dl)
writer=STEPCAFControl_Writer()
assert Interface_Static.SetCVal('write.step.schema','AP242DIS')
Interface_Static.SetCVal('write.step.unit','MM')
writer=STEPCAFControl_Writer();writer.SetDimTolMode(True);writer.SetNameMode(True)
assert writer.Transfer(xd,STEPControl_AsIs)
model=writer.ChangeWriter().Model()
def entities(typename):return [model.Value(i) for i in range(1,model.NbEntities()+1) if model.Value(i).DynamicType().Name()==typename]
def real3(values):
 arr=TColStd_HArray1OfReal(1,3)
 for i,val in enumerate(values,1):arr.SetValue(i,float(val))
 return arr
def items(values):
 arr=StepRepr_HArray1OfRepresentationItem(1,len(values))
 for i,val in enumerate(values,1):arr.SetValue(i,val)
 return arr
def pnt(values,name=''):
 o=StepGeom_CartesianPoint();o.Init(H(name),real3(values));return o
def direction(values):
 o=StepGeom_Direction();o.Init(H(''),real3(values));return o
def axis2(origin,normal=(0,0,1),xref=(1,0,0)):
 o=StepGeom_Axis2Placement3d();o.Init(H(''),pnt(origin),True,direction(normal),True,direction(xref));return o
def find_dimension(id):
 for raw in entities('StepShape_DimensionalCharacteristicRepresentation'):
  dcr=StepShape_DimensionalCharacteristicRepresentation.DownCast(raw);rep=dcr.Representation()
  for i in range(1,rep.NbItems()+1):
   it=rep.ItemsValue(i)
   if it.DynamicType().Name()=='StepRepr_DescriptiveRepresentationItem':
    it=StepRepr_DescriptiveRepresentationItem.DownCast(it)
    if it.Name().ToCString()=='source_id' and it.Description().ToCString()==id:return dcr
 raise RuntimeError('Missing dimension '+id)
sample=find_dimension('MP03').Dimension().DimensionalSize().AppliesTo()
pds=sample.OfShape()
brep_rep=None
for raw in entities('StepAP242_GeometricItemSpecificUsage'):
 usage=StepAP242_GeometricItemSpecificUsage.DownCast(raw)
 if usage.UsedRepresentation().DynamicType().Name()=='StepShape_AdvancedBrepShapeRepresentation':brep_rep=usage.UsedRepresentation();break
assert brep_rep is not None
context=brep_rep.ContextOfItems()
def add_usage(name,aspect,rep,geometry):
 definition=StepAP242_ItemIdentifiedRepresentationUsageDefinition();definition.SetValue(aspect)
 usage=StepAP242_GeometricItemSpecificUsage();usage.Init(H(name),H(''),definition,rep,items(geometry));model.AddWithRefs(usage)
 return usage
def derive(name,geometry,sources):
 supp=StepRepr_ConstructiveGeometryRepresentation();supp.Init(H(name+'_geometry'),items([geometry]),context)
 link=StepRepr_ConstructiveGeometryRepresentationRelationship();link.Init(H(name+'_link'),H('Geometry derived from actual feature axes'),brep_rep,supp);model.AddWithRefs(link)
 aspect=StepRepr_DerivedShapeAspect();aspect.Init(H(name),H('Derived geometry; not a material surface'),pds,StepData_LFalse)
 for source in sources:
  rel=StepRepr_ShapeAspectDerivingRelationship();rel.Init(H('derived from'),False,H(''),aspect,source);model.AddWithRefs(rel)
 add_usage(name+'_usage',aspect,supp,[geometry]);return aspect
def radial(name,end):
 vec=V(*end)-V(0,0,2);n=vec.Length;vec=vec/n
 axis=StepGeom_Vector();axis.Init(H(''),direction(list(vec)),1.)
 ln=StepGeom_Line();ln.Init(H(name),pnt((0,0,2)),axis);return ln
angles={}
for id,a,b in [('MP01',66,64),('MP02',64,63)]:
 dcr=find_dimension(id);angle=StepShape_AngularLocation.DownCast(dcr.Dimension().DimensionalLocation())
 old=[angle.RelatingShapeAspect(),angle.RelatedShapeAspect()]
 ends=[list(fcshape.Faces[i-1].Surface.Center) for i in [a,b]]
 for p in ends:p[2]=2
 vectors=[V(*p)-V(0,0,2) for p in ends]
 measured=math.degrees(math.acos(vectors[0].dot(vectors[1])/(vectors[0].Length*vectors[1].Length)))
 assert close(measured,25.5);angles[id]=measured
 derived=[derive(id+'_radial_'+str(j+1),radial(id+'_line_'+str(j+1),end),[old[j]]) for j,end in enumerate(ends)]
 angle.SetRelatingShapeAspect(derived[0]);angle.SetRelatedShapeAspect(derived[1]);model.AddWithRefs(angle,0,True)
dcr=find_dimension('MP04');dim=StepShape_DimensionalSize.DownCast(dcr.Dimension().DimensionalSize())
circle=StepGeom_Circle();placement=StepGeom_Axis2Placement();placement.SetValue(axis2((0,0,2)))
circle.Init(H('MP04_pitch_circle'),placement,38.)
pcd=derive('MP04_derived_pitch_circle',circle,[dim.AppliesTo()]);dim.SetAppliesTo(pcd);model.AddWithRefs(dim,0,True)
# Manufacturing text properties with standard property/representation/presentation linkage.
styles=StepVisual_TessellatedAnnotationOccurrence.DownCast(entities('StepVisual_TessellatedAnnotationOccurrence')[0]).Styles()
finder=writer.ChangeWriter().WS().TransferWriter().FinderProcess()
def descriptive(name,value):
 o=StepRepr_DescriptiveRepresentationItem();o.Init(H(name),H(value));return o
def find_source_aspect(id):
 candidates=[globals()[model.Value(i).DynamicType().Name()].DownCast(model.Value(i)) for i in range(1,model.NbEntities()+1) if model.Value(i).DynamicType().Name() in ['StepRepr_ShapeAspect','StepRepr_CompositeShapeAspect','StepRepr_DerivedShapeAspect']]
 candidates=[x for x in candidates if x.Name() is not None and id in x.Name().ToCString()]
 if not candidates:
  print('ASPECT_NAMES',[(x.DynamicType().Name(),x.Name().ToCString()) for x in [globals()[model.Value(i).DynamicType().Name()].DownCast(model.Value(i)) for i in range(1,model.NbEntities()+1) if model.Value(i).DynamicType().Name() in ['StepRepr_ShapeAspect','StepRepr_CompositeShapeAspect','StepRepr_DerivedShapeAspect']]],flush=True)
  raise RuntimeError('Missing source-only aspect '+id)
 return next((x for x in candidates if x.DynamicType().Name()=='StepRepr_CompositeShapeAspect'),candidates[0])
def add_note(row):
 id=row['id'];g=graphics[id]
 aspect=find_source_aspect(id)
 characterized=StepRepr_CharacterizedDefinition();characterized.SetValue(aspect)
 prop=StepRepr_PropertyDefinition();prop.Init(H('thread specification' if id=='MP29' else 'general radius rule'),True,H(row['literal']),characterized)
 data=[descriptive('source_id',id),descriptive('drawing_literal',row['literal']),descriptive('source','Maschinenteil_dwg.pdf; drawing revision A'),descriptive('meaning',row['meaning'])]
 if id=='MP29':
  data.extend([descriptive('thread designation','M10'),descriptive('representation','nominal cylinder; user-approved simplified thread')])
 else:
  sampleitem=find_dimension('MP03').Representation().ItemsValue(1)
  measureitem=StepRepr_ReprItemAndLengthMeasureWithUnit.DownCast(sampleitem)
  unit=measureitem.GetMeasureWithUnit().UnitComponent()
  val=StepBasic_MeasureValueMember();val.SetName('POSITIVE_LENGTH_MEASURE');val.SetReal(1.)
  mwu=StepBasic_MeasureWithUnit();mwu.Init(val,unit)
  ri=StepRepr_RepresentationItem();ri.Init(H('general radius'))
  typed=StepRepr_ReprItemAndLengthMeasureWithUnit();typed.Init(mwu,ri);data.append(typed)
 rep=StepRepr_Representation();rep.Init(H(id+'_manufacturing_property'),items(data),context)
 represented=StepRepr_RepresentedDefinition();represented.SetValue(prop)
 pdr=StepRepr_PropertyDefinitionRepresentation();pdr.Init(represented,rep);model.AddWithRefs(pdr)
 tess=STEPCAFControl_GDTProperty.GetTessellation(Part.__toPythonOCC__(g['shape']))
 occurrence=StepVisual_TessellatedAnnotationOccurrence();occurrence.Init(H(''),styles,tess)
 ce=StepVisual_DraughtingCalloutElement();ce.SetValue(occurrence)
 ces=StepVisual_HArray1OfDraughtingCalloutElement(1,1);ces.SetValue(1,ce)
 callout=StepVisual_DraughtingCallout();callout.Init(H(id+'_'+g['view']),ces)
 planegeom=StepGeom_Plane();planegeom.Init(H(''),axis2(g['label_point'],g['normal'],g['x_axis']))
 pe=StepVisual_AnnotationPlaneElement();pe.SetValue(callout)
 pes=StepVisual_HArray1OfAnnotationPlaneElement(1,1);pes.SetValue(1,pe)
 plane=StepVisual_AnnotationPlane();plane.Init(H(''),styles,planegeom,pes)
 dm=StepVisual_DraughtingModel();dm.Init(H(id+'_presentation'),items([callout,plane]),context)
 definition=StepAP242_ItemIdentifiedRepresentationUsageDefinition();definition.SetValue(prop)
 association=StepAP242_DraughtingModelItemAssociation();association.Init(H('manufacturing property to presentation link'),H(''),definition,dm,items([callout]))
 model.AddWithRefs(occurrence);model.AddWithRefs(callout);model.AddWithRefs(plane);model.AddWithRefs(dm);model.AddWithRefs(association)
 return {'id':id,'property':model.Number(prop),'association':model.Number(association),'type':'geometrically linked textual manufacturing property'}
notes=[add_note(row) for row in contract['pmi'] if row['id'] in ['MP29','MP31']]

def add_metadata(mid,name,data,target_faces=(),length_value=None,length_name='nominal value'):
 target=pds
 if target_faces:
  target=find_source_aspect(mid)
 cd=StepRepr_CharacterizedDefinition();cd.SetValue(target)
 prop=StepRepr_PropertyDefinition();prop.Init(H(name),True,H('Not an original drawing dimension'),cd)
 values=[descriptive('metadata_id',mid)]+[descriptive(str(k),str(v)) for k,v in data.items()]
 if length_value is not None:
  sample=StepRepr_ReprItemAndLengthMeasureWithUnit.DownCast(find_dimension('MP03').Representation().ItemsValue(1))
  mv=StepBasic_MeasureValueMember();mv.SetName('POSITIVE_LENGTH_MEASURE');mv.SetReal(length_value)
  mw=StepBasic_MeasureWithUnit();mw.Init(mv,sample.GetMeasureWithUnit().UnitComponent())
  ri=StepRepr_RepresentationItem();ri.Init(H(length_name))
  typed=StepRepr_ReprItemAndLengthMeasureWithUnit();typed.Init(mw,ri);values.append(typed)
 rep=StepRepr_Representation();rep.Init(H(mid+'_representation'),items(values),context)
 rd=StepRepr_RepresentedDefinition();rd.SetValue(prop)
 pr=StepRepr_PropertyDefinitionRepresentation();pr.Init(rd,rep);model.AddWithRefs(pr)
 return {'id':mid,'property_entity':model.Number(prop)}
metadata=[
 add_metadata('ASSUMPTION_PAD_THICKNESS','raised pad thickness',{'status':'user_confirmed_assumption','value_mm':'5','evidence':'Not dimensioned in drawing; explicitly approved by user'},[28,33,31],5.,'pad thickness'),
 add_metadata('ASSUMPTION_CROSS_BORE','cross drilling diameter',{'status':'user_confirmed_assumption','value_mm':'2.5','evidence':'Diameter absent from drawing; explicitly approved by user'},[13,14,15],2.5,'cross bore diameter'),
 add_metadata('ASSUMPTION_THREAD_GEOMETRY','thread geometric representation',{'status':'user_confirmed_assumption','representation':'nominal cylinder with M10 manufacturing property','thread_end_chamfer':'omitted; not dimensioned','pitch':'unspecified','tolerance_class':'unspecified'},[1,3]),
 add_metadata('SOURCE_PROVENANCE','drawing and contract provenance',{'drawing':'Maschinenteil_dwg.pdf','drawing_sha256':contract['sources'][0]['sha256'],'drawing_revision':'A','contract_revision':contract['revision'],'contract_sha256':contract['contract_sha256'],'only_model_source':'specified Maschinenteil_dwg.pdf','generator':'FreeCAD 1.1.4 / OCCT 7.8.1 / freecad-ap242 via MCP inline code'})]
face_signatures={}
for i,f in enumerate(fcshape.Faces,1):
 s=f.Surface;b=f.BoundBox
 d={'type':type(s).__name__,'area':f.Area,'center_of_mass':list(f.CenterOfMass),'bbox':[b.XMin,b.YMin,b.ZMin,b.XMax,b.YMax,b.ZMax]}
 for k in ['Radius','MajorRadius','MinorRadius','Axis','Center','Position']:
  if hasattr(s,k):
   val=getattr(s,k);d[k]=list(val) if hasattr(val,'x') else float(val)
 face_signatures[str(i)]=d
specification={'schema':'maschinenteil-pmi-layout-v1','native_final_object':'CrossBoreCut3','contract_revision':contract['revision'],
 'contract_sha256':contract['contract_sha256'],'source_pdf_sha256':contract['sources'][0]['sha256'],
 'face_selection':'Checked final-face indices plus complete analytic signatures; never infer from names alone',
 'face_signatures':face_signatures,'native_refs':refs,'derived_points':points,
 'derived_angles':{'MP01':{'origin':[0,0,2],'source_faces':[[17,66],[17,64]]},'MP02':{'origin':[0,0,2],'source_faces':[[17,64],[17,63]]}},
 'derived_pitch_circle':{'id':'MP04','radius':38.,'origin':[0,0,2],'normal':[0,0,1],'source_faces':flangeholes},
 'font':{'path':'C:/Windows/Fonts/arial.ttf','sha256':hashlib.sha256(open('C:/Windows/Fonts/arial.ttf','rb').read()).hexdigest(),'height_mm':2.7,'curve_deflection_mm':0.012},
 'annotations':[{**row,'layout':{'mode':layout[row['id']][0],'data':layout[row['id']][1]},
 'presentation':{k:v for k,v in graphics[row['id']].items() if k!='shape'}} for row in contract['pmi']],
 'assumptions_in_step':metadata}
json.dump(specification,open(out+'/Maschinenteil_PMI_Spezifikation.json','w',encoding='utf-8'),indent=2,ensure_ascii=False)

writer.ChangeWriter().WS().ComputeGraph(True)
candidate=out+'/Maschinenteil_PMI_AP242.step'
assert writer.Write(candidate)
text=open(candidate,encoding='utf-8').read();assert 'AP242' in text
print('CANDIDATE_WRITTEN',candidate,flush=True)
# Fresh importer checks numeric PMI values and graphical presentations.
rd=TDocStd_Document('BinXCAF');reader=STEPCAFControl_Reader();reader.SetGDTMode(True);reader.SetNameMode(True)
assert reader.ReadFile(candidate)==IFSelect_RetDone and reader.Transfer(rd)
rtool=XCAFDoc_DocumentTool.DimTolTool(rd.Main());labels=TDF_LabelSequence();rtool.GetDimensionLabels(labels)
readback=[]
expected={r['id']:r for r in contract['pmi']}
for i in range(1,labels.Length()+1):
 obj=XCAFDoc_Dimension.Set(labels.Value(i)).GetObject();descs={}
 for j in range(obj.NbDescriptions()):descs[obj.GetDescriptionName(j).ToCString()]=obj.GetDescription(j).ToCString()
 id=descs.get('source_id')
 if id in expected:
  assert abs(obj.GetValue()-expected[id]['value'])<1e-7,(id,obj.GetValue())
  assert not obj.GetPresentation().IsNull(),id
  readback.append({'id':id,'value':obj.GetValue(),'graphic':True})
assert len(readback)==29,(len(readback),readback)
solidreader=STEPControl_Reader();assert solidreader.ReadFile(candidate)==IFSelect_RetDone;solidreader.TransferRoots()
imported=Part.__fromPythonOCC__(solidreader.OneShape())
assert len(imported.Solids)==1 and imported.isValid()
volume_integration_delta=imported.Volume-fcshape.Volume
symmetric_difference=fcshape.cut(imported).Volume+imported.cut(fcshape).Volume
print('SYMMETRIC_DIFFERENCE',symmetric_difference,'VOLUME_INTEGRATION_DELTA',volume_integration_delta,flush=True)
assert symmetric_difference<1e-5,symmetric_difference
assert len(imported.Faces)==74,len(imported.Faces)
bbdelta=max(abs(getattr(imported.BoundBox,k)-getattr(fcshape.BoundBox,k)) for k in ['XMin','YMin','ZMin','XMax','YMax','ZMax'])
assert bbdelta<1e-6,bbdelta
counts={n:len(entities(n)) for n in ['StepShape_DimensionalCharacteristicRepresentation','StepVisual_TessellatedAnnotationOccurrence','StepVisual_DraughtingCallout','StepVisual_AnnotationPlane','StepAP242_DraughtingModelItemAssociation']}
assert counts['StepShape_DimensionalCharacteristicRepresentation']==29
assert all(counts[n]==31 for n in counts if n!='StepShape_DimensionalCharacteristicRepresentation'),counts
result={'status':'pass','headless':App.GuiUp==0,'source_contract_sha256':contract['contract_sha256'],'file':candidate,
 'step_sha256':hashlib.sha256(open(candidate,'rb').read()).hexdigest(),'numeric_dimensions':29,'manufacturing_properties':notes,'assumption_metadata':metadata,
 'presentation_count':31,'entity_counts':counts,'roundtrip_numeric':readback,'angle_geometry_degrees':angles,'pcd_radius_mm':38.,
 'symmetric_difference_mm3':symmetric_difference,'bounding_box_max_delta_mm':bbdelta,'symmetric_difference_tolerance_mm3':1e-5,'volume_integration_delta_mm3':volume_integration_delta,'original_volume_mm3':fcshape.Volume,'imported_volume_mm3':imported.Volume,'original_faces':74,'native_refs':refs,
 'property_semantics':'M10 is geometric semantic text, not a fully typed thread feature; pitch and tolerance absent',
 'geometry_source':'Maschinenteil_Konstruktion.FCStd, final CrossBoreCut3; no previous part geometry'}
json.dump(result,open(out+'/Maschinenteil_PMI_Pruefung.json','w',encoding='utf-8'),indent=2,ensure_ascii=False)
print('MPMI_EXPORT_SUCCESS:'+json.dumps(result,ensure_ascii=False),flush=True)

```
