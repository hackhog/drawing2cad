---
name: freecad-ap242
description: Rekonstruiere CAD-Modelle aus freigegebenen technischen Zeichnungen über drawing2cad-mcp mit PDF-Aufbereitung und FreeCAD-Proxy, dokumentiere Belege und Unsicherheiten und prüfe STEP AP242 als reproduzierbares Hauptmodell mit editierbaren Operationen und PMI. Auch für STEP-only-Wiederaufbau, Änderungen und Adapterprüfung im nachgewiesenen Funktionsumfang.
metadata:
  version: "0.4.0"
---

# FreeCAD – reproduzierbares AP242-Hauptmodell

Arbeite mit expliziten Eingaben, einem eingefrorenen deklarativen Modellvertrag und messbaren Ausgaben. Jedes geeignete LLM kann die Phasen übernehmen, ohne frühere Chatnachrichten oder Python-Variablen zu kennen. Der ausführende CAD-Adapter bleibt werkzeugabhängig und muss seine Fähigkeiten nachweisen. Modellunabhängiger Ablauf bedeutet weder universelle CAD-Unterstützung noch identische Zeichnungsinterpretation durch verschiedene LLMs.

Verwende `drawing2cad-mcp` als gemeinsame Schnittstelle für PDF-Aufbereitung und die weitergeleiteten FreeCAD-Werkzeuge. Prüfe den tatsächlich angebotenen Toolkatalog und `drawing2cad_status` vor dem Lauf. CAD-Arbeit bleibt ausschließlich FreeCAD-MCP-Arbeit, über den Proxy als `freecad_<Originalname>`. Vollständiges Inline-Python ist zulässig; keine ad hoc erzeugten Modellskript-, Makro- oder ausführbaren Hilfsdateien anlegen. Der ausdrücklich beauftragte, versionierte Servercode in `drawing2cad-mcp` ist davon getrennt. Deklarative JSON-Prüfdaten, CAD-Dateien und Vorschaubilder sind zulässig. Bei reiner Skill-Pflege keine CAD-Dateien verändern.

## Einstieg und Grenzen

Für jeden Lauf [model-agnostic-workflow.md](references/model-agnostic-workflow.md), die gemeinsame Schnittstelle in [drawing2cad-mcp.md](references/drawing2cad-mcp.md) und das Fähigkeits-/Tool-Gate in [tooling-and-mcp-contract.md](references/tooling-and-mcp-contract.md) lesen. Danach nur die für die Phase benötigten Referenzen laden:

| Aufgabe | Referenz |
|---|---|
| PDF lesen, Seite rendern, Detailausschnitt anfertigen und FreeCAD-Tools aufrufen | [drawing2cad-mcp.md](references/drawing2cad-mcp.md) |
| Quellen, Konstruktion, Beziehungen, Unsicherheiten oder Handoff definieren | [model-contract.md](references/model-contract.md) |
| Prozessführung, STEP-Repräsentationen und bekannte Binding-Grenzen | [execution-and-ap242.md](references/execution-and-ap242.md) |
| CSG und nominale PMI aus STEP lesen | [inline-readers.md](references/inline-readers.md) |
| Prozeduralen Graph mit konstanten Verrundungen exportieren/importieren | [inline-procedural-adapter.md](references/inline-procedural-adapter.md), [edge-blends-and-thread-pmi.md](references/edge-blends-and-thread-pmi.md) |
| Metrische Regelgewinde und typische Fasen nachschlagen | [metric-thread-chamfers.md](references/metric-thread-chamfers.md); vollständige 35-Zeilen-Tabelle des Benutzerlinks von M1 bis M68 |
| Semantische Text-Eigenschaften und native PMI-Anzeige lesen | [inline-property-pmi-reader.md](references/inline-property-pmi-reader.md) |
| Lokale UI-Zuordnungen und Reviewdaten getrennt von Original-PMI übertragen | [inline-review-envelope.md](references/inline-review-envelope.md); konkreten Prüfstatus des Profils beachten |
| Native Parametertabelle und vollständig bestimmte Rechteckprofile rekonstruieren | [inline-editable-ui-adapter.md](references/inline-editable-ui-adapter.md); Maße stammen aus STEP, Bedienzuordnung aus der UI-Property |
| Operationen als lineare Liste im nativen Modellbaum darstellen | [inline-linear-history-view.md](references/inline-linear-history-view.md); Originaloperationen gruppieren, ihre Abhängigkeiten erhalten |
| Lokale Reviewmarkierungen aus eingebetteten Daten darstellen | [inline-review-markers.md](references/inline-review-markers.md); eindeutige Geometrieanker und separate Reviewansichten prüfen |
| Wiederaufbau, Änderung, PMI, Marker und Veröffentlichung prüfen | [validation.md](references/validation.md) |

Der allgemeine Vertragswortschatz umfasst primitive Körper, planare Profile/Extrusionen, boolesche Operationen und konstante Kantenverrundungen. Das ist keine pauschale Implementierungszusage. Die dokumentierte prozedurale Adapterfamilie ist enger: achsparallele Rechteckextrusionen, volle Kreisextrusionen entlang +Z/+X, verfeinerte boolesche Operationen, konstante Verrundungen mit eindeutigen Topologieankern und Millimeter. Ältere CSG-Leser haben andere Teilumfänge. Für das konkrete Bauteil Operation, Einheit, Orientierung, Beziehung, PMI-Typ und beide benötigten Adapterrichtungen einzeln prüfen. Nicht unterstützte Konstruktion nie durch einen Endkörper ersetzen und dennoch als editierbar bezeichnen.

Ein rekonstruierter nativer Operationsbaum belegt eine nachvollziehbare Konstruktion. Er beweist nicht die unbekannte ursprüngliche Entwurfsabsicht, originale Skizzenzwänge oder historische Benutzeraktionen. Gleiche Zahlenwerte sind keine erhaltenen Parameterbeziehungen. Standard-STEP-Import eines BREP und Wiederaufbau durch den geprüften Spezialadapter sind getrennte Leistungen.

## Modus und Ablauf

1. **Eingaben fixieren.** Modus `new_drawing`, `replay_contract`, `import_step` oder `edit_model`, exakt erlaubte Quellen mit Hash/Seiten, Zielartefakte und erforderliche Nachweise erfassen. Referenzfälle sind keine zusätzlichen Konstruktionsquellen. Bereits getroffene Nutzerentscheidungen übernehmen.
2. **Fähigkeiten prüfen.** `drawing2cad_status`, aktuellen Toolkatalog, Werkzeugversionen und Adapterprofile erfassen; benötigte Funktionen gegen nachgewiesene Funktionen abgleichen. Ein erreichbarer Proxy belegt weder einen erreichbaren FreeCAD-Kernel noch Headless-Fähigkeit. Ein fehlender Nachweis ist kein Erfolg. Kleine isolierte Proben über MCP durchführen, wenn sie eine konkrete Lücke klären können.
3. **Belege und Register erstellen.** Bei PDF-Quellen `pdf_info → pdf_read_text → pdf_render_page → pdf_crop_region` verwenden; nur benötigte Seiten/Ausschnitte abrufen und die zurückgegebenen Quellhashes vergleichen. Bilder tatsächlich ansehen: Textausgabe enthält keine OCR und ersetzt keine visuelle Zeichnungsinterpretation. Originalangaben, deterministische Ableitungen, Annahmen und ungeklärte Angaben trennen. Jeder unklare Ort und jeder abgeleitete/angenommene Wert erhält Quelle, Status, Ziel-/Geometrieanker und einen sichtbaren Review-Marker separat von Original-PMI. Ein ungelöster Ort darf nicht durch eine erfundene Position verdeckt werden.
4. **Vertrag einfrieren.** Parameter, Einheiten, Koordinatensystem, Relationsgraph, Operations-DAG, PMI, Marker, Prüfpolitik und Adapterumfang versionieren und hashen. Blockierende Lücken gezielt klären; unabhängige Arbeit fortsetzen. Ein autorisierter Annahmewert bleibt eine Annahme. Für Layoutarbeit eine neue Vertragsrevision erzeugen, niemals einen eingefrorenen Vertrag still ändern.
5. **Frisch aufbauen.** Vollständige Eingaben und Inline-Abhängigkeiten laden, isolierten Lauf verwenden, logische IDs stabil halten und explizite Abhängigkeiten topologisch auswerten. Zwischenstände und Endkörper prüfen. Keine aktive Auswahl, vorhandenen Dokumente oder Sessionvariablen voraussetzen.
6. **AP242-Kandidat erzeugen.** Auswertbaren konstruktiven Graph, End-BREP, erforderliche Semantik/Präsentation und unterstützte Review-Daten exportieren. JSON-Text oder benannte Zwischenkörper allein erfüllen den Konstruktionsvertrag nicht. Die letzte gültige Masterdatei erhalten.
7. **STEP-only frisch rekonstruieren.** Nur der Kandidat liefert Modellinhalt. Werkzeuge und Prüfpolitik sind zulässig; Quellvertrag, FCStd, Zeichnung und frühere Variablen dürfen fehlende STEP-Daten nicht ergänzen. Danach gegen unabhängige Sollwerte prüfen. Für Vertragswiederholung zusätzlich aus demselben eingefrorenen Vertrag frisch aufbauen.
8. **Änderung und Rückexport prüfen.** Falls beauftragt, `AP242 → native Operationen → Änderung → AP242 → frischer Import` durchführen. Geometrie/Konstruktion, Relationsübertragung, Original-PMI und Review-Marker getrennt bewerten. Nach einer Änderung betroffene Angaben zunächst als ungeprüft markieren.
9. **Review und Übergabe.** Nur bei bestandenen auftragsrelevanten Prüfungen als Master veröffentlichen. Kandidatenstatus, Register, Berichte, Hashes, aktive Grenzen und Resume-Paket beilegen. Sichtbarkeit durch tatsächliche Anzeige prüfen. Temporärdateien ausschließlich anhand der Artefaktliste des eigenen Laufs aufräumen.

## Reproduzierbarkeit und Nachweisgrenzen

Freie Zeichnungsinterpretation und konstruktive Strategiewahl sind nicht deterministisch. Reproduzierbar ist der geprüfte Aufbau aus identischen Vertragsdaten mit dokumentierter Werkzeugkette. Vergleiche DAG, Parameter, erhaltene Beziehungen, PMI, Marker und Geometrie unter vorher festgelegten Toleranzen; keine identischen STEP-Bytes versprechen. Zeitstempel, Entity-Nummern und Serialisierung können abweichen.

Der Skill dokumentiert den Ablauf und getestete Bausteine. Er installiert keinen universellen Import-/Exportdienst. Ein anderes CAD-System benötigt einen eigenen geprüften Adapter. Vollständige EXPRESS-Konformität, beliebige GD&T-/Toleranzsysteme, vollständige Relationsübertragung und automatische PMI-/Marker-Aktualisierung sind ohne gesonderten Nachweis nicht zugesichert.

## Isolierte Regressionen

Diese Dateien nur für die identische freigegebene Zeichnung oder einen ausdrücklich beauftragten Regressionstest laden. Zahlen, Pfade, Objekt-/Flächennamen, PMI-Anzahl und Layout sind keine Standardwerte:

- [befestigung-baseline.json](references/befestigung-baseline.json): fixierter Befestigung-Fall; die dortige Rippenannahme und Änderungstestgeometrie gelten nur dort. Der dokumentierte Ausgangsstand belegt keinen Autorierungs-Rückexport.
- [maschinenteil-baseline.json](references/maschinenteil-baseline.json) und [inline-maschinenteil-pmi.md](references/inline-maschinenteil-pmi.md): fixierter Maschinenteil-Fall samt vollständigen Präsentationspolylinien. Diese programmatisch lesen, nicht aus Schriftarten neu schätzen. Bestätigte Annahmen zu Dicke, Querbohrungen und vereinfachtem Gewinde gelten nur hier.
- [maschinenteil-review-baseline.json](references/maschinenteil-review-baseline.json): Revision 07 desselben Falls mit rekonstruierter Skizzen-/Extrusionsbedienung und lokalen Reviewmarkierungen. Bewusstes Legacy-Profil `model-contract/1` plus explizite UI-/Review-Erweiterungen; keine behauptete Migration auf das allgemeine Schema 2. Die eingebetteten Codehashes und Fähigkeiten gelten für diesen geprüften Adapterstand.
- Die Maschinenteil-Probe in [inline-procedural-adapter.md](references/inline-procedural-adapter.md) belegt einen konstruktiven/geometrischen Änderungskreislauf ihres Teilumfangs. Sie belegt keine automatische PMI-Aktualisierung und keine allgemeine Review-Marker-Rückstrecke.

Beim Abschluss Master oder klar bezeichneten Kandidaten, Vertrag, Prüfbericht und bei Bedarf abgeleitete Arbeitsdatei verlinken. Tatsächlich bestandene Prüfungen, verbleibende Annahmen, fehlende Funktionen und nächster ausführbarer Schritt müssen ohne Chatverlauf verständlich sein.
