# 4. Read text by glyph templates instead of OCR or a vision model

Date: 2026-10-16

## Status

Accepted. Extends ADR 0003, which excluded text.

## Context

The vector extractor (ADR 0003) knew the position of the text blocks, but not their content.
With read text (dimension values, scale, section labels), the JSON alone is sufficient to build the model.
Without text, a model must also interpret the image.

The BCT PDFs have no text layer. Each character is a filled outline made of polygons, always in the same NX font.
Text is horizontal, vertical, or oblique (parallel to the dimension line).

## Decision

The extractor reads text itself, by comparison with templates of the glyph outlines:

1. Remove the filled bars of the cutting plane (quadrilateral, long side ≥ 3 mm) before text recognition.
2. Group characters into blocks. The reading direction comes from the position of the characters.
   For a single character, it comes from the nearest dimension line.
3. Turn each character into the reading direction, rasterize it to 16×16, and add its position relative to the base line and its height.
4. Compare with labeled templates (`glyph_templates.json`, 122 templates, 34 characters). Both directions on the axis are tried.
   The better one wins. If the result is equal, DIN 406 applies.
5. Spaces come from measured gap widths.

The templates are made once with `scripts/build_glyph_templates.py`: cluster the characters of all 9 samples, name the groups,
write the templates. Characters that are not recognized with certainty show as `?`. The extractor does not guess.

## Consequences

**Positive:**
- All 206 text blocks of the 9 samples are correct (each checked against image crops of the drawing),
  including Ø, decimal comma, °, "5x45°", and "A (2:1)".
- Deterministic, no API key, no system dependency, no team budget. The full extraction takes approx. 0.35 s per drawing.
- The JSON contains geometry and meaning together.

**Negative / trade-offs:**
- Applies only to this NX font. Another CAD system or a scan needs new templates or a fallback (OCR or vision model).
- The extractor does not know characters that are not in the samples (for example "±", "H7", tolerances).
  They show as `?`, or the extractor reads them as a similar known character, until templates are added.
  A test with a drawn "±" gave `?`, `t`, or `2`, depending on its proportions.
- The title block (scale, weight) uses stroke text (polylines instead of filled outlines). The extractor does not read it yet.

## Considered alternatives

| Option | Assessment |
|---|---|
| Tesseract OCR on the rendered image | System dependency in the build, weak for rotated text and Ø |
| Vision model for each drawing | Costs budget for each run, not deterministic, needs a key |
| eDOCr2 | Heavy ML dependencies for a problem that has an exact solution here |
