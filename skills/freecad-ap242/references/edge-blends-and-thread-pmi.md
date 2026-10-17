# Konstante Verrundungen und Gewindebezeichnungen

Diese Erweiterung betrifft Modelle mit echten Verrundungsschritten oder einer Gewindebezeichnung ohne vollständig spezifizierte Gewindegeometrie. Die grundlegenden Prüfungen aus `validation.md` gelten weiterhin. Den jeweiligen Modellvertrag verwenden; Maße des Maschinenteil-Referenzfalls nicht auf andere Zeichnungen übertragen.

## Verrundungen im konstruktiven STEP-Graph

AP242 beschreibt die Operation mit `SOLID_WITH_CONSTANT_RADIUS_EDGE_BLEND(name, rationale, base_solid, blended_edges, radius)`. `blended_edges` enthält eindeutige `EDGE_CURVE`-Referenzen. Die konstruktive Basis muss erhalten bleiben; ein BREP-Zwischenkörper allein ersetzt sie nicht.

Die installierten OCCT-7.8.1-Bindings kennen diese Entity nicht als typisierte Klasse. Der standardkonforme Datensatz kann trotzdem im Part-21-Graph stehen. Ein eigener Parser muss ihn und alle davon abhängigen booleschen Operationen lesen. Niemals unbekannte Operanden als leere Form oder als fertigen Endkörper behandeln. Die unverstandenen Standard-Entities erst nach der üblichen OCCT-Serialisierung ergänzen, damit der Writer keine Referenzen verwirft.

Die Konstruktionsfolge wird durch `PROCEDURAL_SHAPE_REPRESENTATION_SEQUENCE` in einer `PROCEDURAL_SHAPE_REPRESENTATION` beschrieben. `EXPLICIT_PROCEDURAL_SHAPE_REPRESENTATION_RELATIONSHIP` verbindet diese mit der berechneten End-BREP. Eine Verrundung darf nicht unmittelbar als Item einer `CSG_SHAPE_REPRESENTATION` stehen; deren zulässige Item-Typen sind enger.

Für die Kantenauswahl die tatsächliche Basisform unmittelbar vor jeder Verrundung als Hilfs-BREP exportieren. Über den Transfer-Finder die zu den ausgewählten TopoDS-Kanten gehörenden `EDGE_CURVE`-Entities ermitteln. Nur die Hilfs-BREP und ihre Abhängigkeiten zum endgültigen STEP-Modell hinzufügen, keinen weiteren Produktkörper. `EXPLICIT_PROCEDURAL_GEOMETRIC_REPRESENTATION_ITEM_RELATIONSHIP` verbindet die vorausgehende Konstruktionssequenz mit dieser Topologie.

Beim Import die gespeicherten Kanten geometrisch auf der neu aufgebauten Basis identifizieren. Eigenschaften wie Kurventyp, Länge, Endpunkte und Abstand zur gespeicherten Kurve kombinieren. Jede Zuordnung muss eindeutig sein; fehlende oder mehrdeutige Treffer sind Fehler. Entity-IDs oder FreeCAD-Kantennummern sind keine stabilen geometrischen Identitäten. Zylindernähte können einen geometrischen Bogen in mehrere topologische Kanten teilen. Solche Änderungen dürfen nicht durch stilles Verwerfen von Kanten kaschiert werden.

Der normale STEP-Geometrieimport soll weiterhin genau den erwarteten Endkörper liefern. Parser-Erfolg allein beweist weder diesen Umstand noch einen korrekten Wiederaufbau. Frische Importläufe, geometrische Differenzen und ein Parameteränderungstest sind erforderlich. Ein vollständiger EXPRESS-Konformitätstest ist gesondert auszuweisen.

Primärquellen: [Konstante Kantenverrundung](https://www.steptools.com/docs/stp_aim/html/t_solid_with_constant_radius_edge_blend.html), [prozedurale Sequenz](https://www.steptools.com/docs/stp_aim/html/t_procedural_shape_representation_sequence.html), [explizite Ergebnisverknüpfung](https://www.steptools.com/docs/stp_aim/html/t_explicit_procedural_shape_representation_relationship.html).

## M10 als semantische Bezeichnung

Die vollständige Tabelle des Benutzerlinks mit 35 Größen von M1 bis M68 sowie kurze Hinweise zu typischen Fasen stehen in [metric-thread-chamfers.md](metric-thread-chamfers.md). Konkrete Fasenbreiten bleiben separat zu bestimmen.

Wenn nur `M10` angegeben und eine vereinfachte Darstellung vereinbart ist, einen nominalen Zylinder mit einer geometrisch verknüpften semantischen Text-Eigenschaft erzeugen. Geeignete Standardkette: `SHAPE_ASPECT` → `PROPERTY_DEFINITION` → `PROPERTY_DEFINITION_REPRESENTATION` → `DESCRIPTIVE_REPRESENTATION_ITEM`. Die grafische Beschriftung muss auf dieselbe Eigenschaft verweisen.

Eine solche Bezeichnung ist keine vollständig parametrisierte `THREAD`-Feature-Entity. Zusätzliche Werte nicht aus der vereinfachten Zylinderform ableiten. Eine normierte Gewindebezeichnung jedoch zuerst auflösen, bevor ein Wert als fehlend eingestuft wird: Bei einem metrischen ISO-Regelgewinde bedeutet `M10` die Regelsteigung 1,5 mm. Die Steigung ist dann eine aus der Bezeichnung und der angewandten Norm abgeleitete Angabe, kein separat eingezeichnetes Maß und keine frei erfundene Annahme. Die offizielle FreeCAD-Tabelle führt `M10x1.5` in der Reihe `ISO metric regular`; ISO 965-1 beschreibt das Weglassen der Regelsteigung in der Bezeichnung. Im Modellvertrag den Originaltext `M10`, die aufgelösten Werte und die zugrunde gelegte Norm mit Ausgabe getrennt erhalten. Ist die Normzuordnung selbst unklar, diese Interpretation kennzeichnen. `M10` nicht durch ein scheinbar aus der Zeichnung stammendes numerisches Ø10-Maß ersetzen.

Auch eine nicht ausgeschriebene Toleranzklasse ist nicht automatisch eine blockierende Unklarheit: erst Normvorgaben und Anwendungskontext prüfen. Zwischen einem idealisierten Nennprofil zur Visualisierung und einer Geometrie mit gewählten Fertigungsgrenzmaßen unterscheiden. Toleranzlage, tatsächliche Gewindelänge, Auslauf, Freistich und Endfase nur so weit festlegen, wie die Zeichnung, eine ausdrücklich angewandte Norm oder eine bestätigte Annahme sie tragen. Ein Nennprofil mit PMI ist kein Nachweis einer konkreten gefertigten Passung. Für aktuelle Normauflösung die anwendbare Ausgabe prüfen; ISO 965-1:2026 hat die Ausgabe 2013 abgelöst. Ein historischer Bezeichnungsbeleg allein validiert keine vollständige Auslegung nach Ausgabe 2026.

Im Maschinenteil-Referenzfall bleibt die vom Benutzer bestätigte Darstellung ein Hüllzylinder mit M10-PMI. Die neue Möglichkeit einer detaillierten Darstellung hebt diese frühere Entscheidung nicht automatisch auf. Die unbemaßte Endfase bleibt als Unklarheit markiert; sie wird nicht aus der Gewindebezeichnung erzeugt.

Auch bestätigte Annahmen als solche im Hauptmodell erhalten. Sie sind getrennt von originalen Zeichnungsmaßen zu zählen und zu prüfen. Allgemeine Zeichnungsnotizen, beispielsweise „nicht bemaßte Radien R=1“, benötigen eine semantische Eigenschaft mit ihrem tatsächlichen Geltungsbereich; keine pauschale Rundung aller Kanten daraus ableiten.

## Echte Gewindegeometrie und editierbare Gewindeoperation

Drei Fähigkeiten getrennt ausweisen:

1. **Geometrie:** FreeCAD kann ein echtes Schraubengewinde als Profil entlang einer Helix erzeugen, etwa mit einer parametrischen Helixoperation oder mit Helix, Profil, Sweep und boolescher Verknüpfung. Die entstehenden Flächen und Kanten lassen sich grundsätzlich als BREP in STEP AP242 übertragen. Damit ist ein echter Gewindegang sichtbar. Eine Folge von Ringen oder ein beschrifteter Zylinder ist keine gleichwertige Geometrie. Diese grundsätzliche Möglichkeit ist dokumentiert; ein erfolgreicher Export und frischer Reimport der konkreten Geometrie bleibt nachzuweisen.
2. **Semantik:** Das STEP-`THREAD`-Feature definiert eine Gewindebedeutung mit verknüpften Parametern, unter anderem Außendurchmesser, Form, Richtung, Innen-/Außengewinde und Passungsklasse. Die Regeln für `SHAPE_REPRESENTATION_WITH_PARAMETERS`, zugehörige Flächen und die tatsächlich verwendete AP242-Ausgabe beachten. Eine `THREAD`-Entity allein erzeugt weder die Helixflächen noch automatisch eine native CAD-Operation. Die vorhandene M10-Text-Eigenschaft nicht als bereits implementiertes `THREAD`-Feature ausgeben.
3. **Parametrischer Wiederaufbau:** Ein normaler STEP-BREP-Import stellt die Gewindeoberfläche wieder her. Für eine danach editierbare Gewindeoperation muss ein Adapter die vollständige Definition in native Profil-/Helix-/Sweep- oder Gewindefeatures übersetzen und ihre Abhängigkeiten erhalten. Der gegenwärtige Adapter dieses Skills unterstützt Rechteck-/Kreisextrusionen, boolesche Operationen und konstante Kantenverrundungen; Helix-, Sweep- und `THREAD`-Wiederaufbau sind noch nicht implementiert oder geprüft.

Eine Adaptererweiterung muss mindestens Profildefinition, Einheit, Achse und Platzierung, Steigung beziehungsweise Vorschub und Gangzahl, Richtung, axialen Bereich sowie gewählte Anfangs-/Endbehandlung reproduzierbar kodieren. Gewindebedeutung und tatsächlich ausgewertete Operationen mit derselben End-BREP verbinden. Unbekannte Gewindeoperationen als nicht unterstützt zurückweisen; nicht durch einen Endkörper ersetzen und dennoch Editierbarkeit behaupten. Als Nachweis frischen STEP-only-Wiederaufbau, gültigen Solid, Geometrievergleich, Steigungs-/Längenänderung mit Neuberechnung und Rücksetzung sowie Speichern/Öffnen prüfen. Bei Geometrieänderung PMI und Reviewanker erneut validieren.

Primärquellen:

- [FreeCAD: echte Gewinde mit Helix und Profil](https://github.com/FreeCAD/FreeCAD-documentation/blob/main/wiki/Thread_for_Screw_Tutorial.md)
- [FreeCAD: parametrische Additive Helix](https://github.com/FreeCAD/FreeCAD-documentation/blob/main/wiki/PartDesign_AdditiveHelix.md)
- [FreeCAD-Quellcode: ISO-Regelgewindetabelle, M10x1.5](https://github.com/FreeCAD/FreeCAD/blob/main/src/Mod/PartDesign/App/FeatureHole.cpp)
- [ISO 261:1998: allgemeiner Plan metrischer ISO-Gewinde](https://www.iso.org/standard/4165.html)
- [ISO 965-1:2013, Bezeichnung in Abschnitt 12.2; Normtext als historische Primärquelle](https://www.finesz.com/pic/ISO965-1.pdf)
- [ISO 965-1:2026: aktuelle Ausgabe und Ablösung der Ausgabe 2013](https://www.iso.org/standard/87889.html)
- [OCCT: STEP-Translator, BREP-Geometrie und AP242-Ausgabeschema](https://occt3d.com/dev/doc/overview/html/occt_user_guides__step.html)
- [STEP THREAD-Feature und zugehörige Parameterregeln](https://www.steptools.com/docs/stp_aim/html/t_thread.html)
