# drawing2cad-mcp

This local MCP server supplies PDF metadata, embedded text, page images, and detail images.
With the optional [vector extractor](../extractor/README.md), it also supplies the views, read text, and classified strokes of a vector drawing.
It also supplies tools from an existing FreeCAD MCP with the prefix `freecad_`.

Agent → **drawing2cad-mcp** → PDF preparation / existing FreeCAD MCP → FreeCAD addon.

## Tools

| Tool | Purpose and parameters |
|---|---|
| `drawing2cad_status` | Runtime and proxy status. Optional argument: `refresh_freecad=true`. |
| `pdf_info` | `path`: SHA-256, page count, page size, CropBox, and rotation. |
| `pdf_read_text` | `path`, optional `pages`, `max_chars=50000`: embedded text. No OCR. |
| `pdf_render_page` | `path`, `page=1`, `dpi=150`, `include_image=true`: full page image. |
| `pdf_crop_region` | `path`, `page`, `bbox`, `dpi=300`, `include_image=true`: detail image. |
| `drawing_extract` | `path`, `include_strokes=false`, optional `stroke_kinds`: sheet size, views, text read from glyph outlines, and on request the classified strokes of page 1. Needs the optional extractor. |
| `freecad_*` | All tools found in upstream discovery, with the prefix. The proxy does not maintain static copies of their schemas. |

The installed FreeCAD MCP supplies 17 forwarded tools. This server adds six local tools.
For example, `execute_code` becomes `freecad_execute_code`. Its arguments do not change.
The client can add a server namespace before the tool name.

PDF results contain machine-readable `structuredContent` and the same metadata as text.
Page and detail results also contain a PNG image block for direct inspection by an agent.
A separate local image viewer is not necessary. The full PNG stays available at `artifact.path`.
The server limits large preview images. The `preview` fields give their actual dimensions and scale factor.

## Installation

Install Python 3.11 or later and Poppler with `pdftoppm`.
For `drawing_extract`, use Python 3.12 or later.
For CAD work, also install a FreeCAD MCP with a reachable FreeCAD addon.
This server does not require a GUI. It does not change the operating mode of the upstream FreeCAD server.

On Windows, run these commands from this directory:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[test]"
Copy-Item drawing2cad-mcp.example.toml drawing2cad-mcp.local.toml
```

To enable `drawing_extract`, also install the extractor into the same environment:

```powershell
.\.venv\Scripts\python.exe -m pip install -e ..\extractor
```

Without the extractor, `drawing_extract` returns the error `EXTRACTOR_UNAVAILABLE`. All other tools work.
`drawing2cad_status` shows `extractor.available` and `extractor.version`.

On Linux or macOS, use `python3 -m venv .venv` and `.venv/bin/python`.
Install Poppler separately, or configure the existing absolute path to `pdftoppm`.
`requirements-tested.txt` records the Python package versions from the test.
To use those versions, run `pip install -c requirements-tested.txt -e ".[test]"`.
The recorded test used Windows and Python 3.12. Tests on other hosts have not been done.

Set the TOML configuration:

- `[pdf]`: permitted source directories, output directory, and optional absolute Poppler path. Without that path, the server searches `PATH` for `pdftoppm`.
- `[freecad]`: set `enabled=true`, the existing MCP launcher in `command`, and its `args`. Optional fields are `env` and `cwd`. For PDF work alone, set `enabled=false`.
- `[server]`: preview limits and concurrency limits. The example contains the default values.

Relative **configuration paths** use the TOML directory as their base. PDF tool calls use **absolute file paths**.
The `.local.toml` file is specific to this computer. The portable example has no user-specific paths.

## Register with an agent

Register only this server. It starts the existing FreeCAD MCP internally.
For clients with an `mcpServers` configuration, replace the example paths:

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

Codex uses TOML for the same entry:

```toml
[mcp_servers.drawing2cad]
command = 'C:\Projekt\drawing2cad-mcp\.venv\Scripts\python.exe'
args = ["-m", "drawing2cad_mcp", "--config", 'C:\Projekt\drawing2cad-mcp\drawing2cad-mcp.local.toml']
startup_timeout_sec = 30
tool_timeout_sec = 1920
```

The example client timeout matches the local upstream timeout of 1900 seconds.
For different values, set the client timeout longer than the expected operation.
To supply only this interface, disable the existing direct FreeCAD entry.
After configuration changes, reload the MCP connection in the client.
See the [Codex configuration reference](https://learn.chatgpt.com/docs/config-file/config-reference).

To start the protocol process manually, run this command:

```powershell
.\.venv\Scripts\python.exe -m drawing2cad_mcp --config drawing2cad-mcp.local.toml
```

The process waits for an MCP client on stdin/stdout. It sends logs to stderr.
An empty console is not an error.

## Reproducible PDF procedure

1. Give only the permitted PDF to `pdf_info`.
2. Record `source.sha256`.
3. Call `pdf_read_text` for the necessary pages.
4. If a page has `status="native_text_missing"`, call `drawing_extract`. This status means that no native text was found on that page.
   The BCT drawings have no text layer. Their dimensions and labels are vector outlines.
   `drawing_extract` reads these outlines and gives positions in millimeters on the sheet.
   A `?` in a text block or a stroke of kind `unclear` is not a fact. Examine it in a detail image.
   If the extractor is not available or the PDF is a scan, read the page visually.
5. Call `pdf_render_page`.
6. Inspect the returned image.
7. Create detail images for critical dimensions, for example:

```json
{"path":"C:/Projekt/resources/Zeichnung.pdf","page":1,"bbox":[0.25,0.0,0.75,0.5],"dpi":300,"include_image":true}
```

8. Record the source hash, page, crop region, resolution, and artifact hash with the observation.
9. Compare `source.sha256` after each call. A changed source requires a new revision.

Page numbers start at **1**.
`bbox=[left,top,right,bottom]` uses **normalized values from 0 to 1**.
Its origin is the top-left corner of the displayed page after rotation.
The effective page is the intersection of **CropBox and MediaBox**.
Metadata contain the original boxes and the effective box.
The crop operation rounds left and top down to pixels. It rounds right and bottom up.
These coordinates are not CAD coordinates.

The server renders the full page before it creates a detail image.
Thus, `max_pixels` also applies to the full page during a crop call.
DPI must be from 36 to 600.
A higher DPI cannot restore missing image information from a raster source.
Each call reads its own size-limited PDF snapshot.
There is no session across documents and no automatic interpretation of drawing dimensions.

`drawing_extract` reads page 1 from the same hashed snapshot as the other tools.
Its coordinates are **millimeters on the sheet**, origin top left, y down. They are not CAD coordinates.
The extractor does not apply the drawing scale.
Without `include_strokes=true`, each view gives `stroke_count` instead of `stroke_ids`.
Measured responses (status 17.10.2026, A3 BCT drawings): approx. 3 to 5 kB without strokes, 290 to 450 kB with all strokes.
Use `stroke_kinds`, for example `["unclear"]`, to get a small subset.
The extractor supports the BCT template (A3, NX export). See the [extractor limits](../extractor/README.md).

## Behavior and limits

- PDF preparation uses pypdf for text and metadata, Poppler for raster images, and Pillow for crops and previews.
- `drawing_extract` uses the optional `drawing_extractor` package (PyMuPDF). It reads glyph outlines with templates, not with OCR.
- The server has no OCR or automatic CAD reconstruction.
- The server verifies resolved PDF paths against permitted directories, file-size limits, page limits, and pixel limits.
- The Poppler process has a timeout. That timeout does not apply to the pypdf parser or to the vector extractor.
- This server is not an isolated service for unrestricted hostile PDF inputs.
- The proxy preserves schemas, images, resource blocks, structured results, and error status.
- It is a **tool proxy**. It does not forward upstream resource lists, prompts, sampling, or elicitation.
- `freecad.connected` confirms the MCP transport. A suitable FreeCAD call is necessary to verify addon operation.
- If the upstream server is unavailable, the PDF tools stay available.
- The proxy can retain a previously discovered catalog with `catalog_stale=true`.
- Each server process runs its FreeCAD calls in sequence.
- Clients with separate server processes must coordinate access to shared CAD documents.
- The proxy does **not automatically retry** failed or canceled CAD calls.
- An operation that has started can have changed the model. Read its actual state before a retry.
- `freecad_execute_code` retains the upstream permissions.
- The PDF path restrictions do not restrict Python code that executes in FreeCAD.
- The proxy adds no AP242 or PMI capabilities and no implementation for CAD execution without a GUI.

## Tests and skill

```powershell
$env:DRAWING2CAD_PDFTOPPM = 'C:\Pfad\zu\pdftoppm.exe'
.\.venv\Scripts\python.exe -m pytest tests --basetemp tmp/tests -q
```

Without Poppler, the test suite skips image-render tests.
Without the extractor or the sample drawings in `../resources/Drawing2CAD/`, it skips the extractor sample tests.
It can skip symbolic-link tests if the operating system does not permit symbolic links.
The suite uses synthetic PDFs and a harmless MCP test process. It does not change FreeCAD models.
It tests rotation, CropBox/MediaBox, UserUnit, detail pixels, source identity, errors, transport fidelity, and cancellation without automatic retry.

The project skill is at `../skills/drawing2cad`.
Version **0.5.1** specifies this interface and the model-independent workflow in `references/drawing2cad-mcp.md`.
Create and verify the controlling dimensioned drawing before the 3D build.
Use `references/drawing-first.md` for the necessary evidence.
This is a work instruction. The server does not yet enforce it.
The CAD and AP242 adapters remain separate skill components with their own tests.

## Documentation language

Write project documentation in technical English in accordance with ASD-STE100.
Use the [language guide](../skills/drawing2cad/references/documentation-language.md) for terminology and review.
Keep exact interface text, executable examples, and historical test evidence unchanged.
