# MCP-Ausführung und AP242-Darstellung

## Prozessführung ohne Skriptdateien

1. `get_rpc_status` und verfügbare FreeCAD-MCP-Werkzeuge prüfen. Bei ungesundem Dispatcher keine weiteren GUI-Aufgaben aufstauen.
2. `execute_code_headless` bevorzugen, wenn er verfügbar und funktionsfähig ist; vor Nutzung klären, ob die konkrete Implementierung die Vorgabe ohne Skriptdateien erfüllt. Geprüfter lokaler Fallback: über `execute_code` einen separaten `FreeCADCmd`-Prozess mit Inline-Code auf stdin starten. Er benötigt weiterhin den GUI-RPC als Brücke. Nur der Kindprozess arbeitet headless; `FreeCAD.GuiUp == 0` dort nachweisen.
3. Ausführbare Programme aus der installierten FreeCAD-Umgebung ermitteln, nicht einen fremden Python-Interpreter raten. PythonOCC und FreeCAD können verschiedene Interpreter/ABI-Kontexte benötigen. Im Referenzlauf funktionierten getrennte Kindprozesse.
4. Auf Windows Kindprozesse ohne sichtbares Fenster und ohne Shell starten. Argumentlisten, stdin, Capture und endliche Timeouts verwenden. Keine `.py`, `.FCMacro`, `.ps1`, `.bat` oder ähnlich ausführbaren Dateien erzeugen.
5. Jede Inline-Ausführung importiert ihre Abhängigkeiten und erhält alle Eingaben explizit. Ein Erfolgssentinel bzw. strukturiertes Ergebnis ist Pflicht: `FreeCADCmd -c` kann trotz Python-Ausnahme mit Exitcode 0 enden.
6. GUI-/Dokumentmutationen nur auf dem GUI-Thread mit `execute_code`, bzw. über `commit()` bei ausdrücklich geeigneter Async-Arbeit. Keine parallelen Schreibzugriffe auf dasselbe Dokument oder denselben MCP-Namensraum.

Im Speicher ausgeführtes Startmuster, als Dokumentation und nicht als Skriptdatei:

```python
# Innerhalb des FreeCAD-MCP; cad_payload ist ein vollständiger Inline-Text.
result = subprocess.run(
    [freecadcmd_path, "-c"],
    input="exec(" + repr(cad_payload) + ")\n",
    capture_output=True, text=True, timeout=60,
    creationflags=0x08000000,  # Windows: kein sichtbares Konsolenfenster
)
assert result.returncode == 0
assert "CAD_RUN_SUCCESS:" in result.stdout
```

Für den separaten PythonOCC-Prozess ist `python -u -c "import sys; exec(sys.stdin.read())"` mit dem vollständigen Payload auf stdin geeignet. Lange Codes nicht in die Windows-Kommandozeile einbetten. Logs begrenzen, Fehler und strukturiertes Ergebnis erhalten. Nach einem Timeout erst Status bzw. Prozessende klären; nicht unkontrolliert erneut schreiben.

## Geprüfte Werkzeugkette

Referenzbefund: FreeCAD 1.1.4, OCCT 7.8.1, Python 3.11.14, PythonOCC 7.8.1.1, MCP-Addon 0.1.27. Das ist ein getesteter Stand, keine Behauptung über andere Versionen. Bei geänderter Werkzeugkette kleine Fähigkeitenproben ausführen und neue Nachweise protokollieren.

## Konstruktionsbaum im STEP

Im geprüften OCC-Binding schreiben/lesen `RWBooleanResult` nur `SolidModel`-Operanden und `RWCsgSolid` nur `BooleanResult` als Wurzel. Direkte `CsgPrimitive`-Wurzeln bzw. nackte boolesche Operanden führten zu Nullreferenzen. Folgender standardbasierter Aufbau wurde geschrieben und zurückgelesen:

```text
CSG_SHAPE_REPRESENTATION
  CSG_SOLID
    BOOLEAN_RESULT
      EXTRUDED_FACE_SOLID
      CSG_SOLID oder EXTRUDED_FACE_SOLID
```

- Zylinder als Extrusion einer kreisförmigen `FACE_SURFACE`, Quader als Extrusion eines Rechteckprofils darstellen. Das sind auswertbare Konstruktionselemente mit Profilparametern und Tiefe.
- Kreisprofil: `FACE_OUTER_BOUND → EDGE_LOOP → ORIENTED_EDGE → EDGE_CURVE → CIRCLE`; geschlossener Kreis mit identischem Start-/End-Vertex. Kreis und ebene Fläche verwenden dieselbe Achsplatzierung.
- Polygonprofil: `FACE_OUTER_BOUND → POLY_LOOP`; Punkte in Repräsentationskoordinaten, zugehörige `PLANE`, eindeutige Umlaufrichtung. Beim Import die Ebenenplatzierung nicht nochmals auf bereits globale Punkte anwenden.
- Jede boolesche Operation als `BOOLEAN_RESULT` in `CSG_SOLID` kapseln. Beide Operanden über `BooleanOperand.SetSolidModel()` setzen. `CsgSelect.SetBooleanResult()` setzt den entsprechenden Auswahltyp.
- Halbzylinder im Befestigung-Fall als Schnittmenge aus Vollzylinder und Quader darstellen. Diese zusätzlichen Operationen sind transparent; nicht als ursprüngliche Benutzeraktionen ausgeben.
- Den CSG-Baum über `SHAPE_REPRESENTATION_RELATIONSHIP` mit der BREP-Repräsentation desselben Produkts und identischem Einheitenkontext verbinden. Alle Referenzen mit exportieren.

Der Adapter liest die CSG-Repräsentation, löst Hüllen auf, erhält DAG-Teilungen und Operandenreihenfolge, rekonstruiert dann native primitive/extrudierte/boolesche Objekte. Ein einzelnes natives `Part::Feature` mit zugewiesener End-Shape erfüllt die Editierbarkeit nicht.

## Semantischer PMI-Export

Geprüfter Weg: XCAF-Dokument, Shape-/Subshape-Labels, `XCAFDoc_Dimension` mit `XCAFDimTolObjects_DimensionObject`, `STEPCAFControl_Writer` mit DimTol-/Name-Modus. Beim Shape-Root gegebenenfalls zunächst XCAF-Referenz auflösen; andernfalls können Subshape-Labels leer sein.

- `TDocStd_Document('BinXCAF')` und `TDataStd_Name.Set(label, 'name')` erhielten im getesteten Binding normale Python-Strings. Unpassende String-Wrapper können native Abstürze auslösen.
- Writer einmal initialisieren, `write.step.schema` auf `AP242DIS` und Längeneinheit setzen, danach Writer neu erzeugen. Schema-Header der geschriebenen Datei prüfen; eine gesetzte Option allein beweist AP242 nicht.
- Eindeutige `source_id` als Beschreibung an jeder Dimension speichern. Beschreibungseinträge des geprüften Bindings sind 0-basiert.
- Bei `Location_Angular` benötigte der getestete Writer Radiant; der XCAF-Reader lieferte Grad. Tatsächliche STEP-Einheit separat prüfen; keine doppelte Umrechnung.
- `Location_Oriented` plus `SetDirection` löste im getesteten Reader einen nativen Absturz aus. Proben in isolierten Prozessen durchführen und nur nachgewiesene Alternativen wählen.
- Bei abgeleiteten Winkelmaßen Linien zwischen Achsmittelpunkten als `CONSTRUCTIVE_GEOMETRY_REPRESENTATION` anlegen; `DERIVED_SHAPE_ASPECT`, `SHAPE_ASPECT_DERIVING_RELATIONSHIP` und `GEOMETRIC_ITEM_SPECIFIC_USAGE` mit den tatsächlichen Quellflächen verknüpfen. Nicht bloß einen Winkelwert an beliebige Flächen hängen.
- Der XCAF-Reader 7.8.1 verkürzte die Herkunftskette der Winkellinien. Deshalb Ableitungsgraph direkt aus den STEP-Entities prüfen, zusätzlich zum Werte-Round-trip.

## Grafische PMI und FreeCAD-Anzeige

An die semantische Dimension `SetPresentation(shape, name)`, `SetPlane(gp_Ax2(...))` und `SetPointTextAttach(gp_Pnt(...))` setzen. Text-/Maßlinien vor Export mit festgelegter Deflektion polygonisieren; direkte B-Spline-Kontrollpunkte sind kein verlässliches Textbild.

Prüfe je PMI `TESSELLATED_ANNOTATION_OCCURRENCE`, `DRAUGHTING_CALLOUT`, `ANNOTATION_PLANE` und `DRAUGHTING_MODEL_ITEM_ASSOCIATION` sowie die richtige semantische Gegenstelle. Anzahl allein genügt nicht.

Für FreeCAD kann der Importadapter Polylinien aus STEP als sichtbare Geometrie und semantische Datensätze mit STEP-Quellverweisen rekonstruieren. Native Anzeigeobjekte sind keine Zusage, dass FreeCADs Standardexport semantische PMI erhält. Ansichtsgruppen und ausreichenden Kontrast vorsehen. Nach Geometrieänderungen PMI explizit als ungeprüft markieren, bis Werte, Bezüge und Darstellung neu validiert wurden.

Für stabile geometrische Anker nicht die Darstellungstessellierung verwenden: Kanten-Bounds über eine unvermaschte Kopie ermitteln; bei getrimmten Flächen `face.copy(True, False).optimalBoundingBox(False, False)` verwenden. Auch eine gewöhnliche unvermaschte `BoundBox` kann bei Toroidflächen je nach Parametrisierung unterschiedliche konservative Grenzen liefern. Im Maschinenteil-Review beseitigte die optimale Box diese Abweichung ohne Toleranzlockerung. Eindeutige Flächen-/Kantentreffer und die weiteren geometrischen Signaturen bleiben erforderlich.

Kamerabefehle können animieren. Vor einer Ansichtskontrolle die tatsächlich erreichte Kameraorientierung prüfen und erst anschließend aufnehmen; ein sofortiger Screenshot nach `viewTop()` oder `setCameraOrientation()` kann einen Zwischenwinkel zeigen. Unterschiedliche PMI- und Reviewebenen getrennt anzeigen.

## Technische Primärquellen

Bei API-/Versionsänderungen diese Quellen gezielt prüfen; sie sind keine zusätzlichen Konstruktionsquellen:

- [AP242 CSG shape representation](https://www.steptools.com/docs/stp_aim/html/t_csg_shape_representation.html)
- [CSG solid](https://steptools.com/docs/stp_aim/html/t_csg_solid.html)
- [Boolean result](https://steptools.com/docs/stp_aim/html/t_boolean_result.html)
- [Extruded face solid](https://steptools.com/docs/stp_aim/html/t_extruded_face_solid.html)
- [OCCT STEP translator](https://dev.opencascade.org/doc/overview/html/occt_user_guides__step.html)
- [FreeCAD AP242 support tracking](https://github.com/FreeCAD/FreeCAD/issues/19795)
- [FreeCAD GDT import discussion](https://github.com/FreeCAD/FreeCAD/issues/29796)
