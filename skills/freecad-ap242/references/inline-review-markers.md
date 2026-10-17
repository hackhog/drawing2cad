# Reviewmarker-Injektion, Revision 02, Schema 1

Die Eingangsprüfung validiert gezielt mm-Einheit, amb3_-Namespace, eindeutige IDs, Zielkörper, Reviewklassen, Ansichtsgruppen, endliche Anzeige-/Ankerkoordinaten, RGB-Werte und verwendete Text-/Quellhashfelder. Sie behauptet keine vollständige allgemeine JSON-Schemavalidierung. Alle Prüfungen erfolgen vor der Dokumentmutation.

Dieser Code ist Dokumentation und wird ausschließlich als Inline-Python über den FreeCAD-MCP ausgeführt. Er ist keine Skriptdatei. `metadata` ist das vollständige Objekt `drawing2cad.review-annotations/1`, aus der namespaced AP242-Eigenschaft `drawing2cad.review_annotations.v1` gelesen. Keine externe JSON-Datei ist beim späteren Import erforderlich.

Die Marker sind Reviewinformationen, keine zusätzlichen Original-Zeichnungs-PMI, keine Fertigungsmaße und keine Produktkörper. Die 31 originalen Zeichnungsangaben bleiben getrennt. Vor Änderungen validiert die Funktion alle Flächenanker und alle logischen Konstruktionsreferenzen. Mehrdeutige oder fehlende Treffer brechen ab; `FaceN` wird ausschließlich als Laufzeitergebnis gespeichert.

```python
def amb3_inject_review(doc, root, metadata):
    import FreeCAD as App, Part, json, math
    if metadata.get('schema') != 'drawing2cad.review-annotations/1':
        raise ValueError('Unbekanntes Review-Schema')
    if metadata.get('fingerprint_policy',{}).get('bbox_method') != 'optimalBoundingBox(false,false)':
        raise ValueError('Revision 02 erfordert optimale geometrische Boundingboxen')
    if root.Document != doc:
        raise ValueError('Review-Ziel gehört nicht zum Dokument')
    import re
    if metadata.get('units') != 'mm':
        raise ValueError('Review-Einheit muss mm sein')
    if metadata.get('namespace') != 'amb3_':
        raise ValueError('Review-Namespace muss amb3_ sein')
    def finite_vector(value, count, label):
        if not isinstance(value,(list,tuple)) or len(value)!=count:
            raise ValueError(label+': falsche Koordinatenzahl')
        if any(isinstance(x,bool) or not isinstance(x,(int,float)) or not math.isfinite(x) for x in value):
            raise ValueError(label+': nichtendliche oder ungueltige Zahl')
    entries=metadata.get('entries')
    if not isinstance(entries,list): raise ValueError('Revieweintraege muessen eine Liste sein')
    seen=set()
    for item in entries:
        name=item.get('id')
        if not isinstance(name,str) or re.fullmatch(r'amb3_[A-Za-z0-9_]+',name) is None:
            raise ValueError('Ungueltige Review-ID')
        if name in seen: raise ValueError('Doppelte Review-ID '+name)
        seen.add(name)
        if item.get('classification') not in ('known','derived','confirmed','open'):
            raise ValueError(name+': ungueltige Reviewklasse')
        if not isinstance(item.get('title'),str) or not isinstance(item.get('status'),str):
            raise ValueError(name+': Titel/Status fehlt')
        geometry=item['geometry']; display=item['display']
        if geometry.get('root_logical_id') != root.Name:
            raise ValueError(name+': falscher logischer Zielkoerper')
        if display.get('view') not in ('front','side','global'):
            raise ValueError(name+': ungueltige Reviewansicht')
        finite_vector(display.get('color_rgb'),3,name+' RGB')
        if any(x<0 or x>1 for x in display['color_rgb']):
            raise ValueError(name+': RGB ausserhalb 0..1')
        finite_vector(display.get('label_position'),3,name+' Textanker')
        labels=display.get('label_lines')
        if not isinstance(labels,list) or not labels or any(not isinstance(x,str) for x in labels):
            raise ValueError(name+': ungueltiger Beschriftungstext')
        if not isinstance(display.get('target_points',[]),list) or not isinstance(display.get('leader_polylines',[]),list):
            raise ValueError(name+': ungueltige Reviewgeometrie')
        for point in display.get('target_points',[]): finite_vector(point,3,name+' Zielpunkt')
        for line in display.get('leader_polylines',[]):
            if not isinstance(line,list) or len(line)<2: raise ValueError(name+': ungueltige Leitlinie')
            for point in line: finite_vector(point,3,name+' Leitlinienpunkt')
        for anchor in geometry.get('face_fingerprints',[]):
            finite_vector(anchor.get('center'),3,name+' Flaechenschwerpunkt')
            finite_vector(anchor.get('bbox'),6,name+' Flaechenbox')
            finite_vector([anchor.get('area')],1,name+' Flaecheninhalt')
            for key in ('radius','major_radius','minor_radius'):
                if anchor.get(key) is not None: finite_vector([anchor[key]],1,name+' '+key)
    finite_vector(metadata['legend']['label_position'],3,'Legendenanker')
    if not isinstance(metadata['legend'].get('label_lines'),list) or any(not isinstance(x,str) for x in metadata['legend']['label_lines']):
        raise ValueError('Ungueltiger Legendentext')
    if not isinstance(metadata.get('source',{}).get('sha256'),str) or re.fullmatch(r'[0-9a-fA-F]{64}',metadata['source']['sha256']) is None:
        raise ValueError('Ungueltiger Quellhash')
    def fp(face):
        face=face.copy(True,False)  # Geometrie ohne ansichtsabhaengige Triangulation.
        b=face.optimalBoundingBox(False,False); c=face.CenterOfMass; s=face.Surface
        return {'surface':type(s).__name__, 'area':float(face.Area),
                'center':[c.x,c.y,c.z],
                'bbox':[b.XMin,b.YMin,b.ZMin,b.XMax,b.YMax,b.ZMax],
                'radius':float(s.Radius) if hasattr(s,'Radius') else None,
                'major_radius':float(s.MajorRadius) if hasattr(s,'MajorRadius') else None,
                'minor_radius':float(s.MinorRadius) if hasattr(s,'MinorRadius') else None}
    def same(a,b):
        if a['surface']!=b['surface']: return False
        if abs(a['area']-b['area'])>max(1e-5,abs(a['area'])*1e-7): return False
        for key in ('center','bbox'):
            if max(abs(x-y) for x,y in zip(a[key],b[key]))>1e-4: return False
        for key in ('radius','major_radius','minor_radius'):
            x=a.get(key); y=b.get(key)
            if (x is None)!=(y is None): return False
            if x is not None and abs(x-y)>1e-6: return False
        return True
    actual=[fp(f) for f in root.Shape.Faces]
    resolved={}
    for item in metadata['entries']:
        ids=[]
        for expected in item['geometry'].get('face_fingerprints',[]):
            hits=[i+1 for i,value in enumerate(actual) if same(expected,value)]
            if len(hits)!=1:
                raise ValueError(item['id']+': Flaechenanker hat '+str(len(hits))+' Treffer')
            ids.append(hits[0])
        if len(ids)!=len(set(ids)): raise ValueError(item['id']+': doppelte Flaechenanker')
        for name in item['geometry'].get('logical_feature_ids',[]):
            if doc.getObject(name) is None: raise ValueError(item['id']+': Feature fehlt '+name)
        resolved[item['id']]=ids
    # Nur eigene, bereits validierte Reviewobjekte ersetzen.
    for old in reversed(list(doc.Objects)):
        if old.Name.startswith('amb3_'): doc.removeObject(old.Name)
    top=doc.addObject('App::DocumentObjectGroup','amb3_Review')
    top.Label='REVIEW - keine Original-Zeichnungs-PMI'
    top.addProperty('App::PropertyString','ReviewSchema','Review'); top.ReviewSchema=metadata['schema']
    top.addProperty('App::PropertyString','ReviewJSON','Review'); top.ReviewJSON=json.dumps(metadata,ensure_ascii=False,separators=(',',':'))
    top.addProperty('App::PropertyLink','ReviewedBody','Review'); top.ReviewedBody=root
    top.addProperty('App::PropertyString','SourceSHA256','Review'); top.SourceSHA256=metadata['source']['sha256']
    views={}
    for key in ('front','side','global'):
        g=doc.addObject('App::DocumentObjectGroup','amb3_'+key)
        g.Label='REVIEW - '+key; top.addObject(g); views[key]=g
    def appearance(obj,color,width=3):
        if App.GuiUp:
            obj.ViewObject.LineColor=tuple(color)
            obj.ViewObject.PointColor=tuple(color)
            obj.ViewObject.LineWidth=width
            obj.ViewObject.Visibility=True
    for item in metadata['entries']:
        name=item['id']; display=item['display']; color=display['color_rgb']
        group=doc.addObject('App::DocumentObjectGroup',name)
        group.Label=name+' | '+item['title']; views[display['view']].addObject(group)
        group.addProperty('App::PropertyString','ReviewStatus','Review'); group.ReviewStatus=item['status']
        group.addProperty('App::PropertyString','ReviewItemJSON','Review'); group.ReviewItemJSON=json.dumps(item,ensure_ascii=False,separators=(',',':'))
        group.addProperty('App::PropertyLinkList','LogicalFeatures','Review'); group.LogicalFeatures=[doc.getObject(x) for x in item['geometry'].get('logical_feature_ids',[])]
        group.addProperty('App::PropertyLinkSubList','ResolvedTargets','Review')
        if resolved[name]: group.ResolvedTargets=[(root,['Face'+str(x) for x in resolved[name]])]
        edges=[e.copy() for n in resolved[name] for e in root.Shape.Faces[n-1].Edges]
        if edges:
            mark=doc.addObject('Part::Feature',name+'_edges'); mark.Label=name+' - lokale Flaechenumrandung'
            mark.Shape=Part.makeCompound(edges); group.addObject(mark); appearance(mark,color,4)
        lines=[]
        for polyline in display.get('leader_polylines',[]):
            for a,b in zip(polyline,polyline[1:]):
                if sum((x-y)**2 for x,y in zip(a,b))>1e-16:
                    lines.append(Part.makeLine(App.Vector(*a),App.Vector(*b)))
        for center in display.get('target_points',[]):
            # Kleine Ortsmarke in der Vorderansicht; keine konstruktive Geometrie.
            lines.append(Part.makeCircle(1.25,App.Vector(*center),App.Vector(0,0,1)))
        if lines:
            leader=doc.addObject('Part::Feature',name+'_leader'); leader.Label=name+' - Review-Verweis'
            leader.Shape=Part.makeCompound(lines); group.addObject(leader); appearance(leader,color,2)
        note=doc.addObject('App::Annotation',name+'_label')
        note.Label=name+' - Reviewtext'; note.LabelText=display['label_lines']; note.Position=App.Vector(*display['label_position'])
        group.addObject(note)
        if App.GuiUp:
            note.ViewObject.FontSize=18
            note.ViewObject.TextColor=tuple(color)
    legend=doc.addObject('App::Annotation','amb3_Legend')
    legend.Label='REVIEW - Legende'; legend.LabelText=metadata['legend']['label_lines']
    legend.Position=App.Vector(*metadata['legend']['label_position']); views['global'].addObject(legend)
    if App.GuiUp:
        legend.ViewObject.FontSize=16
        legend.ViewObject.TextColor=(0.12,0.12,0.12)
        views['side'].ViewObject.Visibility=False
    doc.recompute()
    return {'schema':metadata['schema'],'entry_count':len(metadata['entries']),
            'resolved_faces':resolved,'objects_created':len([o for o in doc.Objects if o.Name.startswith('amb3_')]),
            'body_geometry_changed':False}
```

Aufruf: `amb3_inject_review(doc, doc.getObject('CrossBoreCut3'), metadata)`. Die Funktion speichert nicht selbst. Der Aufrufer bestimmt den getrennten Kandidatenpfad und führt erneute Geometrie-/Metadatenprüfungen aus. Für eine Seitenansicht die Gruppe `amb3_side` einschalten und `amb3_front` ausblenden. Für die Frontansicht umgekehrt. `amb3_global` enthält die Legende.

Für einen normalen Produkt-STEP-Export dürfen Review-Kanten **nicht** als zusätzliche Bauteile in die zu exportierende Objektliste gelangen. Persistenz entsteht über die deklarierte namespaced Property; die Anwendung rekonstruiert die separaten Reviewgruppen daraus. Das ist eine dokumentierte Anwendungserweiterung, keine Behauptung einer universellen grafischen PMI-Unterstützung in Fremdviewern.


## Eng begrenzte Korrektur in Revision 02

Die native `Face.optimalBoundingBox`-Dokumentation wurde am installierten FreeCAD-Objekt geprüft: `optimalBoundingBox([useTriangulation = True, useShapeTolerance = False])`. Revision 02 verwendet ausdrücklich `False, False` auf einer Kopie ohne Triangulation. Bei getrimmten Toroidflächen liefert die normale `BoundBox` gelegentlich unterschiedlich konservative Grenzen trotz gleicher Geometrie. Dieser Darstellungs-/Berechnungsunterschied wird durch die optimale geometrische Box ersetzt; kein numerischer Grenzwert wird gelockert.

Alle 44 Ankerreferenzen aus Original und dem frisch aus STEP rekonstruierten Körper wurden gegengeprüft. Nur die Boundingboxwerte der zehn Toroidflächen ändern sich gegenüber Revision 01; die übrigen Felder, Reviewaussagen und Layoutdaten bleiben erhalten. Maximale Original-/Neuaufbau-Abweichung der optimalen Boxen: 4,7255e-11 mm. Negative Tests prüfen weiterhin Ablehnung von verschobenen und mehrdeutigen Ankern. Die alte Revision wird unverändert aufbewahrt.
