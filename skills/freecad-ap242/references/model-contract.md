# Modellvertrag, Schema 2

Der Vertrag enthält deklarative Daten, keinen ausführbaren Code. Er trennt Quelleninterpretation, Konstruktion, Review und Nachweise. Schema 2 erweitert den bisherigen Vertrag um explizite Fähigkeiten, ein vollständiges Review-Register und Handoff-Anforderungen. Die vorhandenen Fallfixtures werden dadurch nicht automatisch migriert oder neu zertifiziert. Bei Altdaten `source_schema_version`, Feldzuordnung und fehlende Informationen protokollieren; unbewiesene neue Prüfgruppen bleiben `not_tested`.

## Pflichtfelder

| Feld | Inhalt / Invariante |
|---|---|
| `contract_version`, `model_id`, `revision`, `parent_revision` | Schema und Modellrevision. Inhaltliche Änderungen erzeugen eine neue Revision. |
| `sources[]` | Stabile ID, erlaubter Pfad/URI, SHA-256, Seiten, Zeichnungsstand und Rolle. Ein Hash ersetzt keinen zugänglichen Inhalt. |
| `toolchain`, `capability_profile` | MCP/Addon, FreeCAD, OCCT, Python, PythonOCC, Adapterkennung/-version/Codehash, konkrete Funktionen und geprüfte Grenzen. |
| `units`, `frame` | Längen-/Winkeleinheit, Ursprung, orthonormale rechtshändige Achsen, Bezug zur Zeichnung und Herkunft jeder Koordinatenentscheidung. Keine impliziten GUI-Einheiten. |
| `evidence[]` | ID, Quelle/Hash/Seite, Ansicht/Detail, Text und/oder visuell beobachteter Befund, reproduzierbar lokalisierbare Region mit Koordinatenkonvention, Interpretationsstatus. |
| `parameters[]` | ID, Datentyp, Wert oder `null`, Einheit, Beleg-IDs und Herkunft `explicit`, `derived`, `inferred`, `unresolved`. Werte und Positionen gleich behandeln. |
| `relations[]` | ID, deklarativer Operator/Constraint, Eingabe-/Ausgabe-IDs, Einheiten, Belege und tatsächlicher Erhaltungsumfang. Leere Liste verspricht keine Formeln/Constraints. |
| `operations[]`, `root` | Stabile IDs, Typ, Parameter-/Profilreferenzen, Platzierung, Abhängigkeiten und Verfeinerungsregel. Vollständig auflösbarer azyklischer Graph. |
| `pmi[]` | Ausschließlich ursprüngliche Zeichnungsangaben: `source_id`, semantischer Typ/Wert/Einheit, Quellenbelege, Ziele, Ableitungsbezüge und Präsentation. |
| `review_register[]`, `review_markers[]` | Jede abgeleitete, angenommene oder ungelöste Angabe/Position sowie Konflikte mit Herkunft, Status, betroffenen IDs, Anker und eigenem sichtbaren Marker. |
| `validation_policy`, `required_claims[]` | Vorab festgelegte numerische Toleranzen, Körperzahl, Graph-/PMI-/Markerprüfung, relevanter Änderungstest und erforderliche Nachweisrichtungen. |
| `claims` | Getrennte tatsächliche Prüfstatus aus [validation.md](validation.md), keine Zusammenfassung bloß zugesicherter Fähigkeiten. |
| `canonicalization_profile`, `contract_sha256` | Dokumentiertes Hashverfahren und Hash des definierten Modellinhalts ohne Selbstbezug. Laufdaten/Hashfelder gesondert behandeln. |

Ein `evidence`-Eintrag unterscheidet lesbaren Originaltext und Interpretation. OCR-Text oder ein aus dem Bild gemessenes Verhältnis sind keine explizite Bemaßung. Für abgeleitete Angaben die gesamte Beleg-/Relationskette erhalten. Nicht lesbare Zeichen als ungelöst kennzeichnen. Mehrere widersprechende Zeichnungsansichten nicht durch Mittelwertbildung verschmelzen.

## Vollständiges Review-Register

Für **jeden** `derived`, `inferred` oder `unresolved` Parameter, für unsichere Positionen, Zuordnungen und vereinfachte Geometrien einen Registereintrag anlegen. Ein Eintrag darf mehrere Werte abdecken, wenn Herkunft, Entscheidung und Anker gleich sind; seine `affected_ids` müssen sämtliche betroffenen Werte ausdrücklich aufführen. Auch ein rechnerisch korrekt abgeleiteter Wert bleibt als Ableitung gekennzeichnet.

| Registerfeld | Bedeutung |
|---|---|
| `review_id`, `kind` | Stabile ID; `derived`, `assumed`, `unresolved` oder `conflict`. |
| `affected_ids[]` | Alle betroffenen Parameter, Beziehungen, Operationen, Positionen, Selektoren oder PMI-Zuordnungen. |
| `value`, `unit`, `alternatives` | Eingesetzter Wert oder `null`; Alternativen falls relevant. Keine Zahl für eine ungelöste Pflichtangabe erfinden. |
| `source_refs[]`, `derivation_ref`, `rationale` | Quellen-/Beleg-IDs, gegebenenfalls exakte Berechnung und Begründung. Bei nicht vorhandener Zeichnungsangabe die geprüften Ansichten und das Fehlen dokumentieren. |
| `decision_status` | `open`, `accepted`, `rejected`, `superseded`; `accepted` mit Akteur, Entscheidungsbeleg und Umfang. LLM-Auswahl nicht als Nutzerfreigabe ausgeben. |
| `verification_status` | `not_tested`, `pass`, `fail`, `stale`; unabhängig von der Entscheidung. Bestätigung beweist keine geometrische Korrektheit. |
| `blocking` | Welche konkreten Phasen/Aussagen ohne Lösung nicht erfüllt sind und weshalb. |
| `anchor` | Logische Konstruktions-ID, geometrischer Selektor/Fingerprint, Quellenregion; Auflösestatus `resolved`, `ambiguous`, `unresolved` und erwartete Zielanzahl. |
| `marker_id`, `revision`, `history` | Eigener sichtbarer Review-Marker und nachvollziehbare Änderungen. |

`accepted` macht aus einer Annahme keine originale Zeichnungsangabe. Aufgelöste Punkte dürfen historisch nachvollziehbar bleiben. Bei Quellenkorrektur den alten Eintrag als ersetzt markieren und die neue Belegkette anlegen. Nicht mehr gültige Annahmen nicht still aus dem Register löschen.

Ein ungelöster geometrischer Ort erhält eine Quellenregion und das beabsichtigte logische Ziel; sein Geometrieanker bleibt ausdrücklich ungelöst. Vorhandene eindeutige Bezugsgeometrie darf als Bezug, nicht als behaupteter tatsächlicher Zielort dienen. Im Review eine sichtbare Notiz mit ID und „Ort ungeklärt“ anzeigen. Ohne zulässigen Zielwert den davon abhängigen Aufbau blockieren. Ein frei erfundener Pfeil auf dem Körper ist keine Lösung.

## Sichtbare Review-Marker separat von Original-PMI

Jeder Registereintrag referenziert einen Marker mit `marker_id`, `review_id`, lesbarem Text einschließlich Herkunft/Status, Zielanker, Anzeigemodus, Ansicht/Annotationsebene, Position/Leader und Sichtbarkeitsstatus. Sinnvolle Präfixe sind „ABGELEITET“, „ANNAHME“ und „UNGEKLÄRT“. Status nicht allein durch Farbe kodieren. Registergruppen und Original-PMI separat schaltbar halten; vor der Reviewübergabe die Markierungen sichtbar anzeigen.

Für aufgelöste Geometrie Marker an tatsächlicher Zielgeometrie/Feature-ID verankern. Bei ungelöstem Ort eine sichtbare Review-Liste oder Quellenansicht mit dem ungeklärten Bezug verwenden; `placement_status=unresolved` dokumentieren. Nach einem CAD-Aufbau den Marker an die neu aufgelösten Ziele binden und die Quellenregion beibehalten. Markertexte, Anker und Sichtbarkeit werden mit der Revision eingefroren.

Review-Marker sind keine originalen Maßangaben, Fertigungstoleranzen oder standardisierten semantischen PMI. Eigene `review_id`/`marker_id` und gegebenenfalls `metadata_id` benutzen; keine `source_id` der Zeichnungs-PMI dafür wiederverwenden. Original-PMI, reviewbezogene Metadaten und deren Grafiken getrennt zählen und prüfen.

Für selbsttragende STEP-Übergabe muss der ausgewählte Adapter Register und Marker nachweislich speichern und STEP-only wiederherstellen können. Der lokale namespaced Container in [inline-review-envelope.md](inline-review-envelope.md) beschreibt hierfür ein eigenes Adapterprofil: `drawing2cad.review_annotations.v1` mit Schema `drawing2cad.review-annotations/1`. Es ist nicht mit universeller AP242-PMI-Unterstützung gleichzusetzen. Ein gespeicherter JSON-Property-Text allein beweist weder sichtbare Marker noch verknüpfte Ziele. Fehlt dieser Teil des Adapters, Status und Einschränkung ausweisen; das externe Register allein erfüllt nicht das geforderte STEP-only-Versprechen.

## Operations-DAG und Beziehungen

Zuerst Referenzen, Einheiten und Zyklen prüfen; anschließend topologisch mit stabiler ID-Reihenfolge bei unabhängigen Knoten sortieren. Die Differenz hat geordnete Operanden. Boolesche Gruppierung und Verfeinerungsregel nicht eigenmächtig ändern: Geometrie, Topologie und Flächenzuordnung können sich ändern.

Der deklarative Wortschatz ist von der nachgewiesenen Adapterunterstützung zu trennen:

- `cylinder`: Radius, Höhe und Platzierung; Segmente nur mit nachgewiesener Darstellung.
- `box`: drei positive Längen und Platzierung.
- `polygon_profile`: geordnete, geschlossene, planare Punkte ohne Selbstüberschneidung.
- `extrusion`: Profilreferenz, normierte Richtung, positive Tiefe, Volumenmodus.
- `union`, `difference`, `intersection`: Operandreferenzen und explizite Verfeinerungsregel.
- `fillet`: konstruktive Basis, konstanter positiver Radius, eindeutige Kantenselektoren sowie exportierte Topologieanker. [edge-blends-and-thread-pmi.md](edge-blends-and-thread-pmi.md) beachten.

Andere Operationen und die tatsächlich unterstützten Orientierungen/Einheiten am Fähigkeitsgate prüfen. Eine zulässige JSON-Beschreibung ist keine implementierte CAD-Operation.

Alle Berechnungen aus deklarativen Beziehungen über einen eingeschränkten Operatorbaum mit expliziten Einheiten und Parameterreferenzen ausführen, etwa `add`, `sub`, `mul`, `div`, `sqrt` und ausdrücklich unterstützte trigonometrische Funktionen. Kein `eval` auf Dokument-, Vertrags- oder STEP-Inhalt. Abhängigkeiten müssen im nativen Modell tatsächlich verknüpft sein, wenn ihre Editierbarkeit versprochen wird.

Pro Beziehung den Erhaltungsumfang festhalten: `contract_only`, `native_linked`, `neutral_encoded`, `fresh_reconstructed`, jeweils mit Nachweis. `neutral_encoded` ist kein Ersatz für `fresh_reconstructed`. Gemeinsame Zahlenwerte, viele Spreadsheet-Zellen oder vollständig bestimmte primitive Skizzen beweisen keine gemeinsamen Familienparameter, Positionsbeziehungen oder ursprüngliche Entwurfsabsicht. Wenn eine Radiusänderung Tangentenpunkte verändern soll, ist dieser Zusammenhang im Vertrag, nativen Modell und vereinbarten Neutralformat jeweils erforderlich. Andernfalls nur die tatsächlich erhaltenen unabhängigen Parameter zusichern.

Das Profil [inline-review-envelope.md](inline-review-envelope.md) kann mit `drawing2cad.editable_ui.v1` (Schema `drawing2cad.editable-ui/1`) native UI-Zuordnungen, Labels und Darstellungsstrategien ergänzen. Konstruktion und Konstruktionswerte müssen weiterhin aus den auswertbaren STEP-Operationen kommen; UI-Metadaten dürfen keine fehlenden Operationen ersetzen oder abweichende Werte verdecken.

## Geometrische Selektoren und Original-PMI

`Face17` oder `Edge3` ist nur ein Laufzeitresultat. Ziele über konstruktive Herkunft und geometrische Eigenschaften beschreiben: Zylinder mit Achse, Mittelpunkt, Radius, axialem Bereich; Ebene mit Normale, Lage und Begrenzung; Kante mit Kurventyp, Länge, Endpunkten und Abstand zur Referenzkurve. Symmetrie oder ähnliche Flächen können diese Merkmale mehrdeutig machen; dann zusätzliche Herkunft oder topologische Nachbarschaft nutzen. Bei mehreren Bohrungen die vollständige geordnete Zielmenge angeben.

Jeder Selektor muss genau die erwartete Zahl von Zielen treffen. Null oder mehrere unbeabsichtigte Treffer sind Fehler. Nach Booleschen Operationen, Verrundungen, frischem Aufbau und Änderungen neu auflösen. Historische Flächennummern eines Fallfixtures nur nach vollständigem Fingerprint-Abgleich verwenden. Beim Export tatsächliche STEP-Referenzen mit logischen IDs und Selektoren verbinden; Entity-IDs gelten nur innerhalb ihrer Datei.

Ein Original-PMI-Datensatz enthält getrennt:

- **Semantik:** Originaltext, Typ, Sollwert/Einheit, ausdrücklich angegebene Toleranz/Datum/GD&T, `source_id` und Belege.
- **Ziele:** Eindeutige Selektoren, erwartete Zielmenge und gegebenenfalls Ableitungsgraph, etwa Verbindung zweier Zylinderachsen.
- **Grafik:** Ansicht, Annotationsebene, Textanker, Maß-/Hilfslinien beziehungsweise Polylinien und Verknüpfung zur zugehörigen Semantik.

Nichtnumerische Angaben wie Gewindebezeichnungen als semantische Eigenschaften mit tatsächlicher Geometriezuordnung behandeln. Ein vereinfachter Zylinder ist kein vollständig parametrisiertes Gewindefeature. Steigung, Toleranzklasse, Werkstoff, Rauheit oder Bezüge ohne Zeichnungsbeleg nicht erfinden. Allgemeine Hinweise benötigen einen nachvollziehbaren Geltungsbereich. Eine Liste der Maßtexte reicht für eine reproduzierbare Präsentation nicht aus. Grafische Linien sind keine Semantik; unsichtbare Semantik ist keine geprüfte Präsentation. Numerische Prüftoleranzen sind keine Fertigungstoleranzen.

## Freeze, Hash und Laufzustand

Das Kanonisierungsprofil benennt UTF-8, Schlüsselreihenfolge, Zahlenkodierung, Unicodebehandlung, Arrayreihenfolge und exakte ein-/ausgeschlossene Felder. Gleiche Implementierung/Version verwenden oder Kanonisierungsäquivalenz prüfen. Endliche Zahlen verlangen. `contract_sha256`, sich ändernde Laufberichte/Claims, Zeitstempel und hostabhängige Ausgabepfade ausschließen; Konstruktion, Einheiten, Belege, Entscheidungen, Beziehungen, PMI-/Marker-Spezifikation und Prüfpolitik einschließen. Nicht pauschal alle Pfade entfernen, wenn damit die Identität einer Quelle verlorengeht: Quellen über stabile IDs und Inhaltshashes festhalten. Zusätzlich die vollständige Vertragsdatei separat hashen.

Änderungen an eingefrorenen Modellinhalten, einschließlich finalem Präsentationslayout und Entscheidungen, erzeugen eine neue Revision mit Elternhash. Bei Wiederholung Vertrag nicht aus dem Gedächtnis nachbauen. Fehlt ein Vertrag für eine existierende STEP-Datei, aus den tatsächlich decodierbaren STEP-Daten einen Importvertrag erstellen und unbekannte Quellen-/Relationsinformationen offen ausweisen.

Laufkennungen, Kandidatenpfade, Fortschritt und temporäre Artefakte in einem separaten Laufmanifest halten. Das Resume-Paket nach [model-agnostic-workflow.md](model-agnostic-workflow.md) nennt Quelle/Vertrag/Toolchain, tatsächliche Ergebnisse, offene Punkte und den nächsten ausführbaren Schritt. Keine ausführbaren Payloads als vermeintliche JSON-Daten verstecken.
