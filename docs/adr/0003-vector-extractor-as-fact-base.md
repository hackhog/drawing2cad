# 3. Deterministic vector extractor as the fact base of drawing analysis

Date: 2026-10-16

## Status

Accepted. Extended by ADR 0004 (text).

The separate package and CLI outputs are superseded by [ADR 0012](0012-vector-analysis-in-mcp.md).
Current analysis code is in `drawing2cad-mcp/src/drawing2cad_mcp/vector/`.
The original decision and observations below remain historical evidence.

## Context

The input of the pipeline is the drawing PDFs. An analysis of all 9 files showed:

- They are single-page A3 PDFs from Siemens NX (export with `cgm2pdf` and PDFlib).
- The geometry is real vector paths (Flansch: approx. 3,600 paths, 9,500 line segments, circles as Bézier curves).
- There is no text layer and there are no fonts. Dimension values, section labels, and the title block are drawn as paths.
- The only embedded image is a JPEG with the shaded 3D view.

A vision model reads drawings well qualitatively (which views, sections, and features exist).
Quantitatively, it is not reliable: it connects dimensions to wrong lines, misses positions without dimensions, and invents values.
Each model call also costs team budget.

## Decision

We build a deterministic vector extractor in Python (PyMuPDF). It supplies the fact base for all subsequent steps,
and these steps are checked against it.

Scope of version 1:

1. Read primitives from the PDF: lines, arcs, circles, fills, with line width and line type.
2. Remove the frame and the title block.
3. Classify the primitives with rules: contour, thin line (dimension, center, and hatch line), dimension arrow, character stroke, unclear.
4. Group the contours by position into views.
5. Write JSON plus an overlay PNG for each drawing for visual checks.

Not in scope: reading text (added later by ADR 0004), relations between views, 3D reconstruction.
These are separate components that use the extractor.

The extractor supplies facts about the **drawing**, not about the **part**. Rules interpret the meaning of the lines.
If the rules cannot classify a stroke with certainty, the result marks it as "unclear". The extractor does not guess.

## Consequences

**Positive:**
- Exact coordinates instead of estimated pixel values. Measured length × scale can be compared with the read dimension value.
  This gives confidence values and review flags.
- Deterministic, no model costs, easy to test. This helps the code evaluation by the jury AI.
- Clear separation between fact (geometry) and interpretation.

**Negative / trade-offs:**
- The classification rules are made for the BCT NX export. Other CAD exports (other line widths, a real text layer,
  scanned drawings) need changes or an image fallback.
- An additional component with development effort before a 3D result is available.

## Considered alternatives

| Option | Assessment |
|---|---|
| Vision model only, on the rendered image | Fast, but dimensions are not reliable and cannot be checked. Costs budget for each run |
| Raster image with classic image processing (OpenCV, Hough) | Discards the exact vector data. Less accurate for the same effort |
| PDF → DXF (Inkscape/pstoedit) and DXF tools | Gives the same primitives, but no added value and one more system dependency in the build |
| Existing drawing readers (eDOCr2, Werk24) | Made for text and dimensions in raster images, or commercial. Could add the text part later, but do not replace the geometry part |
