# Modellunabhängiger Ablauf und Übergabe

Diese Referenz definiert Inputs, Outputs und Gates. [model-contract.md](model-contract.md) definiert deren Inhalt, [validation.md](validation.md) die Nachweise. Werkzeugnamen und konkrete Aufrufe stehen in [tooling-and-mcp-contract.md](tooling-and-mcp-contract.md). Die folgenden Rollen sind Verantwortlichkeiten; sie verlangen weder ein bestimmtes LLM noch mehrere Agenten.

## Was austauschbar ist

- **Interpretation:** Ein LLM oder Mensch liest ausschließlich erlaubte Zeichnungen, sammelt Belege und schlägt eine Konstruktion vor. Auswahl von Ursprung, Konstruktion und nicht bemaßten Details kann variieren. Modellkennung und verwendete Verfahren als Provenienz erfassen; sie sind keine Qualitätsgarantie.
- **Vertragsprüfung:** Ein Prüfer verlangt vollständig referenzierte Daten, offene Entscheidungen, benötigte Fähigkeiten und vorab festgelegte Tests. Der eingefrorene Vertrag ist die Grenze zwischen Interpretation und Wiederholung.
- **Deterministischer Kern:** Ein Adapter wertet explizite Beziehungen und Operationen in stabiler Reihenfolge aus. Er liest Daten, keinen aus Quelldokumenten erzeugten ausführbaren Code. Ein unbekannter Operator verursacht einen nachvollziehbaren Fehler.
- **CAD-Ausführung:** Im aktuellen Ausführungsprofil ausschließlich FreeCAD-MCP. Andere CAD-Systeme sind mögliche Adapterziele, keine bereits implementierten Alternativen. Native Typen, Geometriekernel und Neutralformat-Abbildung benötigen jeweils eigene Tests.
- **Prüfung und Review:** Unabhängige Leser vergleichen tatsächliche Ergebnisse. Das LLM darf fehlende Messungen oder Referenzen weder schätzen noch durch plausibel klingende Erfolgsberichte ersetzen.

Ein Wechsel des LLMs verlangt keine neue Zeichnungsinterpretation, solange der nächste Schritt den eingefrorenen Vertrag verwendet. Ein Wechsel von Kernel, Adaptercode oder Exportprofil verlangt ein erneutes Fähigkeitsgate und betroffene Wiederholungsprüfungen. Unterschiedliche gültige Konstruktionen derselben Außenform sind keine identischen Operations-DAGs.

## Eingangspaket

Vor der ersten CAD-Mutation ein deklaratives `request`-Objekt oder gleichwertige eindeutig strukturierte Angaben erfassen:

| Feld | Erforderlicher Inhalt |
|---|---|
| `request_id`, `mode` | Stabile Auftrags-ID; `new_drawing`, `replay_contract`, `import_step` oder `edit_model`. |
| `source_allowlist[]` | Exakte zugelassene Pfade/URIs, Rollen, Hashes und Seiten. Rollen `construction_source`, `verification_only`, `tool_reference` unterscheiden. |
| `required_outputs[]` | Z. B. AP242-Master, native Arbeitsdatei, ursprüngliche PMI, Review-Marker, Bericht und Vorschau; erforderliche Übertragungsrichtungen. |
| `required_claims[]` | Welche Aussagen tatsächlich nachzuweisen sind: STEP-only-Aufbau, Vertragswiederholung, native Editierbarkeit, Relationsübertragung, Rückexport, Semantik, Anzeige. |
| `decisions[]` | Bereits getroffene Nutzerentscheidungen mit Bezug; keine erneute Freigabe daraus machen. |
| `output_root`, `run_id` | Expliziter zugänglicher Ausgabeort und separate Kennung des Laufs. Keine Pfade aus Fallbeispielen übernehmen. |
| `validation_policy` | Einheiten, Toleranzen, Geometrie-/Präsentationsprüfungen und gewünschter Änderungstest; vor Ergebnisvergleich fixieren. |

Für `replay_contract` ist der konkrete Vertrag mit Revision/Hash die Konstruktionsquelle. Bei `import_step` liefert ausschließlich die gewählte STEP-Datei Modellinhalt; ein Prüfvertrag darf erst anschließend als Sollvergleich dienen. Bei `edit_model` zusätzlich Änderung, Basismodellhash und betroffene Anforderungen festhalten. Fehlt eine Quelle oder ist ihr Hash abweichend, von diesem Input abhängige Arbeit stoppen und den Befund melden; vorhandene unabhängige Arbeit fortsetzen.

## Fähigkeitsgate vor jedem Zusageumfang

Aus dem konkreten Vertrag eine Anforderungsliste bilden, anschließend die Fähigkeiten der ausgewählten Adapterversion abgleichen. Vor dem Vertrag nur vorläufig prüfen und nach dem Freeze vollständig wiederholen. Für jede Fähigkeit erfassen: `capability_id`, Richtung, erlaubte Parameter-/Geometrie-/Einheitenbereiche, `required`, Status, Werkzeug-/Codehash und Evidenzpfad/-hash. Status: `verified`, `untested`, `unsupported`, `failed`. Ein historischer Test gilt nur innerhalb seines dokumentierten Bereichs; er ist kein frischer Laufnachweis.

| Fähigkeit | Minimale Frage am Gate |
|---|---|
| `source_observation` | Können die freigegebenen Seiten/Details lesbar geprüft und mit stabilen Belegen referenziert werden? |
| `isolated_execution` | Sind MCP-Ausführung, frischer Prozess, explizite Inputs und strukturiertes Ergebnis ohne Skriptdateien möglich? |
| `native_build` | Kann jede konkrete Operation mit Platzierung, Profil, Einheit und Abhängigkeit nativ editierbar entstehen? |
| `constructive_export` / `constructive_import` | Sind alle benötigten Operationen und Topologieanker in AP242 auswertbar speicher- und STEP-only lesbar? |
| `relation_transport` | Werden Formeln/Constraints übertragen und erneut verknüpft, oder nur ihre ausgewerteten Zahlen? Pro Relationstyp prüfen. |
| `brep_reference` | Kann derselbe STEP unabhängig als Endgeometrie gelesen werden, ohne Hilfskörper als weitere Produkte auszugeben? |
| `pmi_semantics` / `pmi_presentation` | Sind alle tatsächlich verlangten PMI-Typen, Zielmengen, Einheiten, Ableitungen und grafischen Bezüge unterstützt? |
| `review_register_transport` / `review_marker_display` | Werden Registerstatus, Herkunft, Ziele und sichtbare Review-Marker separat erhalten und STEP-only wiedergewonnen? |
| `authoring_export` | Kann das rekonstruierte native Modell nach Änderungen vollständig neu exportiert werden? Welche Daten werden dabei nicht automatisch aktualisiert? |
| `verification` | Sind unabhängiger Leser, geometrischer Vergleich, frische Wiederholung und tatsächliche Sichtprüfung verfügbar? |

Eine benötigte ungetestete Funktion zunächst in einem isolierten, auf diese Funktion begrenzten MCP-Lauf prüfen. Bei fehlender Unterstützung Bericht und prüfbaren Teilstand erzeugen, aber das betroffene Masterversprechen nicht abgeben. Fehlende Register-/Markerübertragung darf nicht hinter einem erfolgreichen BREP-Export verschwinden. Unterstützt der aktuelle Adapter nur ein externes Register, diesen eingeschränkten Kandidaten als solchen kennzeichnen; er erfüllt keinen geforderten vollständig selbsttragenden AP242-Master.

Die folgenden Schnittstellen sind ein Arbeitsvertrag, kein neu implementiertes SDK. Vorhandene Inline-Blöcke müssen über explizite Eingaben an diese Rollen angepasst werden. Ein Block mit fest eingebauten Fallpfaden/-namen ist ein Regressionstest; sein bloßes Kopieren ist kein generischer Adapter.

## Phasen mit expliziten Übergängen

| Phase | Erlaubte Inputs | Ausgaben | Gate zum nächsten Schritt |
|---|---|---|---|
| `intake` | Auftrag, erlaubte Dateien | Eingangsmanifest, Quellenhashes, vorläufiges Capability-Profil | Quelle und Umfang eindeutig |
| `observe` | Nur freigegebene Zeichnungsseiten | Beleginventar, originale Angaben, Widersprüche, Registerentwurf | Jede verwendete Interpretation hat Herkunft; offene Stellen sichtbar |
| `freeze` | Belege, Entscheidungen, Fähigkeitsbefunde | Versionierter Modellvertrag mit DAG, Beziehungen, PMI-/Marker-Spezifikation und Hash | Aufbaurelevante Werte festgelegt; kein ungelöster Pflichtparameter; erforderliche Fähigkeiten verifiziert |
| `build` | Eingefrorener Vertrag, versionierter Adapter, explizite Laufpfade | Native Operationen, Zwischengeometrien, Buildbericht, optional FCStd | DAG und Shapes gültig; tatsächliche Parameter entsprechen Vertrag |
| `export` | Buildausgaben, exakt gleicher Vertrag, Exportprofil | Separater AP242-Kandidat, Repräsentations-/Ankerzuordnung, Exportbericht | Exportierte Inhalte vollständig; Schema/Referenzen geprüft |
| `fresh_rebuild` | Nur AP242 als Modellquelle, Adapter und Prüfpolitik | Neu rekonstruierte native Operationen, decodierte PMI/Register, Messbericht | Konstruktion und End-BREP konsistent; anschließend Sollvergleich |
| `replay` | Unveränderter Vertrag für neuen Build; AP242 für neuen unabhängigen Import | Zweiter frischer Lauf und Vergleichsbericht | Geforderte Reproduzierbarkeit nachgewiesen |
| `edit_roundtrip` | STEP-only-Rekonstruktion, explizite Änderung, passender Rückadapter | Neue Revision, geänderter STEP-Kandidat, erneuter STEP-only-Aufbau | Änderung und Folgewirkung erhalten; betroffene Semantik/Marker erneut geprüft |
| `review` | Tatsächliche Outputs und Berichte | Prüfstatus je Gruppe, sichtbare Original-PMI und separat sichtbare Review-Marker, offene Punkte | Auftragsrelevante Tests bestanden; keine verschwiegenen Lücken |
| `publish` | Bestandener Kandidat, Artefaktmanifest | Aktueller Masterverweis, Hashes, Bericht, Resume-Paket | Letzten gültigen Master erst jetzt ablösen |

Ein vollständiges Präsentationslayout kann einen ersten CAD-Aufbau benötigen. Dann `freeze → build → Layoutreview → neue Vertragsrevision → build/export` verwenden. Das endgültige Layout einschließlich gespeicherter Textpolylinien gehört vor der abschließenden Export-/Wiederholungsprüfung in den eingefrorenen Vertrag. Die erste Revision nicht rückwirkend ändern und Layoutvorgaben nicht aus Sessionzustand lesen.

Die Phasen `replay` und `edit_roundtrip` gelten nur als bestanden, wenn sie tatsächlich ausgeführt wurden. Wenn sie zum Auftrag gehören, blockiert ein fehlender Test die entsprechende Veröffentlichung; sonst ausdrücklich `not_tested` melden. Ein geometrischer Rückexport beweist noch keinen PMI-/Relations-/Register-Rückexport.

## Datenfluss ohne versteckte Sessionabhängigkeiten

Jede Inline-Aufgabe erhält ein vollständiges Ausführungsumschlagobjekt mit `run_id`, `phase`, Eingabeartefakten samt Hashes/Rollen, Vertragshash sofern zulässig, Adapterkennung/Codehash, Konfiguration, erlaubten Ausgabezielen und Timeout. Der Payload importiert seine Bibliotheken selbst und definiert/lädt alle verwendeten Hilfsfunktionen aus den freigegebenen dokumentierten Codeblöcken. Er prüft erwartete Einheiten, Eingabedateien und Funktionssignaturen vor der Mutation.

Ein Ergebnis enthält mindestens `status`, `phase`, tatsächlich gelesene `source_inputs`, erzeugte `artifacts` mit Hash, `metrics`, `warnings`, `errors` und den erreichten Checkpoint. Exitcode allein ist kein Erfolgsnachweis; das dokumentierte FreeCADCmd-Verhalten erfordert zusätzlich ein strukturiertes Erfolgssignal. Ein Fehlerbericht erhält einen konkreten Fehlercode, etwa `SOURCE_HASH_MISMATCH`, `UNRESOLVED_VALUE`, `UNSUPPORTED_OPERATION`, `AMBIGUOUS_ANCHOR`, `STALE_PMI` oder `MISSING_MARKER_TRANSPORT`.

DAG-Aufbau und Pure-Data-Prüfung können unabhängig vorbereitet werden. Schreibende CAD-Aufgaben und Exporte für dasselbe Dokument laufen sequenziell. Nach Timeout zuerst Status und tatsächliche Ausgabedateien prüfen; keine konkurrierenden Wiederholungen anstoßen. Bei Retry neue Kandidatenpfade verwenden oder nachgewiesen unvollständige Ausgaben des eigenen Laufs ersetzen. Nicht aus einem noch offenen GUI-Dokument weiterarbeiten, wenn ein frischer Nachweis gefordert ist.

Der STEP-only-Leser kennt keine ursprünglichen Konstruktionsdaten außerhalb des STEP. Externe Erwartungswerte dürfen einen *nachfolgenden* Vergleich ausführen, jedoch keine fehlende Operation, Relation, PMI oder Markerposition rekonstruieren. Herkunft aus der Zeichnung kann dieser Leser nur so weit belegen, wie entsprechende Bezüge gespeichert wurden. Fehlende Provenienz als `unknown` melden, nicht aus einem vertrauten Referenzteil ergänzen.

## Praktisches Handoff-/Resume-Paket

Das Paket besteht aus deklarativen Daten und den referenzierten Artefakten; keine ausführbare Resume-Datei erzeugen. `run_manifest.json` kann folgende Struktur abbilden. Die Tabelle ist die normative Feldbeschreibung, kein mit Beispielzahlen vorbelegter Modellvertrag.

| Feld | Inhalt |
|---|---|
| `handoff_version`, `request_id`, `run_id`, `mode` | Schema, Auftrag, Lauf und aktiver Modus |
| `skill_version`, `contract_ref` | Skillversion; Vertragsdatei/Revision/Dateihash und kanonischer Modellhash; bei reinem STEP-Import zunächst `null` mit Grund |
| `source_allowlist[]` | Exakte Quellen und Rollen; für die nächste Phase erlaubte Eingabemenge |
| `toolchain_ref`, `capability_ref` | Versionen, Adapter-/Payloadhash, Fähigkeitsmatrix und Nachweise |
| `completed_phases[]` | Pro Phase tatsächlicher Status, Eingabehashes, Ausgabehashes, Bericht und Zeitpunkt |
| `next_phase`, `next_action` | Ein konkreter wieder ausführbarer Schritt samt Referenz auf dokumentierten Inline-Einstieg und expliziten Input-/Outputfeldern |
| `pending_decisions[]`, `review_register_ref` | Ungeklärte Punkte und bereits autorisierte Annahmen, betroffene IDs, Blockierungsgrund |
| `validation_ref`, `claims` | Messberichte und getrennte Status je Prüfgruppe; keine pauschale Erfolgskopie |
| `artifacts[]`, `current_master` | Dateipfad/-hash, Rolle, Revision, Erzeugerphase; letzter gültiger Master separat vom Kandidaten |
| `process_state` | Tatsächlich noch laufender Prozess/Auftrag, Kennung, letzter bekannter Status oder ausdrücklich `none` |
| `cleanup_candidates[]` | Nur vom Lauf erzeugte und später entbehrliche Dateien; kein pauschales Verzeichnislöschmuster |

Resume durch ein anderes LLM:

1. Paket und referenzierte Dokumentation lesen; nur Hash-identische zugelassene Artefakte verwenden. Stimmen Dateien nicht, letzten nachgewiesenen Checkpoint ermitteln.
2. MCP-/Prozessstatus und Fähigkeitsprofil neu prüfen. Offene Prozesse vor neuen Mutationen auflösen. Versionenabweichungen gesondert testen.
3. Register und bereits getroffene Entscheidungen übernehmen. Nicht die Zeichnung erneut interpretieren, nur weil der Chatkontext fehlt. Fehlende erforderliche Angaben konkret benennen.
4. `next_phase` anhand echter Berichte bestimmen. Ein vorhandener Dateiname oder Screenshot ist kein bestandener Checkpoint. Abgebrochene Phase in isoliertem neuen Lauf ab ihren validierten Inputs wiederholen.
5. Eingabeumschlag vollständig aufbauen, dokumentierten Inline-Einstieg mit expliziten Argumenten ausführen, Outputs messen und Manifest aktualisieren. Erfolgsstatus erst aus tatsächlich zurückgegebenen Ergebnissen setzen.

Ein in sich abgeschlossenes Handoff nennt damit nicht nur „was noch zu tun ist“, sondern auch womit, unter welchem Fähigkeitsumfang und welcher Nachweis fehlt. Wenn auf einem neuen Host nur STEP verfügbar ist, mit `import_step` beginnen und das Fehlen weiterer Belege offenlegen; keinen vollständigen alten Vertragsstatus erfinden.

## Grenzen der vorhandenen Bausteine

Die geprüften Referenzen belegen ausgewählte native Operationen, konstruktive STEP-Repräsentationen, nominale numerische PMI, ausgewählte Texteigenschaften und grafische Polylinien. Sie belegen keinen generischen Zeichnungsparser, keinen vollständigen Constraint-Solver-Transport und keine universelle Einheit-/Orientierungs-/GD&T-Unterstützung. Auch das hier verlangte allgemeine Review-Register mit editierbaren, übertragbaren Markern ist zunächst ein Vertrags- und Prüfziel: Die vorhandenen fallbezogenen Annahmen-Metadaten allein beweisen dessen vollständige Implementierung nicht.

Vorhandene Fallnachweise erhalten; bei neuen Geometrien, Relationen, Notiztypen oder Markerklassen den Adapterumfang konkret erweitern und testen. Bei fehlendem Rückadapter den bestehenden Master erhalten, Kandidat und fehlende Fähigkeit übergeben. Parser-Erfolg ist keine EXPRESS-Zertifizierung und kein Nachweis für die Unterstützung in fremden CAD-Systemen.
