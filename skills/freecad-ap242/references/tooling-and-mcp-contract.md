# Toolinventar, gemeinsame MCP-Schnittstelle und CAD-Dienstentwurf

Stand: 2026-10-17. `drawing2cad-mcp` im gleichnamigen Projektordner bündelt PDF-Aufbereitung und den bestehenden FreeCAD-MCP. Die Benutzung steht in [drawing2cad-mcp.md](drawing2cad-mcp.md). Der Live-Katalog enthält die lokalen PDF-Tools und dynamisch weitergeleitete `freecad_*`-Tools; die 17 FreeCAD-Aufrufe unten sind der erhaltene Upstream-Snapshot vom 2026-10-16. Die fachlichen `cad_*`-Tools in Abschnitt 6–9 bleiben **Entwurf, nicht implementiert**. Die AP242-Funktionen bleiben dokumentierte Inline-Bausteine. Es gibt keinen allgemeinen Zeichnungsparser und keinen universellen parametrischen STEP-Dienst.

Der Ablauf und die Pflichtnachweise stehen in [model-agnostic-workflow.md](model-agnostic-workflow.md), der Modellinhalt in [model-contract.md](model-contract.md). CAD-Arbeit erfolgt über die FreeCAD-Werkzeuge des gemeinsamen MCP. Inline-Python ist zulässig; keine ad hoc erzeugten `.py`, `.FCMacro`, `.ps1`, `.bat` oder anderen ausführbaren Modellhilfsdateien anlegen. Der vom Nutzer beauftragte, versionierte Python-Server ist eine eigene Softwarekomponente. Seine PDF-Pfadfreigabe begrenzt nicht den Inhalt beliebigen Python-Codes im FreeCAD-Proxy.

## 1. Nachweise und Erfassungsgrenzen

Die folgende Tabelle dokumentiert den FreeCAD-Toolstand vom 2026-10-16. Für jeden neuen Lauf den Live-Katalog einschließlich Beschreibungen und Eingabeschemata abfragen; der Proxy übernimmt die aktuelle Upstream-Schnittstelle. Generierte Katalogdateien sind lokale Laufartefakte und kein Bestandteil des versionierten Skills.

Versions- und Pfadbefunde für den jeweiligen Host neu ermitteln. Sie sind keine Installationsvoraussetzung mit weltweit gültigen Pfaden. Geprüfte Referenzversionen, darunter PythonOCC `7.8.1.1`, sind in [execution-and-ap242.md](execution-and-ap242.md) dokumentiert; ihre Verfügbarkeit auf einem neuen Host ist gesondert zu prüfen.

Neue Inventare, Host-Snapshots und Prüfberichte unter dem ignorierten `output/` des Projekts ablegen. Historische Dateien unter `references/tooling/` können lokal vorhanden sein, sind ebenfalls ignoriert und werden vom Skill nicht vorausgesetzt. Die maßgeblichen Ausführungsregeln, Adaptereinstiege und Schnittstellenentwürfe stehen in dieser Referenz und den verlinkten Workflow-Dokumenten.

Die Erfassung unterscheidet `advertised` (Tool verfügbar), `observed` (lokal festgestellt), `verified_subset` (durch benannte Probe belegt), `untested` und `unsupported`. Eine Toolbeschreibung allein belegt weder eine erfolgreiche Ausführung noch den vollständigen Funktionsumfang. Referenzmodelle liefern ausschließlich Testbelege; Maße, Objektbezeichnungen, PMI-Anzahlen und Layout aus anderen Zeichnungen werden niemals in einen neuen Modellauftrag übernommen.

## 2. FreeCAD-Upstream-Snapshot und Proxy-Zuordnung

Über `drawing2cad-mcp` heißt beispielsweise `execute_code` nun `freecad_execute_code`, `get_rpc_status` heißt `freecad_get_rpc_status`. Der clientseitige Namespace vor dem Toolnamen hängt vom Host ab. Eingabeschemata und MCP-Ergebnisinhalte stammen weiterhin vom bestehenden FreeCAD-Server. Das Präfix ist keine neue CAD-Implementierung. Fehlt der Upstream, bleiben PDF-Werkzeuge nutzbar; CAD-Erreichbarkeit getrennt prüfen. Die folgenden historischen Aufrufe nicht als zweiten gleichzeitig nötigen Agentenzugang konfigurieren.

Der gemeinsame Rückgabetyp ist `CallToolResult`, typischerweise Text und optional Screenshot. Für Fehler und Messwerte existiert in dieser Tooloberfläche kein durchgängig verbindliches fachliches Ergebnisschema. Deshalb strukturierte Resultate des Inline-Adapters zusätzlich prüfen.

Folgende Kurzdefinitionen enthalten alle im historischen Stand angebotenen Parameter; `?` bedeutet optional. `View` ist `Isometric | Front | Top | Right | Back | Left | Bottom | Dimetric | Trimetric`. `Record` bedeutet `{[key:string]:unknown}`. Für die tatsächlich installierte Version sind die Beschreibungen und Schemata des Live-Katalogs maßgeblich.

| Tatsächlicher Toolname | Eingabe | Zweck / Ausführungsgrenze |
|---|---|---|
| `mcp__freecad__create_document` | `{name:string}` | Neues GUI-Dokument. |
| `mcp__freecad__create_object` | `{doc_name:string,obj_name:string,obj_type:string,obj_properties?:Record,analysis_name?:string\|null,include_screenshot?:boolean,view_name?:View}` | Native Objekte; FEM-Hilfen verfügbar, für AP242 nicht benötigt. |
| `mcp__freecad__edit_object` | `{doc_name:string,obj_name:string,obj_properties:Record,include_screenshot?:boolean,view_name?:View}` | Eigenschaften schreiben; dokumentgebundene Mutation. |
| `mcp__freecad__delete_object` | `{doc_name:string,obj_name:string,include_screenshot?:boolean,view_name?:View}` | Objekt löschen; nur explizit zum Lauf gehörende Objekte. |
| `mcp__freecad__execute_code` | `{code:string,include_screenshot?:boolean,view_name?:View,timeout?:number\|null}` | Vollständiges Inline-Python auf dem GUI-Thread. Timeout: positive endliche Sekunden, Standard 90, maximal 1800; Queue- und Ausführungsbudget jeweils. |
| `mcp__freecad__execute_code_async` | `{code:string}` | Hintergrundthread für schwere reine Geometrieberechnung. **Kein isolierter Prozess.** GUI-/Dokumentschreiben nur über injiziertes `commit(fn,timeout=120)`. |
| `mcp__freecad__execute_code_headless` | `{code:string,timeout?:number}` | Angeboten: separater `freecadcmd`, Standardtimeout 600 s. Lokal Befund `freecadcmd not found`; Einhaltung des Verbots temporärer Skriptdateien ungeklärt. Derzeit kein freigegebener Ausführungsweg. |
| `mcp__freecad__get_async_status` | `{job_id?:string}` | Status von Async-Jobs; leer: laufende und bis zu 20 kürzlich abgeschlossene. Flüchtige Historie bis FreeCAD-Ende. |
| `mcp__freecad__get_rpc_status` | `Record` (normal `{}`) | RPC-/GUI-Dispatcherzustand, hängende Operation, Versionsabgleich; funktioniert ohne GUI-Thread. |
| `mcp__freecad__get_object` | `{doc_name:string,obj_name:string,include_screenshot?:boolean,view_name?:View}` | Eigenschaften eines Objekts lesen. Für rein lesende Inventur `include_screenshot:false`. |
| `mcp__freecad__get_objects` | `{doc_name:string,include_screenshot?:boolean,view_name?:View}` | Objekte/Eigenschaften eines Dokuments lesen. |
| `mcp__freecad__list_documents` | `Record` (normal `{}`) | Offene Dokumentnamen lesen. |
| `mcp__freecad__get_view` | `{view_name:View,width?:number\|null,height?:number\|null,focus_object?:string\|null}` | Tatsächlichen aktiven View aufnehmen, Ausrichtung/Fokus anwenden; daher keine zustandsneutrale Inventur. |
| `mcp__freecad__reload_document` | `{doc_name:string}` | Offenes Dokument schließen und aus seiner Datei neu laden. Vorher Zustand/ungesicherte Änderungen beachten; kein harmloser Leseaufruf. |
| `mcp__freecad__get_parts_list` | `Record` (normal `{}`) | Teilebibliothek inventarisieren; kein Bestandteil des geprüften Rekonstruktionspfads. |
| `mcp__freecad__insert_part_from_library` | `{relative_path:string,include_screenshot?:boolean,view_name?:View}` | Bibliotheksteil einfügen; wäre zusätzliche Konstruktionsquelle und braucht Auftragsdeckung. |
| `mcp__freecad__run_fem_analysis` | `{doc_name:string,analysis_name:string,timeout?:number,include_screenshot?:boolean,view_name?:View}` | CalculiX/FEM; blockiert GUI synchron, keine parallelen RPC-Schreibaufrufe. Angeboten, in diesem AP242-Ablauf nicht geprüft. |

Screenshots sind bei den optionalen `include_screenshot`-Aufrufen standardmäßig aktiv. Für analytische Aufrufe ausschalten. `execute_code` teilt einen lebenden Python-Namensraum: jeder Payload importiert Abhängigkeiten selbst, erhält vollständige Eingaben und benutzt eigene Namen. Schreibende Aufrufe verschiedener Agenten auf demselben Dokument oder Namensraum serialisieren.

## 3. Host, Interpreter, Bibliotheken und Hilfsmittel

| Bestandteil | Beobachteter Stand / genauer Pfad | Verwendung und Grenze |
|---|---|---|
| FreeCAD | 1.1.4; Commit `4fd3bf320d9566a27e60069fc8387448aaa3a094` | Native Dokumente und Operationsbaum. |
| OCCT | 7.8.1 | BREP, boolesche Operationen, Verrundung, STEP/XCAF. |
| Python in FreeCAD | 3.11.14, conda-forge, MSC v.1944 AMD64 | ABI dieses Builds; nicht mit beliebigem System-Python ersetzen. |
| PythonOCC | 7.8.1.1, dokumentierter Referenzstand | `OCC.Core.*`; Bindinggrenzen separat beachten. |
| MCP-Addon | 0.1.27, beobachtet | RPC-Brücke; nicht mit einer unabhängig bestätigten Serverpaketversion gleichsetzen. |
| GUI | `C:/Program Files/FreeCAD 1.1/bin/FreeCAD.exe` | Bestehende MCP-Verbindung und tatsächliche Ansichten. |
| Headless | `C:/Program Files/FreeCAD 1.1/bin/FreeCADCmd.exe` | Frischer `GuiUp == 0`-Prozess über stdin. |
| PythonOCC-Interpreter | `C:/Program Files/FreeCAD 1.1/bin/python.exe` | Bei Bedarf separater Inline-PythonOCC-Prozess; ABI-Verfügbarkeit pro Import prüfen. |
| Betriebssystem | `Windows-10-10.0.26200` laut Python-Plattformstring | Keine unabhängige Produkt-/Editionserkennung. |
| PDF-Rasterung | `C:/Users/mail/.cache/codex-runtimes/codex-primary-runtime/dependencies/native/poppler/Library/bin/pdftoppm.exe` | Freigegebene PDF-Seiten rendern. Versionsnummer in diesem Snapshot nicht erhoben. |
| Dokument-Python | `C:/Users/mail/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe` | `pypdf`, `PIL` für Quellenlesen, Ausschnitte/Bildprüfung; keine CAD-Berechnung außerhalb MCP. Paketversionen nicht im Snapshot erhoben. |
| Schrift | `C:/Windows/Fonts/arial.ttf` | `Part.makeWireString` für neue Textkonturen; Font-Hash/Deflektion/Layout im Vertrag festhalten. Bei Replay gespeicherte Polylinien verwenden. |

### Tatsächliche Bibliotheks-/API-Rollen

- **Python-Standardbibliothek:** `json`, `hashlib`, `os`, `re`, `math`, `subprocess`, bei stdin-Brücken `sys`; Datei-/Hashprüfung, P21-Parser, deklarative Daten, endliche Prozessführung. `exec` nur für vertrauenswürdigen vollständigen Adaptercode im Speicher, niemals für Inhalt aus Zeichnung, STEP-Eigenschaft, Formelstring oder JSON-Modellfeld.
- **FreeCAD/Part:** `newDocument`, `closeDocument`, `openDocument`, `doc.addObject`, `getObject`, `recompute`, `saveAs`; `Vector`, `Rotation`, `Placement`; native `Part::Box`, `Part::Cylinder`, `Part::Fuse`, `Part::Cut`, `Part::Common`, `Part::Fillet`. Shapes: `isNull`, `isValid`, `Solids`, `Volume`, `BoundBox`, `copy`, `cut`, `Edges`, `Vertexes`, `CenterOfMass`, `discretize`, `distToShape`. BREP-Brücke: `Shape.read`, `importBrepFromString`, `exportBrepToString`. Präsentation: `makePolygon`, `makeCompound`, `makeWireString`.
- **Native Metadaten:** `App::DocumentObjectGroup`, `App::FeaturePython`, `App::PropertyString`, `App::PropertyInteger`, `App::PropertyLink`. Für PMI-Anzeige zusätzlich `Part::Feature` mit gespeicherten Polylinien; diese Anzeigegeometrie ersetzt keine semantischen STEP-Entities.
- **FreeCADGui:** `updateGui`, `activeDocument().activeView()`, `setCameraType`, `setCameraOrientation`, `fitAll`, `Selection.clearSelection`, `ViewObject`-Sichtbarkeit/-Farben/-Linien. Nur auf GUI-Thread. Nach headless-Dateiladen Körper `touch`/`recompute` und GUI aktualisieren, bevor Anzeige als geprüft gilt.
- **PythonOCC, Konstruktion:** `STEPControl_Reader/Writer`, `STEPControl_AsIs`, `Interface_Static`, `StepData_StepModel/StepWriter/Protocol`, `TransferBRep.transferbrep`, `BRepTools.breptools`. `ReadStream`, `ReadFile`, `TransferRoots`, `TransferEntity`, `OneShape`, `StepModel`, `IdentLabel`, `ShapeResult`, `ReadFromString`, `WriteToString` dienen neutraler Geometrie und echten Kantenreferenzen.
- **PythonOCC, semantische/grafische PMI:** `TDocStd_Document`, `TDataStd_Name`, `TDF_Label/LabelSequence`, `XCAFDoc_DocumentTool/Dimension`, `XCAFDimTolObjects_DimensionObject`, `STEPCAFControl_Writer/Reader/GDTProperty`, `gp_Pnt/Dir/Ax2`, `TopExp_Explorer`, `TopAbs_*`, `TopoDS.topods`, `TColStd_HArray1OfReal`, ausgewählte `StepGeom`, `StepRepr`, `StepShape`, `StepAP242`, `StepVisual`, `StepBasic`, `STEPConstruct`-Bindings. Das Inventar dieser APIs ist keine pauschale Unterstützung aller ihrer Typen.
- **Ergänzter UI-Adapter:** `Sketcher`, `Sketcher::SketchObject`, `Part.LineSegment`, `Sketcher.Constraint` mit `Coincident`, `Horizontal`, `Vertical` und `Distance`, `renameConstraint`, `FullyConstrained`; `Part::Extrusion` mit `LengthFwd`; `Spreadsheet::Sheet`, `set`, `setAlias`, `mergeCells`, Stile/Spaltenbreiten und `setExpression`. [inline-editable-ui-adapter.md](inline-editable-ui-adapter.md) bildet im dokumentierten Maschinenteil-Fall sechs Rechteckextrusionen auf vollständig bemaßte Skizzen ab und bindet 56 unabhängige aus STEP gelesene Maße an die Tabelle. Das ist eine ausdrücklich rekonstruierte Bedienzuordnung; gemeinsame Muster-/Lagebeziehungen und ursprüngliche Benutzerhistorie werden nicht behauptet. Expressions werden aus validierten Namen und festem Adaptercode erzeugt, nicht als frei ausführbarer Modelltext übernommen.
- **Ergänzter Review-Renderer:** `Part.makeLine`, `Part.makeCircle`, unvermaschte Flächenkopie `copy(True,False)`, `App::Annotation`, `App::PropertyLinkList`, `App::PropertyLinkSubList`; Geometriefingerprints werden vor der Markererzeugung auf eindeutige Treffer geprüft. Siehe [inline-review-markers.md](inline-review-markers.md). Dies ist ein Anwendungsschema für getrennte Reviewobjekte, keine allgemeine PMI- oder automatische Neuverankerungslösung.
- **Nicht als implementierte Abhängigkeit behaupten:** `Draft` und `Import`/`ImportGui` sind keine notwendige oder nachgewiesene Grundlage dieses prozeduralen Adapters. Eine vorhandene FreeCAD-Arbeitsumgebung beweist keinen vollständigen Constraint-/Spreadsheet-/Standardexport-Rückweg. Die UI-Ergänzung erweitert den Basisadapter um ihren eigenen belegten Teilumfang.

Getrimmte Reviewflächen nutzen zusätzlich `face.copy(True,False).optimalBoundingBox(False,False)`: gewöhnliche Bounds können trotz entfernter Triangulation konservative, parametrisierungsabhängige Grenzen liefern. Das geprüfte Profil validiert Millimeter, Ziel-Root, Namespace, eindeutige IDs, Statusklassen und endliche Anzeigegeometrie vor der Mutation. Dies ersetzt keinen universellen JSON-Schema-Validator. Für Bildränder wurde außerdem die orthographische Kamerahöhe über `activeView().getCameraNode().height.getValue()/setValue()` angepasst; der von FreeCAD bereitgestellte Coin-Knoten benötigt dafür keinen zusätzlichen externen Prozess.

### Werkzeuge außerhalb der CAD-Ausführung

PDF-Lesen, Rendering und Ausschnitte laufen jetzt über `drawing2cad-mcp`: `pypdf`, Poppler und Pillow sind Serverabhängigkeiten; Agenten benötigen dafür keinen eigenen Shell-/Python-Aufbereitungscode. MCP-Bildinhalte oder die zurückgegebenen Bildartefakte tatsächlich ansehen. `functions.exec`/`ALL_TOOLS` sind eine mögliche Host-Orchestrierung, keine Abhängigkeit des Skills. `exec_command`/PowerShell (`rg`, `Get-Content`, `ConvertFrom-Json`, `Get-FileHash`) und `apply_patch` dienen weiterhin Software-/Dokumentpflege und Inventur. `view_image` kann lokale PDF-Rasterungen und CAD-Captures zur Sichtprüfung anzeigen. `open_in_codex` öffnet Dateien zur Übergabe und ist kein fachlicher Prüfer. `load_workspace_dependencies` ermittelt gegebenenfalls gebündelte Laufzeiten auf einem neuen Host; andere Agenten können die dokumentierten Serverabhängigkeiten regulär installieren.

`collaboration.spawn_agent`, `send_message`, `followup_task`, `list_agents`, `wait_agent` und `interrupt_agent` koordinieren getrennte Arbeitsaufträge und Dateibesitz. Sie sind optionale Orchestrierung, keine Voraussetzung für die Modellreproduktion. CAD-Entscheidungen/Nachweise müssen im Resume-Paket liegen, nicht nur in Agentenmeldungen. Web-/Browserwerkzeuge sind allenfalls für gezielte Primärquellen-/API-Recherche nötig; sie dürfen keine ungeprüften Modellquellen oder CAD-Mutationen an der MCP-Grenze vorbeiführen.

## 4. Tatsächlich ausführbarer Weg ohne Skriptdateien

Der geprüfte lokale CAD-Weg bleibt `freecad_execute_code → FreeCAD-MCP.execute_code → subprocess → FreeCADCmd.exe -c → stdin`. Er benötigt weiterhin eine gesunde GUI-RPC-Brücke; nur das Kind ist headless. `drawing2cad-mcp` beseitigt diese Upstream-Abhängigkeit nicht. Ein eigenständiger CAD-Worker ohne gestartete GUI gehört zum späteren `cad_*`-Entwurf. `freecad_execute_code_headless` erst nach behobenem Programmpfad und nachgewiesen dateifreier Upstream-Implementierung verwenden.

Innerhalb eines vollständigen MCP-Inline-Aufrufs ist folgendes Muster zulässig. Pfade, `run_id`, Hashes und Payload stammen aus freigegebenem Ausführungsumschlag; dieses Beispiel wird nicht als Datei gespeichert:

```python
import subprocess as tool3_subprocess
import json as tool3_json

# tool3_payload enthält vertrauenswürdigen Adaptercode plus separat validierte Daten.
# Er importiert FreeCAD selbst, prüft GuiUp == 0 und erzeugt am Ende genau eine
# Zeile CAD_RUN_SUCCESS:<JSON mit run_id, phase, input_hashes, artifacts, metrics>.
tool3_result = tool3_subprocess.run(
    [tool3_freecadcmd_path, '-c'],
    input='exec(' + repr(tool3_payload) + ')\n',
    capture_output=True, text=True, timeout=tool3_timeout_seconds,
    creationflags=tool3_subprocess.CREATE_NO_WINDOW,
    shell=False,
)
tool3_lines = [s[len('CAD_RUN_SUCCESS:'):]
               for s in tool3_result.stdout.splitlines()
               if s.startswith('CAD_RUN_SUCCESS:')]
if tool3_result.returncode != 0 or len(tool3_lines) != 1:
    raise RuntimeError('WORKER_FAILED_OR_MISSING_RESULT')
tool3_report = tool3_json.loads(tool3_lines[0])
# Danach run_id, Eingabehashes, Artefakte und fachliche Gates prüfen.
```

`FreeCADCmd -c` kann nach einer Python-Ausnahme Exitcode 0 liefern. Exitcode, genau ein passendes Ergebnissignal und fachliche Validierung sind gemeinsam erforderlich. Der Sentinel muss auf den aktuellen Lauf bezogen sein; ein zufälliger Logtext darf keinen Erfolg auslösen. Der separate PythonOCC-Aufruf verwendet `[python_path, '-u', '-c', 'import sys; exec(sys.stdin.read())']` mit vollständigem Code auf stdin, ebenso `CREATE_NO_WINDOW`, `shell=False`, Capture und Timeout.

Das heutige `subprocess.run`-Muster ist synchron. Für längere Jobs ist das äußere MCP-Budget größer als das Kindbudget einschließlich Fehlerbehandlung zu setzen. Ein GUI-Timeout beendet Arbeit nicht zuverlässig. Zuerst `get_rpc_status`/gegebenenfalls Jobstatus und tatsächliche Ausgaben klären, bevor erneut geschrieben wird. Async ist keine Lösung für ungeschützte Dokumentmutationen. Eigene Laufpfade und Namenspräfixe verhindern Kollisionen; sie ersetzen keine Serialisierung.

## 5. Vorhandene Adapterbausteine und belegter Umfang

| Dokumentierter Einstieg | Explizite Inputs → Outputs | Nachgewiesene Grenze |
|---|---|---|
| `sth_p21_parse`, `sth_p21_validate_refs` | P21-Text → Records/Referenzprüfung | Eigener begrenzter Parser, keine EXPRESS-Zertifizierung. Defaults: 32 MiB, 200000 Records, 2000000 Knoten, Tiefe 128, String 1 MiB. |
| `sth_export_constructive(step_path,contract_path,build_path,out_path)` | PMI-/BREP-Präfix, freigegebener Vertrag, Buildbericht und Zwischen-BREPs → neuer konstruktiver STEP + Bericht | mm; achsparallele Rechtecke, vollständige Kreise +Z/+X, verfeinerte Boolesche, konstante Verrundung mit eindeutigen Kantenankern. |
| `sth_decode_step(step_path)` | Nur STEP → neutraler Operationsgraph, Wurzel, Einheiten/Referenzen | Genau eine prozedurale Sequenz; explizite vorherige Operanden; keine still verlorenen unverbundenen Operationen. |
| `sth_rebuild_step(step_path,fcstd_path=None,docname=...)` | Nur STEP als Modellquelle → Dokument, Endfeature, Featuremap, Beweisbericht, decodierte Operationen | Native editierbare Part-Operationen; unabhängiger End-BREP-Vergleich; keine ursprünglichen unbekannten Skizzenzwänge. |
| `sth_verify_replay(...)` | STEP + Berichtspfad → Mess-/Änderungsbericht | Fallbezogener Maschinenteil-Regressionstest; keine generische Sollprüfung. Zahlen und Features nicht auf neue Teile übertragen. |
| `read_step_pmi_extended(path,expected_count=None)` | Nur STEP → `annotations`, `metadata_properties` | Nominale Größen/Lagen/Winkel; Gewindebezeichnung als Text; positive allgemeine Radiusangabe; Geometriebezüge und gespeicherte Polylinien. Toleranz-/Datumfamilien werden abgelehnt. |
| `add_step_pmi_to_native(doc,data,source_path,root_name)`, `show_step_pmi_view(...)` | Decodierte STEP-PMI + natives Dokument → Semantik-/Anzeigeobjekte und Ansicht | Vorhandene Ebenengruppierung ist fallbezogen; kein automatischer PMI-Neuaufbau nach Änderungen. |
| `append_adapter_properties(source_path,output_path,properties)` | Vorhandener STEP + deklarative Metadaten → separater Kandidat/Bericht | Erhält bestehende Entities; pro Eigenschaft `n+3` Standardentities für `n` JSON-Textstücke, maximal 4000 ASCII-Zeichen je Stück und insgesamt 2 MiB; keine stillen Duplikate. |
| `read_adapter_properties(step_path,expected_schemas)` | Nur STEP + bekannte Schemakennungen → deklarative Metadaten | Eindeutige Eigenschaften/Verknüpfungen, Produkt-/Kontextbindung, Schema, Chunkreihenfolge/-vollständigkeit und doppelte JSON-Schlüssel geprüft; Geometrie-/Darstellungsnachweis bleibt eigener Test. |
| `hist3_make_box`, `hist3_apply_ui`, `hist3_rebuild_editable(step_path,fcstd_path=None,docname=...)` | Nur STEP-Operationsentities und darin gespeicherte UI-Property → native Operationen, ausgewählte Rechteckskizzen/Extrusionen, Parametertabelle und Bericht | Dokumentierter Maschinenteil-Teilumfang: sechs vollständig bemaßte Rechteckskizzen und 56 unabhängige Maße; keine gemeinsamen Muster-/Lagezwänge oder allgemeine Relationsrekonstruktion. |
| `amb3_inject_review(doc,root,metadata)` | Aus STEP gelesene `drawing2cad.review-annotations/1` + rekonstruierter Körper → separate Reviewgruppen, Umrandungen, Verweise, Text und Ankerbericht | Profil-/fallbezogene Front-/Seiten-/Globalansichten; eindeutige Flächenfingerprints und logische Feature-IDs; Darstellung und unveränderte Produktgeometrie anschließend unabhängig prüfen. |

Quellen: [execution-and-ap242.md](execution-and-ap242.md), [inline-procedural-adapter.md](inline-procedural-adapter.md), [inline-property-pmi-reader.md](inline-property-pmi-reader.md), [inline-review-envelope.md](inline-review-envelope.md), [inline-editable-ui-adapter.md](inline-editable-ui-adapter.md), [inline-review-markers.md](inline-review-markers.md). Die dokumentierte Änderungskette belegt für den getesteten Teilumfang `STEP → native Operationen → geänderter Parameter → neuer STEP → frischer Import`. Sie belegt keine automatische Relations-, PMI- oder Review-Anker-Aktualisierung. Neue UI-/Review-Bausteine benötigen zusätzlich den zum konkreten finalen STEP-Hash gehörenden Replay-/Anzeigebeleg; ihr Vorhandensein im Skill ersetzt diesen nicht.

Die Chunkserialisierung ist eine konkrete Kompatibilitätsanforderung: Ein großer einzelner JSON-String verursachte beim beobachteten OCCT-7.8.1-Leser `input buffer overflow`. Nummerierte kleine `DESCRIPTIVE_REPRESENTATION_ITEM`-Textstücke umgehen diese Grenze. Der Leser akzeptiert das ältere einteilige `application/json`-Format; neue Writer teilen lange Texte auf und prüfen den vollständigen Round-trip.

**Standard und Anwendungsschema trennen:** Der auswertbare Konstruktionsgraph liegt in standardisierten STEP-Operationsentities. Die zusätzlichen Schlüssel `drawing2cad.editable_ui.v1` / Schema `drawing2cad.editable-ui/1` und `drawing2cad.review_annotations.v1` / Schema `drawing2cad.review-annotations/1` sind anwendungsspezifische JSON-Inhalte in `PROPERTY_DEFINITION → PROPERTY_DEFINITION_REPRESENTATION → REPRESENTATION → DESCRIPTIVE_REPRESENTATION_ITEM`-Containern. Das sind keine standardisierten Constraints, keine neu erfundenen Zeichnungs-PMI und kein Beleg, dass ein fremdes CAD sie versteht. Auch eine gespeicherte UI-Beziehung ist erst dann ein parametrischer Zusammenhang, wenn ein Adapter sie validiert, wieder verknüpft und durch Änderungstest nachweist.

Die optionale native Baumansicht aus [inline-linear-history-view.md](inline-linear-history-view.md) ergänzt ab Skill 0.3.1 die Bedienung: `lin4_apply_history(doc, ordered_ids)` gruppiert die echten Originaloperationen, `lin4_expand_history(doc, group)` zeigt sie als lineare Liste. Werkzeuge bleiben `execute_code`, FreeCAD `App::DocumentObjectGroup` und für die Anzeige PySide/Qt. Es werden weder Skriptmodule noch neue Geometrie oder zusätzliche STEP-Operationsentities benötigt. Bei einem STEP-only-Aufbau stammt die Reihenfolge aus dem decodierten Operationsgraphen. Die UI ist FreeCAD-spezifisch; der STEP-Graph bleibt plattformneutral im bisher geprüften Umfang.

## 6. Weiterführender CAD-Dienstentwurf: gemeinsame Datentypen

Alle folgenden `cad_*`-Namen und Schemas sind **Entwurf, nicht aufrufbare Tools**. Sie sind nicht Bestandteil des implementierten PDF-/FreeCAD-Proxys. Ein späterer fachlicher Dienst kann diese Endpunkte über versionierten Adaptern anbieten und damit freie Python-Ausführung durch deklarative Eingaben ersetzen.

Typkonventionen: `Id` ist ein begrenzter stabiler String, `Hash` ein SHA256 in 64 Hexzeichen, `Vec3` drei endliche Zahlen; unbekannte Felder standardmäßig ablehnen. JSON-Modelldaten dürfen weder Python, Importpfade, Shellkommandos noch ausführbare Ausdrucksstrings enthalten. Erlaubte Formeln als typisierten AST mit benannten Operatoren, Dimensionsprüfung und Zyklusprüfung abbilden.

```typescript
type ArtifactRef = { artifact_id: Id; path: string; sha256: Hash;
  role: 'construction_source'|'verification_only'|'tool_reference'|'output';
  media_type: string; pages?: number[] }; // Seiten 1-basiert
type Envelope = { schema: 'drawing2cad.request/1'; request_id: Id; run_id: Id;
  phase: string; mode: 'new_drawing'|'replay_contract'|'import_step'|'edit_model';
  source_allowlist: ArtifactRef[]; output_root: string; output_paths: string[];
  adapter: {id: Id; version: string; code_sha256: Hash};
  limits: {queue_timeout_s: number; execution_timeout_s: number;
    max_memory_mb: number; max_output_bytes: number};
  required_capabilities: CapabilityRequirement[] };
type CapabilityRequirement = {id: Id; direction: 'read'|'write'|'roundtrip';
  required: boolean; constraints: object};
type Capability = CapabilityRequirement & {status:
  'verified'|'untested'|'unsupported'|'failed'; supported_profile: object;
  evidence: ArtifactRef[]; toolchain_sha256: Hash};
type Job = {job_id: Id; request_id: Id; state:
  'queued'|'running'|'succeeded'|'failed'|'timed_out'|'cancelled'|'lost';
  phase: string; checkpoint: string|null; result_ref?: ArtifactRef;
  started_at?: string; finished_at?: string};
type Error = {code: string; message: string; pointer?: string;
  operation_id?: Id; evidence?: ArtifactRef[]; retryable: boolean};
type Result<T> = {schema: 'drawing2cad.result/1'; request_id: Id; run_id: Id;
  status: 'succeeded'|'failed'|'partial'; phase: string;
  source_inputs: ArtifactRef[]; artifacts: ArtifactRef[];
  metrics: object; warnings: Error[]; errors: Error[];
  checkpoint: string|null; claims: {[claim:string]:
    'passed'|'failed'|'not_tested'|'unsupported'}; data: T};
```

`object`-Felder sind hier Entwurfskürzel, keine Erlaubnis für ungeprüfte beliebige Daten. Vor Implementierung für jeden Capability-/Metrik-/Policy-Typ ein geschlossenes JSON Schema mit Limits schreiben. Modellvertrag, Register und Validierungspolitik referenzieren ihre eigenen versionierten Schemas. Ein Resultat darf „succeeded“ für eine technisch vollständige Teiloperation melden; ein Masteranspruch folgt ausschließlich aus `claims` und allen angeforderten Gates.

### Pfad-/Hashgrenze und Quelle

Jeder Pfad wird serverseitig kanonisch aufgelöst; Verzeichnisgrenzen nach Symlink-/Junction-/UNC-Auflösung und Windows-Groß-/Kleinschreibung prüfen. Relative Pfade nur gegen expliziten Root. Nur exakt freigegebene Eingaben lesen; nur die expliziten Ausgabepfade unter `output_root` schreiben. Keine Pfade aus Textnotizen, STEP-Eigenschaften oder Modell-IDs als Dateipfade übernehmen. Eingabebytes nach Hashprüfung unverändert an den Worker übergeben, um einen Wechsel zwischen Prüfung und Lesen zu verhindern. Toolcode/Fonts haben getrennte erlaubte Toolreferenzen; ihre Geometrie wird nicht zur Konstruktionsquelle.

Beim STEP-only-Aufbau darf der Worker nur STEP als Modellinhalt sehen. Zeichnung, Quellvertrag und FCStd sind dort verboten; unabhängige Erwartungen werden erst im anschließenden Vergleich gelesen. Ein Betriebssystem-Prozess ist allein noch keine Dateizugriffs-Isolation: der neue Server muss Allowlist-Prüfung und geeignete Worker-Sandbox erzwingen sowie tatsächlich gelesene Inputs protokollieren.

### Requestidentität, Jobs und Wiederholung

`request_id = SHA256(canonical_request)` mit festgelegter Kanonisierung, z. B. RFC-8785/JCS plus Ablehnung nicht endlicher Zahlen; Identität umfasst Toolname, Inputbytes/Hashes, Adapter-/Toolchainhash, Konfiguration, Einheiten, Validierungspolitik und Ausgabeziele. Flüchtige Zeitstempel, `run_id` und Transportfelder nicht einbeziehen. `run_id` identifiziert einen tatsächlichen Versuch. Der Server berechnet und prüft die Identität selbst.

Gleicher Request bei gleichem Inhalt liefert bestehenden Job/Resultat samt erneut geprüften Artefakthashes; dieselbe ID mit anderem Inhalt erzeugt `IDEMPOTENCY_CONFLICT`. Keine stillen Wiederholungen nach Clienttimeout. Zur bewussten frischen Reproduktion `replay_nonce` als semantisches Requestfeld verwenden; neue `run_id` allein reicht nicht. Aufträge journalisieren, Status/Resultate nach Neustart erhalten und unbekannt beendete Jobs als `lost` auflösen.

Worker werden ohne GUI-Abhängigkeit gestartet, mit endlichen Queue-/Ausführungsbudgets, Prozessgruppen-/Windows-Job-Object-Abbruch, Speicher-/Ausgabelimits und stdout/stderr-Capture. Das ist geplanter Serverumfang; der aktuelle Inline-Fallback besitzt nicht all diese Garantien. Kandidaten zunächst in einem laufgebundenen Ziel schreiben, Hash/Validierung abschließen und anschließend atomar registrieren. Letzten gültigen Master erst durch ausdrücklich angeforderten Publish-Schritt mit erfüllten Gates ersetzen. Abbruch darf keinen Kandidaten automatisch zum Master erklären.

## 7. Vorgeschlagene granulare Tools

Alle Mutationen liefern zuerst `Job`; das finale `Result<T>` ist über Status/Resultat zugänglich. Kleine reine Leseprüfungen dürfen synchron `Result<T>` zurückgeben. `E` bezeichnet `Envelope`, `Ref` bezeichnet `ArtifactRef`.

| Geplanter Name | Eingabeschema zusätzlich zu `E` | Ergebnisschema `data` und wichtigste Bedingung |
|---|---|---|
| `cad_get_capabilities` | `{required:CapabilityRequirement[],refresh:boolean}`; nur Leseprobe, kein Modell nötig | `{toolchain:object,capabilities:Capability[],gaps:Error[]}`; Richtungen/Versionen/einzelne Operationen, Einheiten, PMI, Marker und Renderer getrennt. |
| `cad_observe_source` | `{sources:Ref[],pages:number[],regions?:{page:number,bbox:[number,number,number,number],unit:'pdf_point'}[],render:{dpi:number},observations?:Ref}` | `{renders:Ref[],observations:Ref,unresolved:Id[]}`; Rendering/Extraktion und agentenseitige Interpretation mit Provenienz trennen. Beobachtungen sind noch kein freigegebener Modellvertrag. |
| `cad_validate_contract` | `{contract:Ref,policy:Ref,freeze:boolean}` | `{valid:boolean,contract_sha256:Hash,canonical_model_sha256:Hash,requirements:CapabilityRequirement[],issues:Error[]}`; Schema, DAG, Einheiten, Referenzen, offene Werte, Quellen, PMI/Marker; Freeze erzeugt neue unveränderliche Revision. |
| `cad_build_native` | `{contract:Ref,validation:Ref,native_path:string,intermediate_root:string}` | `{native:Ref,build_report:Ref,root_id:Id,feature_map:Ref}`; frischer Worker, vollständiger DAG, native Operationen und Zwischengeometrie geprüft. |
| `cad_export_ap242` | `{contract:Ref,build:Ref,profile:Id,step_path:string,include:{construction:boolean,pmi:boolean,review:boolean}}` | `{candidate:Ref,export_report:Ref,representation_map:Ref}`; konstruktive Entities, End-BREP, Semantik/Präsentation getrennt prüfen; kein Standard-BREP-Export als Editierbarkeit deklarieren. |
| `cad_rebuild_step` | `{step:Ref,native_path:string,profile:Id}` | `{native:Ref,decoded_contract:Ref,rebuild_report:Ref,feature_map:Ref}`; STEP ist einzige Modellquelle, kein ursprünglicher Vertrag als versteckte Ergänzung. |
| `cad_edit_native` | `{base:Ref,base_sha256:Hash,changes:{feature_id:Id,parameter:Id,value:object}[],native_path:string}` | `{native:Ref,revision:Ref,change_report:Ref,invalidated_pmi:Id[],invalidated_markers:Id[]}`; typisierte Parameter, unterstützte Editierrichtung, Auswirkungen und Staleness. Rückexport bleibt eigenes Tool. |
| `cad_read_pmi` | `{step:Ref,profile:Id}` | `{pmi:Ref,semantics_report:Ref,presentation_report:Ref,unsupported_types:string[]}`; gespeicherte Semantik, Ziele, Einheiten, Ableitung und Polylinien lesen. |
| `cad_write_pmi` | `{base:Ref,pmi:Ref,profile:Id,output_step:string}` | `{candidate:Ref,pmi_report:Ref}`; deklarative PMI mit konkreten Geometrieankern; Originalangaben und Reviewdaten nicht vermischen. |
| `cad_read_review` | `{step:Ref,schemas:string[]}` | `{ui:Ref\|null,register:Ref\|null,markers:Ref\|null,report:Ref}`; bekannte Anwendungsschemata lesen, fehlende/ungültige Extension melden. |
| `cad_write_review` | `{base:Ref,register:Ref,markers:Ref,ui?:Ref,output_step:string}` | `{candidate:Ref,review_report:Ref}`; Standardcontainer mit Anwendungsschema; Ziele prüfen; unresolved anchor darf keine erfundene Position erhalten. |
| `cad_validate_model` | `{subject:Ref,expected?:Ref,policy:Ref,checks:('geometry'\|'construction'\|'relations'\|'pmi'\|'review'\|'replay'\|'edit_roundtrip')[]}` | `{validation_report:Ref,claims:object,missing_evidence:Error[]}`; benötigte unabhängige Workerläufe tatsächlich ausführen und jede Prüfgruppe gesondert bewerten. |
| `cad_capture_review` | `{subject:Ref,views:{id:Id,orientation:object,visible_groups:Id[],width:number,height:number}[],renderer:Id}` | `{images:Ref[],capture_report:Ref}`; tatsächliche Geometrie/PMI/Marker rendern, Rendererfähigkeit separat; unbekannte Gruppen/unsichtbare Pflichtmarker ablehnen. |
| `cad_artifact_manifest` | `{artifacts:Ref[],reports:Ref[],contract?:Ref,previous_master?:Ref,publish:boolean}` | `{manifest:Ref,resume:Ref,current_master:Ref\|null}`; Hashes und Gates prüfen, reine Manifestierung ohne Publish erlaubt. `publish:true` ersetzt Master nur bei erfüllten Anforderungen. |
| `cad_job_status` | `{job_id:Id}` ohne Modell-Envelope | `{job:Job}`; read-only, persistent, keine GUI-Abhängigkeit. |
| `cad_job_result` | `{job_id:Id}` ohne Modell-Envelope | `Result<T>` oder strukturierter `JOB_NOT_FINISHED`; keine stillen Wiederholungen. |
| `cad_cancel_job` | `{job_id:Id,reason:string}` ohne Modell-Envelope | `{job:Job,cancel_requested:boolean}`; nur eigenen Job abbrechen, Teiloutputs quarantänisieren. |

Die spätere Implementierung muss die generischen `value`-/`orientation`-/`claims`-Objekte in diesem Entwurf durch geschlossene Unionschemata konkretisieren. Der editierbare UI-Vertrag bezeichnet stabile Feature-/Parameter-IDs und zulässige Werte; Anzeigeetiketten sind keine API-IDs. Eine Änderung mit nicht erneuerbaren PMI/Reviewankern liefert einen prüfbaren Kandidaten und `STALE_PMI`/`STALE_REVIEW`, keinen vollständig geprüften Master.

## 8. Fehlervertrag

Jeder Fehler enthält stabilen Code, menschenlesbaren Befund, JSON Pointer/Feature-ID soweit bekannt, Nachweis und Retrybarkeit. Teilberichte bleiben lesbar. `unsupported` und `not_tested` nicht mit Erfolg zusammenfassen.

| Codes | Bedeutung / Reaktion |
|---|---|
| `SOURCE_NOT_ALLOWED`, `PATH_OUTSIDE_ALLOWLIST`, `SOURCE_HASH_MISMATCH`, `INPUT_CHANGED` | Quelle/Pfad/Bytes nicht freigegeben; vor Mutation abbrechen. |
| `SCHEMA_INVALID`, `UNRESOLVED_VALUE`, `DAG_CYCLE`, `DUPLICATE_ID`, `RELATION_UNSUPPORTED`, `UNIT_UNSUPPORTED` | Vertrags- oder Relationsfehler; gezielten Befund liefern. |
| `CAPABILITY_UNVERIFIED`, `UNSUPPORTED_OPERATION`, `UNSUPPORTED_PMI`, `MISSING_MARKER_TRANSPORT`, `ADAPTER_VERSION_MISMATCH` | Geforderte Fähigkeit fehlt; keine Ersatz-BREP-Erfolgsmeldung. |
| `AMBIGUOUS_ANCHOR`, `ANCHOR_NOT_FOUND`, `INVALID_SHAPE`, `RECOMPUTE_FAILED`, `GEOMETRY_MISMATCH`, `GRAPH_MISMATCH` | Konstruktion/Topologie/Geometrieprüfung fehlgeschlagen. |
| `STALE_PMI`, `STALE_REVIEW`, `PRESENTATION_MISSING`, `REVIEW_MARKER_INVISIBLE` | Fachliche Angabe, Bezug oder sichtbare Darstellung nicht nachgewiesen. |
| `STEP_PARSE_ERROR`, `STEP_REFERENCE_MISSING`, `STEP_PROFILE_UNSUPPORTED`, `PROPERTY_SCHEMA_UNKNOWN`, `LIMIT_EXCEEDED` | Parser-/Schema-/Ressourcengrenze; keine stillen weggelassenen Daten. |
| `WORKER_NOT_FOUND`, `WORKER_CRASHED`, `WORKER_TIMEOUT`, `GUI_UNAVAILABLE`, `RESULT_SENTINEL_MISSING`, `OUTPUT_HASH_MISMATCH` | Ausführungsfehler; Status/Prozessende prüfen, Teiloutputs nicht veröffentlichen. |
| `IDEMPOTENCY_CONFLICT`, `JOB_NOT_FOUND`, `JOB_NOT_FINISHED`, `JOB_LOST`, `OUTPUT_CONFLICT`, `VALIDATION_GATE_FAILED` | Lebenszyklus/Publikation nicht erfüllt; vorhandenen Master erhalten. |

## 9. Implementierungsfolge und notwendige Tests

1. **Bestand versionieren:** Inline-Bausteine nach Funktion ordnen; unveränderliche Code-/Toolchainhashes, Lizenz-/Installationsabhängigkeiten, unterstützte Profile und historische Nachweise erfassen. Keine Fallkonstanten in generische Defaults übernehmen. Zu diesem Zeitpunkt noch keine neue Interoperabilitätszusage.
2. **Datenvertrag schließen:** JSON Schemas für Request/Result, Modell, Beziehungen, Quellen, UI, Register, Marker, Policy und Capture schreiben; Grenzwerte, Hashkanonisierung, stabile IDs und Fehlercodes festlegen. Reine Validatoren zuerst.
3. **Worker betreiben:** Einen tatsächlich GUI-unabhängigen MCP-Worker mit Jobjournal, Dateigrenze, stdin-Protokoll, Limits, Abbruch und atomarer Artefaktregistrierung implementieren. Bestehende GUI-Anzeige optional separater Dienst. Kein Modellcode aus JSON ausführen.
4. **Schmale Adapter kapseln:** Zuerst geprüfte primitive/boolesche/konstante Fillet-Familie plus STEP-only-Aufbau. API-Richtungen separat freischalten. Danach nominale PMI, Darstellung und benannte Review/UI-Extensions. Relationsübertragung und automatische Neuverankerung erst nach eigenen Tests als Capability anbieten.
5. **Unabhängige Validierung anschließen:** End-BREP-Leser, P21-Struktur-/Zielprüfung, zwei frische Wiederholungen, Edit-/Rückexport und tatsächliche Ansicht. Prüfer darf fehlende Quelldaten nicht an den STEP-only-Builder nachreichen.
6. **Fachlichen CAD-Dienst ausliefern:** Granulare Tools, maschinenlesbare Capabilities, Beispiele ohne Fallwerte und vollständiges Handoff. Andere CAD-Systeme jeweils als neue Adapter mit eigenen Nachweisen behandeln. Dieser weiterführende `cad_*`-Dienst ist nicht der bereits implementierte `drawing2cad-mcp`-Proxy.

| Testgruppe | Mindestens notwendige Fälle und Erfolgskriterium |
|---|---|
| Tool-/Hostgate | Programme fehlen, ABI/Version weicht ab, GUI läuft nicht: Worker bleibt echt headless; unterstützte Profile/Fehler stimmen. Kein als verfügbar beworbener, defekter Headlesspfad. |
| Keine Skriptdateien | Dateisystembeobachtung von Workerstart bis Ende: keine `.py`/Makro-/Shell-Dateien, nur deklarierte Artefakte; stdin enthält vollständigen Code. |
| Ausführung | Exception bei Exitcode 0, fehlender/falscher/doppelter Sentinel, Kernelcrash, Timeout, Queueüberlauf, oversized stdout: kein falscher Erfolg, begrenzte Logs, Kindprozess endet. |
| Zugriff | Traversal, Junction/Symlink, UNC, Groß-/Kleinschreibung, Eingabetausch nach Hashprüfung, erlaubter Root mit unerlaubter Datei, Pfad in JSON-Text: Ablehnung ohne Zugriff/Masteränderung. |
| Idempotenz/Jobs | Retry während laufendem Job, gleiche ID/anderer Inhalt, Serverneustart, Clientabbruch, Lost Job, parallele Schreibversuche: höchstens ein Publish, Status rekonstruierbar. |
| Vertrag | Fehlende/duplizierte IDs, Zyklen, NaN/Inf, Einheitenkonflikt, ungelöster Pflichtwert, nicht freigegebene Quelle, nicht unterstützte Relation/Operation: präziser Fehler vor Build. |
| Native Konstruktion | Jede erlaubte Primitive/Orientierung/Boolesche und konstante Fillet einzeln; Grenzradien, leere/mehrdeutige Kanten, unverbundene Operation: native Typen/Parameter korrekt, ungültige Inputs abgelehnt. |
| STEP-only | Worker erhält nur STEP; DAG/Operanden/Einheiten/Parameter erhalten; ein Produktroot, gültiger erwarteter Solid, unabhängiger BREP-Vergleich unter fixierter Toleranz. Fehlende Graphdaten nicht durch Endkörper ersetzen. |
| Reproduzierbarkeit | Zweimal frischer Vertragsbuild und frischer STEP-only-Import; semantische Graph-/Parameter-/PMI-/Markerwerte und Geometrie vergleichen. Keine Forderung nach identischen STEP-Bytes. |
| Edit/Rückexport | Unterstützten Parameter und Fillet ändern, Rückexport, weiterer frischer Import; beabsichtigte Änderung/Folgewirkung nachgewiesen. Relationen gesondert testen, gleiche Nominalzahlen reichen nicht. |
| PMI | Wert/Einheit/Quelle/Geometrieziel/Ableitung/Präsentation prüfen; Winkelgrad/Radiant, fehlender Callout, Duplikat, falsche Assoziation, unsupported Datum/Toleranz, Textnote als falscher Durchmesser. |
| Review/UI | Eigenschaftsduplikat, unbekanntes Schema, >2-MiB-Payload, doppelte JSON-Schlüssel, verlorene/vertauschte/falsch nummerierte Chunks, falscher Produkt-/Einheitenkontext, Code-ähnlicher Text, ungültiger Featureanker, ungelöster Ort; ursprüngliche PMI unverändert; sichtbare Marker aus STEP wiedergewonnen und nach Änderung neu geprüft. |
| UI-Parameter/Skizzen | Vollständige native Constraint-Prüfung der unterstützten Rechteckprofile, Wertegleichheit zwischen STEP und Tabelle, Alias-/Zielvalidierung, Änderung über Tabellenzelle mit anschließender Geometrieprüfung und Restore. Unabhängige Zeilen nicht fälschlich als gemeinsame Parameterrelation ausgeben. |
| Anzeige | Tatsächliche Screenshots aller geforderten Ebenen, Körper sichtbar, Text lesbar, Original-PMI und Review getrennt; gespeicherte Polylinien bei fehlender/anderer Schrift identisch wiedergeben. |
| Publikation | Fehlendes Gate, geänderter Artefakthash, Abbruch beim Schreiben: alter Master bleibt; Kandidat klar bezeichnet; Manifest/Resume decken alle tatsächlichen Outputs und offenen Ansprüche ab. |
| Fremder Adapter | Eigene positive/negative Import-/Export-/Edit-/PMI-/Marker-Tests; Erkennung von Standardcontainern allein gilt nicht als semantische oder parametrische Unterstützung. |

Dieser weiterführende fachliche CAD-Dienst würde Quell-/Vertragsprüfung, isolierte Ausführung, den belegten Operationsadapter, STEP-only-Rekonstruktion, unabhängige Prüfung und ein persistentes Artefakt-/Jobprotokoll kapseln. Der vorhandene PDF-/FreeCAD-Proxy übernimmt diese Aufgaben nicht automatisch. Fehlende Relations- und PMI-Automatik bleiben explizite Capability-Lücken, bis ihre Tests bestanden sind.
