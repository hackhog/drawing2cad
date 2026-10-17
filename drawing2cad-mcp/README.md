# drawing2cad-mcp

Lokaler MCP-Server für PDF-Metadaten, eingebetteten Text, Seitenbilder und Detailausschnitte. Er stellt außerdem die Werkzeuge eines vorhandenen FreeCAD-MCP mit dem Präfix `freecad_` bereit.

Agent → **drawing2cad-mcp** → PDF-Aufbereitung / bestehender FreeCAD-MCP → FreeCAD-Addon.

## Werkzeuge

| Tool | Zweck / Parameter |
|---|---|
| `drawing2cad_status` | Laufzeit und Proxyzustand; optional `refresh_freecad=true`. |
| `pdf_info` | `path`: SHA-256, Seitenzahl, Seitengröße, CropBox, Rotation. |
| `pdf_read_text` | `path`, optional `pages`, `max_chars=50000`: eingebetteter Text, keine OCR. |
| `pdf_render_page` | `path`, `page=1`, `dpi=150`, `include_image=true`: ganze Seite. |
| `pdf_crop_region` | `path`, `page`, `bbox`, `dpi=300`, `include_image=true`: Detailausschnitt. |
| `freecad_*` | Alle dynamisch entdeckten Upstream-Tools, jeweils mit Präfix; keine statisch nachgebauten Schemata. |

Bei dem vorhandenen FreeCAD-MCP sind es 17 weitergeleitete und 5 lokale Tools. Beispiel: `execute_code` wird zu `freecad_execute_code`; Argumente bleiben unverändert. Der Client kann einen zusätzlichen Server-Namespace voranstellen.

PDF-Ergebnisse enthalten maschinenlesbare `structuredContent` und dieselben Metadaten als Text. Render-/Crop-Ergebnisse enthalten zusätzlich ein PNG als MCP-Bild, sodass Agenten keinen separaten lokalen Bildbetrachter benötigen. Das vollständige PNG bleibt unter `artifact.path` verfügbar. Große Vorschauen werden begrenzt; `preview` nennt ihre tatsächlichen Maße und den Skalierungsfaktor.

## Installation

Voraussetzungen: **Python ≥3.11**, **Poppler mit `pdftoppm`** und für CAD ein bereits installierter FreeCAD-MCP samt erreichbarem FreeCAD-Addon. Der Server selbst benötigt keine GUI. Er verändert die Betriebsart des FreeCAD-Upstreams nicht.

Aus diesem Verzeichnis unter Windows:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[test]"
Copy-Item drawing2cad-mcp.example.toml drawing2cad-mcp.local.toml
```

Unter Linux/macOS entsprechend `python3 -m venv .venv` und `.venv/bin/python`. Poppler separat installieren oder den vorhandenen absoluten `pdftoppm`-Pfad konfigurieren. `requirements-tested.txt` hält die beim Test verwendeten Python-Paketversionen fest; sie können mit `pip install -c requirements-tested.txt -e ".[test]"` reproduziert werden. Geprüft wurde Windows/Python 3.12; andere Hosts sind noch nicht praktisch getestet.

Die TOML-Datei ausfüllen:

- `[pdf]`: erlaubte Quellverzeichnisse, Ausgabeordner und optional absoluter Poppler-Pfad. Ohne Pfad wird `pdftoppm` in `PATH` gesucht.
- `[freecad]`: `enabled=true`, vorhandenes MCP-Startprogramm in `command`, seine bisherigen `args`; optional `env` und `cwd`. Für reine PDF-Arbeit `enabled=false`.
- `[server]`: Grenzen für Bildvorschau und Parallelität. Die Standardwerte sind im Beispiel enthalten.

Relative **Konfigurationspfade** beziehen sich auf den TOML-Ordner. PDF-Toolaufrufe verwenden **absolute Dateipfade**. Die `.local.toml` dieses Rechners ist eine lokale Konfiguration; die portable Vorlage enthält keine Benutzerpfade.

## Beim Agenten registrieren

Nur diesen Server registrieren; er startet den vorhandenen FreeCAD-MCP intern. Für Clients mit `mcpServers`-Konfiguration, nach Ersetzen der Beispielpfade:

```json
{
  "mcpServers": {
    "drawing2cad": {
      "command": "C:/Projekt/drawing2cad-mcp/.venv/Scripts/python.exe",
      "args": ["-m", "drawing2cad_mcp", "--config", "C:/Projekt/drawing2cad-mcp/drawing2cad-mcp.local.toml"]
    }
  }
}
```

In Codex verwendet derselbe Eintrag TOML:

```toml
[mcp_servers.drawing2cad]
command = 'C:\Projekt\drawing2cad-mcp\.venv\Scripts\python.exe'
args = ["-m", "drawing2cad_mcp", "--config", 'C:\Projekt\drawing2cad-mcp\drawing2cad-mcp.local.toml']
startup_timeout_sec = 30
tool_timeout_sec = 1920
```

Die Beispiel-Toolfrist passt zur lokalen Upstream-Frist von 1900 Sekunden. Bei anderen Werten muss die Clientfrist länger als die erwartete Operation sein. Bestehenden direkten FreeCAD-Eintrag deaktivieren, wenn ausschließlich diese Schnittstelle angeboten werden soll. Nach Konfigurationsänderungen die MCP-Verbindung im Client neu laden. [Codex-Konfigurationsreferenz](https://learn.chatgpt.com/docs/config-file/config-reference).

Manuell startet der Protokollprozess so:

```powershell
.\.venv\Scripts\python.exe -m drawing2cad_mcp --config drawing2cad-mcp.local.toml
```

Er wartet dann auf einen MCP-Client an stdin/stdout. Logs gehen an stderr; eine leere Konsole bedeutet keinen Fehler.

## Reproduzierbarer PDF-Ablauf

1. Nur die konkret freigegebene PDF an `pdf_info` übergeben. `source.sha256` protokollieren.
2. `pdf_read_text` für benötigte Seiten aufrufen. `native_text_missing` heißt: keine nativen Textdaten gefunden; das Blatt visuell lesen.
3. `pdf_render_page` aufrufen und das zurückgegebene Bild ansehen.
4. Kritische Maße gezielt ausschneiden, zum Beispiel:

```json
{"path":"C:/Projekt/resources/Zeichnung.pdf","page":1,"bbox":[0.25,0.0,0.75,0.5],"dpi":300,"include_image":true}
```

5. Quellhash, Seite, Ausschnitt, Auflösung und Artefakthash mit dem Befund speichern. `source.sha256` bei jedem Aufruf vergleichen; eine geänderte Quelle ist eine neue Revision.

Seiten sind **1-basiert**. `bbox=[left,top,right,bottom]` ist auf **0..1 normalisiert**, mit Ursprung oben links in der dargestellten, rotierten Seite. Grundlage ist die effektive **Schnittmenge von CropBox und MediaBox**. Originale und effektive Box stehen in den Metadaten. Links/oben werden auf Pixel ab-, rechts/unten aufgerundet. Diese Koordinaten sind keine CAD-Koordinaten.

Die Seite wird zunächst vollständig gerendert und anschließend ausgeschnitten. Deshalb gilt `max_pixels` auch für die ganze Seite eines Crop-Aufrufs. DPI muss 36–600 betragen; mehr DPI kann fehlende Bildinformation einer Rasterquelle nicht ersetzen. Jeder Aufruf liest einen eigenen begrenzten PDF-Snapshot. Es gibt keine dokumentübergreifende Session oder automatische Interpretation von Zeichnungsmaßen.

## Verhalten und Grenzen

- PDF-Aufbereitung: pypdf für Text/Metadaten, Poppler für Rasterung, Pillow für Ausschnitte/Vorschau. Keine OCR und keine automatische CAD-Rekonstruktion.
- PDF-Quellen werden auf aufgelöste erlaubte Verzeichnisse, Dateigröße und Seiten-/Pixelgrenzen geprüft. Der Poppler-Prozess hat eine Zeitgrenze. Diese Zeitgrenze umfasst nicht den pypdf-Parser; dies ist kein isolierter Dienst für beliebige feindliche PDFs.
- Der Proxy erhält Schemata, Bilder, Ressourcenblöcke, strukturierte Ergebnisse und Fehlerstatus. Es ist ein **Tool-Proxy**; Upstream-Ressourcenlisten, Prompts, Sampling und Elicitation werden nicht vermittelt.
- `freecad.connected` bestätigt den MCP-Transport. Ob das FreeCAD-Addon selbst funktioniert, zeigt erst ein passender FreeCAD-Aufruf. Bei fehlendem Upstream bleiben PDF-Tools nutzbar. Ein zuvor entdeckter Katalog kann als `catalog_stale=true` erhalten bleiben.
- FreeCAD-Aufrufe werden pro Serverprozess serialisiert. Mehrere Clients mit eigenen Serverprozessen müssen gemeinsame CAD-Dokumente zusätzlich koordinieren.
- Fehlgeschlagene oder abgebrochene CAD-Aufrufe werden **nicht automatisch wiederholt**. Eine bereits gestartete Operation kann trotzdem wirksam geworden sein; vor Wiederholung den Zustand lesen.
- `freecad_execute_code` behält die Rechte des Upstreams. Die PDF-Pfadfreigabe schränkt beliebigen dort ausgeführten Python-Code nicht ein. Der Proxy ergänzt keine AP242-/PMI-Fähigkeit und keine Headless-Implementierung.

## Tests und Skill

```powershell
$env:DRAWING2CAD_PDFTOPPM = 'C:\Pfad\zu\pdftoppm.exe'
.\.venv\Scripts\python.exe -m pytest tests --basetemp tmp/tests -q
```

Ohne Poppler werden Renderingtests übersprungen. Symlinktests können ohne entsprechende Betriebssystemrechte übersprungen werden. Die Suite verwendet synthetische PDFs und einen harmlosen MCP-Testprozess; sie ändert keine FreeCAD-Modelle. Sie prüft u. a. Rotation, CropBox/MediaBox, UserUnit, Detailpixel, Quellenidentität, Fehler, Transporttreue und Abbruch ohne Wiederholung.

Der projektseitige Skill liegt unter `../skills/freecad-ap242`. Version **0.4.0** beschreibt diese Schnittstelle und den modellunabhängigen Ablauf in `references/drawing2cad-mcp.md`. Die eigentlichen CAD-/AP242-Adapter bleiben getrennte, explizit geprüfte Skillbestandteile.
