# drawing-extractor

Deterministic vector extractor for technical drawing PDFs ([ADR 0003](../docs/adr/0003-vector-extractor-as-fact-base.md)).
The extractor reads the strokes from the PDF, gives each stroke a meaning, and groups the strokes into views.
It supplies **facts about the drawing** (exact coordinates), not facts about the part.

## Build and run

Prerequisite: [uv](https://docs.astral.sh/uv/). uv installs Python 3.12 if necessary.

```bash
cd extractor
uv sync --locked             # dependencies from uv.lock
uv run pytest                # sample tests are skipped if the sample drawings are missing
uv run drawing-extract ../resources/Drawing2CAD/*/*_dwg.pdf -o out
```

The extractor does not need an API key or a network connection at runtime.

## Output

For each drawing, the extractor writes these files to `out/`:

- `<part>.json`: strokes with class and geometry, views, and text blocks with the recognized text
  (`"text": "Ø3,5"`, `"angle_deg": 90` = read from bottom to top)
- `<part>_overlay.png`: the drawing in light gray, with the classes in color and the views as frames

Coordinates are in **millimeters on the sheet**. The origin is at the top left, and y points down.
The extractor does not know the scale (for example 2:1). The scale is in the title block, and a later step must read it.

| Class | Meaning |
|---|---|
| `contour` | visible body edge |
| `hatch` | hatching of a section area |
| `centerline` | dash-dot line (center line, bolt circle, center cross) |
| `hidden` | dashed line (hidden edge) |
| `dimension` | dimension line or leader line with an arrow |
| `extension` | extension line |
| `arrow` | dimension arrowhead with its fill strokes |
| `cutting_plane` | cutting plane with section arrows |
| `unclear` | not part of a view; the extractor does not guess |

## How it works

1. `reader.py`: PyMuPDF reads the paths. Bézier curves that are circular arcs become arcs.
   Connected quarter arcs become full circles. The frame and the title block (`template.py`) are removed.
   Filled paths are characters, because the PDFs have no text layer.
2. `classify.py`: rules use geometry, not line width, because line width has a different meaning
   in each drawing (the order is in the module docstring).
3. `text.py`: the characters are filled outlines of an NX font. Each character is turned into the reading
   direction, rasterized, and compared with `glyph_templates.json` ([ADR 0004](../docs/adr/0004-text-by-glyph-templates.md)).
   To build the templates again, see `scripts/build_glyph_templates.py`.
4. `views.py`: body strokes that touch each other make groups. Groups that are mostly inside each other
   are merged. The view that covers the embedded 3D image is `is_iso`.

## Limits (status 17.10.2026)

- Made for the BCT template (A3, NX export). Other templates need a different `template.py`.
- Text: only the NX font of the samples (34 characters). Unknown characters (for example "±") show as `?`,
  but the extractor can also read them as a wrong known character. The title block (scale, weight)
  uses stroke text, and the extractor does not read it yet.
- A filled glyph that the PDF stores as rectangle (`re`) path items stops the text reader with an error.
  NX writes glyphs only as polylines, but other programs can use rectangles.
- Extension lines that do not touch an arrowhead sometimes stay `contour`. Because of this,
  view frames can be a little too large (for example Welle).
- The extractor does not recognize arrowheads that are not isosceles triangles. The 9 samples do not
  contain such arrowheads. NX sometimes puts one arrowhead into two consecutive PDF paths;
  the extractor recognizes these arrowheads, but not arrowheads across paths that are farther apart.
