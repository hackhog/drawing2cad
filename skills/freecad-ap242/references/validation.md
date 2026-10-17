# Prüfvertrag und Veröffentlichung

Status je Prüfgruppe: `pass`, `fail`, `not_tested`, `not_applicable`. `not_applicable` benötigt eine Begründung; fehlende Fähigkeiten sind nicht automatisch unzutreffend. `not_tested` ist kein Erfolg. Auftrags- und Modellvertrag legen vorab fest, welche Gruppen vor der Masterveröffentlichung bestehen müssen. Ein neuer Bericht ersetzt keine unverändert gebliebenen alten Nachweise, sondern verweist mit Hash/Version auf sie und trennt sie vom aktuellen Lauf.

## Getrennte Prüfbehauptungen

| Gruppe | Nachweis |
|---|---|
| `source_traceability` | Verwendete Quellen/Seiten/Hashes autorisiert; verwendete Angaben durch Belege oder offen ausgewiesene Ableitung/Annahme gedeckt. |
| `contract_integrity` | Eingefrorene Revision/Hash, gültige Daten, vollständige Referenzen, azyklische Graphen und dokumentierte Entscheidungen. |
| `native_construction` | Tatsächlich native editierbare Operationen, Parameter und Abhängigkeiten im zugesagten Umfang. |
| `brep_equivalence` | Unabhängig gelesener End-BREP geometrisch äquivalent zur Rekonstruktion. |
| `step_structure` | Header/Schema, konkrete Entity-Typen und Referenzen geprüft; keine volle EXPRESS-Zertifizierung impliziert. |
| `step_only_rebuild` | Frischer Aufbau ausschließlich aus dem STEP als Modellquelle. |
| `contract_replay` | Zweiter frischer Aufbau aus demselben eingefrorenen Vertrag äquivalent. |
| `step_replay` | Zweiter frischer STEP-only-Aufbau äquivalent. |
| `editability` | Relevante vorgelagerte Änderung wirkt korrekt bis zum Ergebnis und lässt sich zurücksetzen. |
| `relation_transport` | Jede zugesagte Beziehung wird aus STEP rekonstruiert und reagiert als Beziehung; ausgewertete Zahlen allein reichen nicht. |
| `pmi_semantics`, `pmi_presentation`, `native_pmi_visibility` | Original-PMI vollständig, geometrisch zugeordnet und in den jeweiligen Darstellungen tatsächlich sichtbar. |
| `review_register`, `review_marker_transport`, `native_review_visibility` | Register vollständig; Status/Quellen/Anker/Marker separat erhalten und sichtbar. |
| `authoring_geometry`, `authoring_relations`, `authoring_pmi`, `authoring_review` | Änderung mit Rückexport und erneutem frischen Import für jede Datenfamilie separat belegt. |

Ein zusammenfassender Status `authoring_roundtrip` darf nur `pass` sein, wenn alle dafür verlangten Datenfamilien bestanden sind. Ein erfolgreicher Geometrietest neben `authoring_pmi=not_tested` ist kein vollständiger Rückexport. Standardimport und Spezialadapter separat mit Namen/Version benennen.

## Geometrie und Konstruktion

1. Prüftoleranzen und erwartete Körperzahl vor dem ersten Ergebnis festlegen. Größenordnung, Einheit, Kernel und Vergleichsart begründen. Numerische Toleranzen nicht als Fertigungstoleranzen darstellen oder nach einem Fehlversuch lockern.
2. Vollständigen erreichbaren DAG, Relationen, Parameter, Einheiten und Platzierungen prüfen. Radien/Tiefen positiv, Profile gültig, Richtungen/Koordinatenrahmen konsistent. Nicht nur die Wurzel testen.
3. Native Zwischenobjekte dürfen keinen Fehlerzustand haben; Shape und erwarteter Objekttyp müssen passen. Profile sind keine Volumenkörper. Adapterhilfsobjekte, Spreadsheet und Review-/PMI-Objekte separat zählen. Ein beschrifteter Endkörper ist kein nativer Operationsbaum.
4. End-BREP unabhängig aus demselben STEP lesen. Rekonstruierten Endkörper vergleichen: beide gerichteten booleschen Materialdifferenzen, Topologievalidität, Körperzahl, Bounding Box, relevante Maße und bei Bedarf Schnitte. Volumen und Bounding Box allein genügen nicht. Für offene Flächen/Drähte geeignete Abstandstests festlegen; ein Volumentest ist dort nicht ausreichend.
5. Schema-Header und Entity-Referenzen tatsächlich prüfen. Hilfs-BREP für Topologieanker dürfen keine unerwarteten weiteren Produktkörper erzeugen. Unverstandene Operatoren, fehlende Verweise oder mehrdeutige Selektoren müssen die betroffene Konstruktion ablehnen.

Ein abweichender Einzelwert der Volumenintegration nach STEP-Import ist gesondert von booleschen Materialdifferenzen zu untersuchen. Messmethoden und Differenzen protokollieren, nicht eine Methode nachträglich als austauschbaren Grenzwert verwenden. Eine bekannte Fallabweichung ist kein allgemeiner Freibrief für neue Geometriefehler.

## Original-PMI: Semantik und Anzeige

Für jede erwartete `source_id` genau eine originale Angabe prüfen: richtiger Typ, Text/Wert, Einheit, ausdrücklich geforderte Toleranz/Datum, vollständige Zielmenge und gültiger Ableitungsgraph. Unbekannte PMI-Typen/Toleranzfamilien nicht still ignorieren. Keine Normwerte ergänzen, die nicht aus der Zeichnung stammen. Vollständigkeit gegen ID-Mengen und Eigenschaften prüfen; bloße Anzahl reicht nicht.

Für grafisch geforderte PMI die Kette Grafik → Callout → semantische Dimension/Eigenschaft prüfen. Annotationsebene, Textanker und Polylinien müssen konsistent sein. Bei semantischen Texteigenschaften muss die Verknüpfung auf die tatsächliche `PROPERTY_DEFINITION` zeigen. Callouts brauchen eine gültige Annotationsebene und Draughting-Model-Referenz. Ableitungsgraphen zusätzlich direkt aus STEP prüfen, wenn ein XCAF-Leser sie verkürzt.

Die gespeicherten Ansichten tatsächlich anzeigen und auf Lesbarkeit, fehlende Labels, verdeckte Inhalte, Überlagerungen und abgeschnittene Darstellung kontrollieren. Koplanarität allein reicht nicht: Die Ebene muss aus der vorgesehenen Sicht vor dem verdeckenden Körper liegen. Abgeleitete Lochkreis-/Winkelgeometrie auch grafisch kenntlich machen. Native Anzeige, STEP-Präsentationsverknüpfung und Anzeige in einem fremden Viewer sind getrennte Nachweise. Ein Screenshot belegt nicht automatisch semantische Verknüpfung.

Erst nach Sichtprüfung endgültiges Layout einfrieren; Layoutkorrektur erzeugt eine neue Vertragsrevision und erneute betroffene Prüfungen.

## Register, Annahmen und sichtbare Review-Marker

1. Aus Vertrag und decodierten Daten die Menge aller abgeleiteten, angenommenen, ungelösten und widersprüchlichen Werte/Positionen bestimmen. Jede betroffene ID muss im Register abgedeckt sein; nicht nur „wichtige“ Annahmen aufnehmen.
2. Für jeden Eintrag Herkunft, Beleg/Derivation, Wert/Einheit oder ausdrücklich `null`, Entscheidung und Prüfstatus, betroffene IDs, Anker, Marker-ID und Historie prüfen. `accepted` darf nicht ohne Entscheidungsbeleg entstehen. Bestätigte Annahmen behalten ihre Herkunftsklasse.
3. Eindeutige geometrische Ziele neu auflösen. Bei ungelöstem Ort Quellenregion und beabsichtigtes logisches Ziel sowie sichtbaren Hinweis „Ort ungeklärt“ verlangen; keinen erfundenen konkreten Geometrieanker akzeptieren. Eine offene aufbaurelevante Pflichtangabe blockiert den abhängigen Aufbau/Export.
4. Marker separat von Original-PMI darstellen, mit Herkunft/Status im lesbaren Text. Nicht allein Farbe verwenden. Markergruppen einschalten und jede relevante Ansicht tatsächlich prüfen. Ungeklärte Orte ohne CAD-Ziel müssen in der Review-Liste/Quellenansicht sichtbar bleiben.
5. Im frischen STEP-only-Import IDs, Status, Herkunft, Zielselektoren, Ankerfingerprints und Präsentation vergleichen. Ein externer JSON-Bericht oder ein Property-Text allein beweist keine wiedergewonnene sichtbare Markierung.
6. Nach Änderungen Zielanker neu prüfen; betroffene Register/Marker auf `stale` setzen, bis Neubewertung abgeschlossen ist. Ein unverändert sichtbares altes Label ist kein gültiger Änderungsnachweis.

Das Profil [inline-review-envelope.md](inline-review-envelope.md) verwendet namensgebundene lokale Eigenschaften für Review-/UI-Daten. Nur deren konkret geprüfte Parser-/Import-/Exportstrecke zusichern; keine automatische Bedeutung in fremden CAD-Systemen behaupten. Review-Einträge und Original-PMI getrennt zählen. Die Forderung nach einem vollständigen Register zertifiziert alte Fixtures nicht rückwirkend.

## Frische Wiederholungen und Herkunft der Inputs

- Für `contract_replay` einen neuen Build aus identischem eingefrorenem Vertrag durchführen; keine aktive Auswahl, gespeicherten Prozessvariablen oder vorhandene FCStd als Konstruktionsquelle verwenden.
- Für `step_only_rebuild` und `step_replay` je einen neuen Prozess verwenden, der nur STEP als Modellquelle erhält. Adapter/Prüfpolitik dürfen geladen werden. Ursprünglicher Vertrag, Zeichnung und FCStd dürfen fehlende STEP-Daten nicht ergänzen; den Sollvergleich erst nach abgeschlossener unabhängiger Rekonstruktion ausführen.
- Tatsächlich gelesene Eingaben im Bericht festhalten. Identische Quell-/Vertragshashes, Adapter-/Toolchainprofil und Prozessisolation belegen. Dateiname und Zeitstempel beweisen keinen frischen Lauf.
- Logische DAGs, Parameter, zugesagte Beziehungen, PMI- und Register-/Markerinventar sowie Geometrie vergleichen. STEP-Entity-IDs auf logische Identität abbilden; andere Seriennummern sind kein Inhaltsunterschied.
- Datei-Hashes dürfen wegen Serialisierung abweichen. Fehlende Wiederholungsart separat `not_tested` melden; zwei STEP-Importe beweisen nicht automatisch einen zweiten Build aus dem Vertrag.

## Editierbarkeit und native Bedienoberfläche

Eine relevante vorgelagerte Parametervariable wählen, deren geometrische Folge unabhängig berechenbar ist. Änderung, zulässiger Bereich, erwartete Folge und Rücksetztest vor Ausführung festlegen. Rekonstruktion muss bis zur Wurzel neu berechnen und Zwischenoperationen erhalten. Danach Ausgangswert zurücksetzen und ursprüngliche Geometrie erneut prüfen. Ein einzelner Test beweist nicht beliebige Änderungen aller Parameter.

Falls zugesagte Beziehungen existieren, zusätzlich eine Änderung wählen, die diese Beziehung beansprucht: Gleichheit, Kopplung, Tangentialität oder Positionsregel muss tatsächlich reagieren. Unabhängige gleichlautende Werte oder Zellen zählen nicht als Kopplung. Native Skizzen auf ihren tatsächlichen Constraint-Umfang prüfen; vollständig bestimmte primitive Rechtecke beweisen kein vollständiges Entwurfsnetz des Bauteils.

UI-Metadaten dürfen Labels, Parameterzuordnungen oder eine native Darstellungsstrategie liefern. Die frisch importierten Konstruktionswerte gegen den Standard-STEP-Operationsgraph prüfen; widersprechende UI-Werte ablehnen. Die Anzahl vorhandener Spreadsheet-Zellen ist kein Nachweis vollständiger Editierbarkeit.

## Änderung und Rückexport

Aus der STEP-only-Rekonstruktion eine Änderungsversion erzeugen. Modellrevision, geänderte Parameter, Auswirkungen auf Geometrie, Beziehungen, PMI und Review-Einträge explizit erfassen. Betroffene Original-PMI zunächst `stale` setzen, neu berechnen/zuordnen/präsentieren und prüfen. Originalen Zeichnungswert und neuen Entwurfswert nicht still gleichsetzen: Abweichung von der Zeichnung im Register dokumentieren.

Den geänderten konstruktiven Graph und End-BREP sowie alle verlangten aktualisierten PMI/Review-Daten als neuen AP242-Kandidaten exportieren. In einem weiteren frischen Prozess ausschließlich aus diesem STEP rekonstruieren. Geänderten Parameter, erwartete Folgewirkung, Beziehungen und jede betroffene Annotation prüfen. Unbetroffene Original-PMI müssen weiterhin erhalten sein. Ein zurückgesetzter nativer Änderungstest ohne diesen Rückexport beweist nur Editierbarkeit.

Ein fehlender Rückadapter oder fehlende automatische PMI-Aktualisierung blockiert die entsprechende Behauptung. Manuell aktualisierte PMI sind nur dann akzeptabel, wenn sie explizit versioniert und vollständig neu geprüft werden; den Ablauf nicht als automatisiert bezeichnen. Den gültigen Ausgangsmaster erhalten.

## Bericht, Review und Veröffentlichung

Ein JSON-Bericht nennt Auftrag, Dateipfade/-hashes, Vertragshash/-revision, Adapter-/Toolchainversionen, erlaubte und tatsächlich verwendete Inputs, Fähigkeitsumfang, Status je Prüfgruppe, Messmethoden/Messwerte, Testparameter, Register und erzeugte Artefakte. `pass` nur aus tatsächlich gemessenen Ergebnissen setzen. Historische Nachweise, aktuelle Tests und geplante Erweiterungen getrennt ausweisen.

Nur einen Kandidaten mit bestandenen auftragsrelevanten Gruppen als aktuellen Master markieren. Für geforderte Gruppen sind `fail` oder `not_tested` Veröffentlichungshindernisse; einen hilfreichen Teilstand klar als Kandidat mit fehlendem Nachweis bereitstellen. Bereits autorisierte Annahmen verlangen keine erneute Freigabe. Inhaltliche Widersprüche, neue nötige Entscheidungen oder fehlende Fakten konkret benennen.

Übergeben: Master oder Kandidat, deklarativer Vertrag, Prüfbericht, sichtbare Original-PMI/Review-Ansichten, gegebenenfalls abgeleitete FCStd sowie Handoff-Manifest nach [model-agnostic-workflow.md](model-agnostic-workflow.md). Grenzen und nächster Schritt müssen ohne Chatgeschichte verständlich sein. Alte Masterdatei bis zum validierten Nachfolger erhalten.

## Ausschließlich fallbezogene historische Nachweise

Diese Zahlen gelten nur für die identischen Fixtures; weder Geometrie, Maße noch Toleranzen auf neue Teile übertragen:

- Im bisherigen mm-Referenzfall wurden nominale Werte mit `1e-7` und Materialvolumendifferenzen mit `1e-5 mm³` geprüft.
- Befestigung: Änderung des rechten Bohrungsradius von 6 auf 5,5 mm bei 20 mm Materialdurchdringung ergibt unabhängig `pi * (6² - 5.5²) * 20 = 361.2831551628262 mm³` Volumenzunahme. Die Werkzeughöhe 22 mm ist nicht die Materialdicke. Danach Radius zurücksetzen. Der dokumentierte Ausgangsstand hat keinen nachgewiesenen Autorierungs-Rückexport.
- Maschinenteil: Integration wich ungefähr `0,000556 mm³` ab, während beide gerichteten Materialdifferenzen null waren. Den Befund mit seinen Messmethoden erhalten, nicht als allgemeine Toleranzerhöhung verwenden.
- Maschinenteil: Der dokumentierte Bohrungsradius-Rückexport belegt Konstruktion/Geometrie innerhalb seines Adapterteilumfangs; automatische PMI-Aktualisierung und vollständige allgemeine Relations-/Markerübertragung folgen daraus nicht. Neue UI-/Review-Erweiterungen benötigen eigene Berichte.
