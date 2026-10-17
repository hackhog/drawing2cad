# drawing2cad

Werkzeuge und ein reproduzierbarer Agenten-Workflow zur Rekonstruktion von CAD-Modellen aus technischen PDF-Zeichnungen. Der Python-MCP bereitet PDFs auf und bündelt den Zugriff auf den vorhandenen FreeCAD-MCP. Der Skill beschreibt Modellierung, Quellenbelege, offene Maße und die Prüfung von CAD-/STEP-Ergebnissen.

## Projektstruktur

| Pfad | Inhalt |
|---|---|
| [drawing2cad-mcp/](drawing2cad-mcp/README.md) | Python-Server, Installation, Konfiguration und Tests |
| [skills/freecad-ap242/](skills/freecad-ap242/SKILL.md) | Skill, Ablauf, Adapterbeschreibungen und Referenzen |
| `resources/` | Originalzeichnungen und CAD-Referenzen für die Validierung |
| `output/` | Lokal erzeugte Modelle, Zeichnungen, Vorschaubilder und Prüfberichte |
| `tmp/` | Lokale temporäre Arbeitsdaten |

## Einstieg

Die [MCP-Dokumentation](drawing2cad-mcp/README.md#installation) enthält die Einrichtung mit Python, Poppler und FreeCAD sowie die Testbefehle. Die portable Vorlage [drawing2cad-mcp.example.toml](drawing2cad-mcp/drawing2cad-mcp.example.toml) wird als `drawing2cad-mcp.local.toml` kopiert und für den jeweiligen Rechner angepasst.

Der MCP liefert PDF-Metadaten, Text, gerenderte Seiten und Detailausschnitte sowie die weitergeleiteten FreeCAD-Werkzeuge. CAD-Historie, semantische PMI und Headless-Exporte müssen für den jeweiligen Adapter und Werkzeugstand separat geprüft werden; ein STEP-Export allein belegt diese Eigenschaften nicht.

## Versionierung

Quellcode, Tests, Abhängigkeitsdateien, Beispielkonfigurationen, Skill-Referenzen und Originalressourcen gehören ins Repository. Die 36 vorhandenen Ressourcendateien umfassen zusammen rund 13 MiB und werden ohne Git LFS verwaltet.

Generierte Modelle, Zeichnungen, Renderings und Laufberichte gehören ausschließlich in die ignorierten Verzeichnisse `output/`, `outputs/`, `out/`, `artifacts/` oder `tmp/`. Diese Ausschlüsse gelten auch in Unterverzeichnissen. Die Dateien bleiben lokal verfügbar und werden nicht versioniert. Umgebungen, Caches, FreeCAD-Backups und rechnerabhängige Konfigurationen sind ebenfalls ignoriert. Fest gepflegte Skill-Referenzen und Regressionseingaben sind Bestandteil des Quellprojekts.

`.gitattributes` vereinheitlicht Textdateien auf LF und erhält die Originalbytes der Ressourcen und STEP-Dateien, damit ihre Quellprüfsummen beim Klonen unverändert bleiben. PDF-, Bild- und native CAD-Dateien werden als binär behandelt. Tatsächliche CAD-Modelle und Zeichnungen außerhalb der generierten Ausgabeordner werden nicht pauschal ausgeschlossen.
