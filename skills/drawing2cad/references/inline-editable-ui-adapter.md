# Editable user interface from AP242: inline adapter

First, load the parser, geometry, and import functions from `inline-procedural-adapter.md` inline. Also load `read_adapter_properties` from `inline-review-envelope.md`. Then execute the following block inline through the FreeCAD proxy of `drawing2cad-mcp`. No script file is necessary.

Entry point: `hist3_rebuild_editable(step_path, fcstd_path=None, docname="Maschinenteil_Editierbar")`. The STEP file is the only model source. The adapter reads user interface metadata from its named property.

In the verified Maschinenteil case, the adapter rebuilds 53 standard operations as native operations. It maps each of six selected rectangular extrusions to a fully dimensioned sketch and `Part::Extrusion`. The 56 independent dimensions in the table come only from STEP operation entities.

The adapter does not rebuild or invent shared bolt-circle, pattern, or position constraints. Positions and axes remain editable through Placement. The result is a reconstructed operation sequence, not the original user history.

```python

def hist3_make_box(doc, name, op):
    import FreeCAD as App, Part, Sketcher
    sketch = doc.addObject('Sketcher::SketchObject', name + 'Profile')
    sketch.Placement.Base = App.Vector(*op['origin'])
    points = [(0,0), (op['length'],0), (op['length'],op['width']), (0,op['width'])]
    for i in range(4):
        a,b = points[i], points[(i+1)%4]
        sketch.addGeometry(Part.LineSegment(App.Vector(a[0],a[1],0),App.Vector(b[0],b[1],0)),False)
    for i in range(4): sketch.addConstraint(Sketcher.Constraint('Coincident',i,2,(i+1)%4,1))
    for i in (0,2): sketch.addConstraint(Sketcher.Constraint('Horizontal',i))
    for i in (1,3): sketch.addConstraint(Sketcher.Constraint('Vertical',i))
    sketch.addConstraint(Sketcher.Constraint('Coincident',0,1,-1,1))
    ix=sketch.addConstraint(Sketcher.Constraint('Distance',0,op['length']))
    iy=sketch.addConstraint(Sketcher.Constraint('Distance',1,op['width']))
    sketch.renameConstraint(ix,'ProfileX'); sketch.renameConstraint(iy,'ProfileY')
    solid = doc.addObject('Part::Extrusion',name)
    solid.Base=sketch; solid.Dir=App.Vector(0,0,1); solid.LengthFwd=op['height']; solid.LengthRev=0; solid.Solid=True
    solid.Reversed=False; solid.Symmetric=False
    doc.recompute()
    if sketch.SolverMessages if hasattr(sketch,'SolverMessages') else False:
        raise ValueError('Sketch solver messages: '+name)
    if not sketch.FullyConstrained: raise ValueError('Rectangle not fully constrained: '+name)
    if sketch.ViewObject: sketch.ViewObject.Visibility=False
    return solid

def hist3_apply_ui(doc, operations, metadata):
    import re, json
    if metadata.get('schema') != 'drawing2cad.editable-ui/1': raise ValueError('Unsupported UI schema')
    if metadata.get('native_box_strategy') != 'selected_rectangle_sketch_extrusion_v1': raise ValueError('Unsupported box strategy')
    names={o['id']:o for o in operations}
    if set(metadata['labels']) != set(names): raise ValueError('UI labels must cover construction')
    sheetname=metadata['parameter_sheet_name']
    if not re.fullmatch('[A-Za-z][A-Za-z0-9_]*',sheetname): raise ValueError('Invalid sheet name')
    if doc.getObject(sheetname): raise ValueError('Parameter sheet already exists')
    sheet=doc.addObject('Spreadsheet::Sheet',sheetname);sheet.Label=metadata['parameter_sheet_label']
    sheet.set('A1','EDITIERBARE KONSTRUKTION AUS AP242');sheet.mergeCells('A1:F1')
    sheet.set('A2','Gelbe Zellen C ändern. Jede Zeile ist unabhängig; keine automatische Muster- oder Lagekopplung.');sheet.mergeCells('A2:F2')
    sheet.set('A3','Position/Achse: Placement am Zylinder oder an der Profilskizze. Verrundungen: Edges am Verrundungsschritt.');sheet.mergeCells('A3:F3')
    sheet.set('A4','PMI nach Änderungen prüfen. Quelle: explizite STEP-Operationen; keine ursprüngliche Benutzerhistorie.');sheet.mergeCells('A4:F4')
    for cell,value in zip(('A6','B6','C6','D6','E6','F6'),('Bereich / Schritt','Parameter','Wert ändern','Einheit','Native Eigenschaft','Logische ID')):sheet.set(cell,value)
    sheet.setStyle('A1:F1','bold','add');sheet.setStyle('A6:F6','bold','add')
    sheet.setBackground('A6:F6',(0.16,0.25,0.35));sheet.setForeground('A6:F6',(1.,1.,1.))
    rows=[];aliases=set();mapped_parameters=set()
    for row,item in enumerate(metadata['parameter_rows'],7):
        name,key,alias=item['operation'],item['parameter'],item['alias']
        if name not in names or not re.fullmatch('[A-Za-z][A-Za-z0-9_]*',alias) or alias in aliases: raise ValueError('Invalid parameter mapping')
        op=names[name];obj=doc.getObject(name)
        if item['unit']!='mm' or op['type'] not in ('cylinder','box'):raise ValueError('Unsupported parameter units/type')
        allowed=('radius','depth') if op['type']=='cylinder' else ('length','width','height')
        if key not in allowed: raise ValueError('Invalid source parameter')
        if (name,key) in mapped_parameters: raise ValueError('Duplicate operation parameter mapping')
        mapped_parameters.add((name,key))
        aliases.add(alias)
        sheet.set('A'+str(row),item['group']+' / '+metadata['labels'][name]);sheet.set('B'+str(row),item['label'])
        sheet.set('C'+str(row),format(op[key],'.15g')+' mm');sheet.setAlias('C'+str(row),alias)
        sheet.set('D'+str(row),'mm');sheet.set('F'+str(row),name)
        expression=sheetname+'.'+alias
        if op['type']=='cylinder':
            target=obj;prop={'radius':'Radius','depth':'Height'}[key]
        elif obj.TypeId=='Part::Box':
            target=obj;prop={'length':'Length','width':'Width','height':'Height'}[key]
        elif key=='height':
            target=obj;prop='LengthFwd'
        else:
            target=obj.Base;prop='Constraints.'+{'length':'ProfileX','width':'ProfileY'}[key]
        target.setExpression(prop,expression)
        sheet.set('E'+str(row),target.Name+'.'+prop)
        sheet.setBackground('C'+str(row),(1.0,0.93,0.58))
        rows.append({'row':row,'cell':'C'+str(row),'operation':name,'parameter':key,'alias':alias,'target':target.Name,'property':prop})
    for col,width in [('A',390),('B',230),('C',110),('D',65),('E',270),('F',160)]:sheet.setColumnWidth(col,width)
    for i,op in enumerate(operations,1):
        obj=doc.getObject(op['id']);obj.Label=('%02d  '%i)+metadata['labels'][op['id']]
        obj.addProperty('App::PropertyInteger','ConstructionStep','Konstruktion');obj.ConstructionStep=i;obj.setEditorMode('ConstructionStep',1)
        obj.addProperty('App::PropertyString','LogicalOperation','Konstruktion');obj.LogicalOperation=op['id'];obj.setEditorMode('LogicalOperation',1)
        obj.addProperty('App::PropertyString','EditHelp','Konstruktion');obj.EditHelp='Maße: Parameter-Tabelle (Doppelklick); ursprüngliche STEP-Parameter, keine zusätzlichen Konstruktionsbeziehungen.'
        if obj.TypeId=='Part::Extrusion':obj.Base.Label=('%02dP  '%i)+'Rechteckskizze – '+metadata['labels'][op['id']]
        if obj.ViewObject: obj.ViewObject.Visibility=(i==len(operations))
    sheet.addProperty('App::PropertyString','AdapterMetadata','AP242');sheet.AdapterMetadata=json.dumps(metadata,ensure_ascii=False,separators=(',',':'));sheet.setEditorMode('AdapterMetadata',1)
    sheet.addProperty('App::PropertyString','PMIStatus','AP242');sheet.PMIStatus='PMI und Reviewmarkierungen gelten für den gespeicherten Ausgangsstand; nach Parameteränderungen erneut prüfen.';sheet.setEditorMode('PMIStatus',1)
    doc.recompute()
    return rows

def hist3_rebuild_editable(step_path,fcstd_path=None,docname='AP242NativeRebuild'):
    decoded=sth_decode_step(step_path)
    metadata=read_adapter_properties(step_path,{'drawing2cad.editable_ui.v1':'drawing2cad.editable-ui/1'})['drawing2cad.editable_ui.v1']
    hist3_native_box_ids=set(metadata['sketch_extrusion_operations'])
    if not hist3_native_box_ids.issubset({o['id'] for o in decoded['operations'] if o['type']=='box'}):raise ValueError('Invalid sketch operation IDs')
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
                o=hist3_make_box(doc,name,op) if name in hist3_native_box_ids else None
                if o is None:
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
        rows=hist3_apply_ui(doc,decoded['operations'],metadata)
        report['parameter_rows']=rows
        report['native_sketches']=[{'name':o.Name,'fully_constrained':o.FullyConstrained,'state':o.State} for o in doc.Objects if o.TypeId=='Sketcher::SketchObject']
        report['ui_metadata_source']='STEP PROPERTY_DEFINITION drawing2cad.editable_ui.v1'
        doc.Label=metadata.get('document_label','Editierbare Konstruktion – '+decoded['root'])
        if fcstd_path:doc.saveAs(fcstd_path)
        return doc,root,objects,report,decoded
    except:
        A.closeDocument(doc.Name)
        raise


```

## Fingerprint correction

In both definitions in the procedural reference, replace `bb=e.BoundBox` with `bb=e.copy(True,False).BoundBox`. GUI triangulation can approximate bounding-box extremes. The copy without a mesh uses the geometry. Keep the tolerance and the distance check in both directions between edges unchanged.
