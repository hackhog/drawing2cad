# Work instructions for drawing-extractor

Deterministic vector extractor. Decision: [ADR 0003](../docs/adr/0003-vector-extractor-as-fact-base.md).

## Rules

- Geometry and facts only. Do not call a model or an external API in this package.
- Use millimeters on the sheet, with y down, in all internal data. Convert pt to mm only in `reader.py`.
- Before you add a classification rule, look at the overlays of all 9 samples
  (`uv run drawing-extract ../resources/Drawing2CAD/*/*_dwg.pdf -o out`). After the change, `tests/test_samples.py` must pass.
  Do not use rules that depend only on line width. Line width has a different meaning in each drawing.
- If a stroke is not certain, keep it `unclear`. Do not guess.
- The `*.stp` and `*.prt` files in `resources/` are verification data. Never read them in this package.

## Facts about the BCT PDFs

- NX export (`cgm2pdf`), A3, no text layer. Characters are filled paths.
- Dimension arrow: triangle (base approx. 0.9 mm, sides approx. 3.5 mm) plus parallel fill strokes in the same path.
- NX sometimes puts one arrowhead into two consecutive PDF paths. The paths are large collection paths,
  and the arrowhead is at the boundary. Example: Maschinenteil, angle dimension 25.5° (one side and the fill strokes
  in one path, the other side and the base in the next path). More frequent: the triangle in one path and the
  fill strokes in the next path (one arrow each in Befestigung, Rotation, Trägerplatte, Maschinenteil).
  Thus, arrow detection permits `path_id` ± 1, but not more.
- Section arrow: line width 0.5 mm (usually) or a large triangle (base approx. 3.75 mm).
- Center line: dashes 14.7 mm / gap 1 mm / dot 3 mm / gap 1 mm.
- Extension lines have a gap where they cross another dimension line.
- Characters: filled polygons, one glyph = one path. The bars of the cutting plane are also filled
  (quadrilateral, length ≥ 3 mm). The extractor removes them before text recognition.
- Gaps in character heights: inside a word ≤ 0.26, between words ≥ 0.35. Next to "1", subtract a margin of 0.15.
- To teach new characters: `scripts/build_glyph_templates.py dump …`, look at the contact sheets, add to `labels.json`,
  then `build`. After that, change `tests/expected_texts.json` only after a visual check of the image crops.
