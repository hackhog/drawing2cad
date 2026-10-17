# Linear view of native operations

This is an optional FreeCAD development-adapter reference. It is not a dependency of the backend-neutral skill. Prefer the maintained tools in [managed-workflow.md](managed-workflow.md) when they cover the operation. Revalidate any remaining inline fallback before use.


A native `App::DocumentObjectGroup` can show original operations as direct children in an explicit order. Their `Base`, `Tool`, and profile dependencies remain. When an operation is expanded, these dependencies are also accessible. Expand the group and collapse its operations to produce the default linear view. This creates no link copies or new final solids.

The group is a FreeCAD user interface view. It does not add a construction operation or change the STEP DAG. Get the order from the verified operation graph. For a STEP-only repeat run, create this view from ordered logical IDs after the constructive rebuild. No additional geometry data or Python module is necessary in the saved FCStd.

## Inline component

Use the FreeCAD proxy of `drawing2cad-mcp`. Supply `doc` and `ordered_ids` explicitly. Do not assume an active selection or active document. First, make a new working copy.

`lin4_apply_history` creates native groups without a GUI. Verify this path in the headless server. `lin4_expand_history` is an optional desktop display helper. It requires the GUI thread and is not part of the server workflow.

The default label was made generic. Revalidate the changed code before use. No live CAD test was run during this cleanup.

The component changes only its native group and the group metadata. Object parameters, dependencies, and 3D visibility remain unchanged. Tree expansion is a separate operation that requires the GUI.

```python
import re

def lin4_apply_history(doc, ordered_ids, group_name='ConstructionHistory',
                       group_label='Construction history - linear steps'):
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
    doc.openTransaction('Linear construction view')
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

If the result is `TREE_ITEMS_NOT_READY`, repeat the MCP call after the GUI updates. Do not report a successful display without evidence. A headless build can save the group. It cannot prove that a tree view is visible. Do not change global TreeView settings.

Save after successful expansion to preserve group and operation states. After the file opens, the document itself can appear collapsed. Use the same GUI component to expand it.

## Required verification

Compare all operation IDs and the direct group order with the current operation graph.
Make sure that geometry, dependencies, and available visibility states remain unchanged.
Change and restore one permitted parameter under the run test policy.
Then reopen the saved file and repeat the checks.
A headless server must complete these checks without the optional tree-expansion helper.

Record test inputs, expected results, actual results, and tool versions outside this skill.
This reference contains no part-specific tests or measured case results.
This view does not replace semantic PMI or adapter capability verification.

Primary sources: [FreeCAD Tree view](https://github.com/FreeCAD/FreeCAD-documentation/blob/main/wiki/Tree_view.md) describes dependency display. [FreeCAD ViewProviderLink.cpp](https://github.com/FreeCAD/FreeCAD/blob/main/src/Gui/ViewProviderLink.cpp) shows that normal links can inherit children from the linked ViewProvider. Links do not provide a general method for a flat operation view.
