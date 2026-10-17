# Lineare Ansicht nativer Operationen

Eine native `App::DocumentObjectGroup` kann die Originaloperationen in einer expliziten Reihenfolge als gleichrangige Kinder anzeigen. Ihre `Base`-/`Tool`-/Profil-Abhängigkeiten bleiben bestehen. Beim Aufklappen einer Operation sind diese weiterhin zusätzlich erreichbar; die lineare Standardansicht entsteht durch die aufgeklappte Gruppe und eingeklappte Operationen. Es entstehen keine Link-Kopien und keine neuen Endkörper.

Die Gruppierung ist eine FreeCAD-Bedienansicht, keine neue Konstruktionsoperation und keine Änderung des STEP-DAG. Die Reihenfolge muss aus dem bereits geprüften Operationsgraphen stammen. Für STEP-only-Wiederholung diese Ansicht nach dem konstruktiven Wiederaufbau aus den geordneten logischen IDs erzeugen. Sie benötigt weder zusätzliche Geometriedaten noch ein Python-Modul im gespeicherten FCStd.

## Inline-Baustein

Nur über den FreeCAD-MCP auf dem GUI-Thread ausführen. `doc` und `ordered_ids` explizit übergeben; keine aktive Auswahl oder aktives Dokument voraussetzen. Vorher eine neue Arbeitskopie verwenden. Der Baustein verändert ausschließlich seine native Gruppe und deren Metadaten; Objektparameter, Abhängigkeiten und 3D-Sichtbarkeit bleiben erhalten. Die Tree-Aufklappung erfolgt separat und verlangt die GUI.

```python
import re

def lin4_apply_history(doc, ordered_ids, group_name='ConstructionHistory',
                       group_label='01 Konstruktionshistorie – lineare Schritte'):
    if not isinstance(ordered_ids, (list, tuple)) or not ordered_ids:
        raise ValueError('LINEAR_HISTORY_EMPTY_ORDER')
    if (not isinstance(group_name, str)
            or not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', group_name)
            or not isinstance(group_label, str) or not group_label.strip()):
        raise ValueError('LINEAR_HISTORY_INVALID_GROUP')
    if any(not isinstance(n, str) for n in ordered_ids):
        raise ValueError('LINEAR_HISTORY_INVALID_ID')
    if len(set(ordered_ids)) != len(ordered_ids) or group_name in ordered_ids:
        raise ValueError('LINEAR_HISTORY_DUPLICATE_OR_SELF_REFERENCE')
    objects = [doc.getObject(n) for n in ordered_ids]
    if any(o is None or not o.isDerivedFrom('Part::Feature') for o in objects):
        raise ValueError('LINEAR_HISTORY_MISSING_OR_NON_SHAPE_OPERATION')
    rank = {n: i for i, n in enumerate(ordered_ids)}
    for o in objects:
        if any(rank[x.Name] >= rank[o.Name]
               for x in o.OutList if x.Name in rank):
            raise ValueError('LINEAR_HISTORY_NOT_TOPOLOGICAL: ' + o.Name)
    group = doc.getObject(group_name)
    if group is not None and (
            group.TypeId != 'App::DocumentObjectGroup'
            or getattr(group, 'LinearHistoryProfile', '') != 'native-group/1'):
        raise ValueError('LINEAR_HISTORY_NAME_COLLISION')
    before = {o.Name: (tuple(x.Name for x in o.OutList),
              o.ViewObject.Visibility if o.ViewObject else None) for o in objects}
    doc.openTransaction('Lineare Konstruktionsansicht')
    try:
        if group is None:
            group = doc.addObject('App::DocumentObjectGroup', group_name)
            group.addProperty('App::PropertyString', 'LinearHistoryProfile',
                              'Linear History')
            group.LinearHistoryProfile = 'native-group/1'
            group.setEditorMode('LinearHistoryProfile', 1)
        group.Label = group_label
        group.Group = objects
        after = {o.Name: (tuple(x.Name for x in o.OutList),
                 o.ViewObject.Visibility if o.ViewObject else None) for o in objects}
        if before != after or [o.Name for o in group.Group] != list(ordered_ids):
            raise RuntimeError('LINEAR_HISTORY_INVARIANT_CHANGED')
        doc.commitTransaction()
    except Exception:
        doc.abortTransaction()
        raise
    return group

def lin4_expand_history(doc, group):
    import FreeCAD as App
    if not App.GuiUp:
        return {'applied': False, 'reason': 'GUI_UNAVAILABLE'}
    import FreeCADGui as Gui
    from PySide import QtWidgets
    if group.Document != doc:
        raise ValueError('LINEAR_HISTORY_WRONG_DOCUMENT')
    # FreeCAD's tree item bindings expose the label, not a stable object ID.
    # Reject ambiguous labels; never choose a different document by accident.
    if sum(d.Label == doc.Label for d in App.listDocuments().values()) != 1:
        raise ValueError('LINEAR_HISTORY_AMBIGUOUS_DOCUMENT_LABEL')
    if sum(o.Label == group.Label for o in doc.Objects) != 1:
        raise ValueError('LINEAR_HISTORY_AMBIGUOUS_GROUP_LABEL')
    Gui.updateGui()
    targets = []
    for tree in Gui.getMainWindow().findChildren(QtWidgets.QTreeWidget):
        for i in range(tree.topLevelItemCount()):
            item = tree.topLevelItem(i)
            if item.text(0) != doc.Label:
                continue
            for j in range(item.childCount()):
                child = item.child(j)
                if child.text(0) == group.Label:
                    targets.append((item, child))
    if not targets:
        return {'applied': False, 'reason': 'TREE_ITEMS_NOT_READY'}
    for item, child in targets:
        item.setExpanded(True)
        child.setExpanded(True)
        for i in range(child.childCount()):
            child.child(i).setExpanded(False)
    return {'applied': True, 'tree_instances': len(targets),
            'direct_operation_count': len(group.Group)}
```

Bei `TREE_ITEMS_NOT_READY` den späteren MCP-Aufruf nach der GUI-Aktualisierung wiederholen; kein positives Anzeigeergebnis erfinden. Ein Headless-Aufbau kann die Gruppe speichern, jedoch keine tatsächlich sichtbare Baumansicht nachweisen. Keine globalen TreeView-Einstellungen verändern. Speichern nach erfolgreicher Aufklappung erhält die Gruppen-/Operationszustände; das Dokument selbst kann nach Öffnen eingeklappt erscheinen und wird durch denselben GUI-Baustein geöffnet.

## Prüfungen und bekannter Nachweis

Die lokale isolierte Probe unter FreeCAD 1.1.4 verwendete Box, Zylinder und `Part::Cut`, als drei direkte Originalkinder einer nativen Gruppe. Nach Speichern/Öffnen blieben Reihenfolge, Gruppenlabel, Abhängigkeiten, aufgeklappte Gruppe und eingeklappte Operationen erhalten. Eine Box-Längenänderung von 20 auf 21 mm änderte das Volumen um `100.00000000000045 mm³` bei erwartet `100 mm³`; Rückstellung und erneutes Öffnen ergaben jeweils `0 mm³` symmetrische Differenz. Es wurde kein Python-Proxy verwendet. Dies belegt die native Gruppierungsstrategie; der Inline-Baustein und ein konkretes vollständiges Modell müssen zusätzlich mit den jeweiligen Eingaben geprüft werden.

Fallbezogene Evidenz: `output/cad/Maschinenteil/linear_tree_probe_v4/Native_Group_Persistenz_Pruefung.json` und `Native_Group_Persistenz.FCStd`. Diese Pfade sind historische Prüfausgaben, keine generischen Eingabepfade.

Der vollständige Inline-Baustein wurde anschließend am Maschinenteil mit 53 Originaloperationen geprüft: direkte Gruppenreihenfolge und alle bisherigen Abhängigkeiten/Sichtbarkeiten unverändert, 0 mm³ geometrische Differenz nach Rückstellung und erneutem Öffnen. Änderung des ersten Querbohrungsradius von 1,25 auf 1,1 mm ergab 33,2223422886 mm³ Volumenzuwachs bei erwartet 33,2223423117 mm³. Gruppe aufgeklappt und alle 53 direkten Operationskinder eingeklappt wurden nach erneutem Öffnen aus dem tatsächlichen Qt-Baum gelesen. Ein erster Aufruf lieferte korrekt `TREE_ITEMS_NOT_READY`; der nächste MCP-Aufruf nach GUI-Aktualisierung stellte die Ansicht her. Evidenz: `output/cad/Maschinenteil/review_20261016/linear_history_v4/Lineare_Historie_Pruefung.json` und `Lineare_Historie.png`. Der vorhandene STEP-Master blieb bytegleich; diese Ansicht ergänzt den nativen Wiederaufbau.

Für das konkrete Modell vor Übergabe alle Operations-IDs und die direkte Gruppenreihenfolge vergleichen, Geometrie sowie Sichtbarkeit unverändert nachweisen, einen Parameter ändern/zurückstellen und die gespeicherte Datei erneut öffnen. Die Ansicht ersetzt weder semantische PMI noch das Adapter-Fähigkeitsgate.

Primärquellen: [FreeCAD Tree view](https://github.com/FreeCAD/FreeCAD-documentation/blob/main/wiki/Tree_view.md) beschreibt, wie Abhängigkeiten im Baum erscheinen; die hier dokumentierte flache Gruppierung wurde zusätzlich gegen die tatsächlich installierte Version geprüft. [FreeCAD ViewProviderLink.cpp](https://github.com/FreeCAD/FreeCAD/blob/main/src/Gui/ViewProviderLink.cpp) zeigt, dass normale Links die Kinder des verknüpften ViewProviders übernehmen können; sie sind daher keine allgemeine Abkürzung zur flachen Operationsansicht.
