# 31. Render complete drawings from contract 2.0

Date: 2026-10-20

## Status

Accepted. Replaces the rendering decision of [ADR 0029](0029-drawing-contract-2-with-projection-sheet-and-gps-data.md).
Uses the derived views of [ADR 0030](0030-views-derived-from-the-validated-model.md).
Implemented in the MCP (`drawing2cad-mcp/src/drawing2cad_mcp/sheet_layout.py`, `drafting.py`, `drawing_contract.py`).

## Context

DrawingSpec 2.0 declares isometric views, sections, sheet data, datums, and tolerance frames, and `drawing_derive_views` derives the views.
The renderer rejected this content with `render_unsupported`. Thus a drawing with an isometric view, a section, a title block,
or a tolerance frame could not be delivered.

## Decision

### One layout for validation and rendering

- `sheet_layout.py` calculates the positions of the title block, the border, the projection symbol, the tolerance frames,
  the datum symbols, the section marks, and the review list. It has no CAD imports.
- `drawing_validate` uses these positions for its checks and gives them to the renderer in `resolved.layout`.
  Thus the checked layout and the rendered layout are the same.

### Content

- Ellipses become DXF ELLIPSE entities. Each hatching becomes a DXF HATCH with the pattern ANSI31, with its angle and spacing.
- Section marks (ISO 128-3): the cutting line as a thin chain line, thick ends, arrows in the viewing direction, and the letter at each end.
  The arrows show the direction from the viewer toward the part.
- Border (ISO 5457): a frame at the sheet margin, centering marks, and, with `zone_grid`, zone numbers and letters in the margin.
- Title block (ISO 7200): 180 mm wide at the bottom-right corner, with the fields of `title_block`, the title, the units, the scales (ISO 5455),
  the part revision, and the projection symbol (ISO 5456-2). A field without a value stays empty.
  The symbol has the small end of the cone on the left. First angle puts the end view right of the cone, third angle left of it.
  A 2.0 drawing with a title block does not repeat the title and the units as free labels.
- Tolerance frames (ISO 1101): a compartment for the characteristic symbol, the value with Ø or SØ and the modifiers, and one compartment
  for each datum reference. The symbols are lines, circles, and arcs, not font characters. A leader with an arrow head goes to the feature.
- Datum symbols (ISO 5459): a filled triangle with its base along the feature tangent, a leader from its apex, and a square with the letter.
  `position` is optional. The apex points to the side of the square.
- A leader ends on its primitive: the middle of a line, the top of a circle, the middle of an arc, or the middle of the parameter range of an ellipse.
- Theoretically exact dimensions: native DXF dimensions with a frame around the value (negative DIMGAP).

### Review marks

- A tolerance frame with status `needs_review` is drawn on layer `GPS_REVIEW`: red, with dashed lines, and with the text REVIEW.
  It is not drawn as a supported frame. A frame with status `fail` stops the rendering.
- Each `unsupported_gps` item is a red text line `REVIEW <id>: <literal text>` above the title block.
- A note that looks like a geometrical tolerance gets the finding `gps_free_text` with status `needs_review`.
  Free text does not replace a structured tolerance frame.

### Checks

- The title block must fit inside the margin, and no view frame may overlap it (`sheet_overlap`).
  Each field value must fit its field (`title_block_text`).
- Tolerance frames, datum squares, section letters, and the review list must stay inside the margin and must not overlap each other or a label (`sheet_overlap`).
  The leaders of frames and datums, the cutting line, and the section arrows must not cross another sheet item or a label.
  Arrow heads and datum triangles must not overlap another sheet item or a label. A frame must not cover its own feature point.
  These defects are layout defects and give diagnostic artifacts.
- A tolerance value is shown with at most 6 decimal places. A value that the text cannot show exactly fails, so the drawing never shows a rounded value.
- A section needs the projection of its source view for its marks. Without it, the drawing fails with `section_marks`.
  This defect is missing data, not a layout defect, so it gives no diagnostic artifacts.
- The border and its zone labels are in the margin. The margin check of the other entities excludes them.

### One revision for DXF and PDF

- The renderer writes the DXF, reads it again, and renders the PDF from the file that it read.
- The PDF metadata records the part revision, the description hash, and the DXF hash. The report records the DXF hash and the counts of the sheet items.
- `render_gate` stays for content of later versions. For schema 2.0 it does not reject content.

## Consequences

- A complete-service drawing can contain an isometric view, sections, a border, a title block, and tolerance frames of the supported profile.
- Text widths are estimates. The frames and the title block use a larger factor than labels, because the text height is the cap height.
- Rendering is not ISO conformity. A reviewer must still compare the drawing with the source and the model.

## Tests

- `drawing2cad-mcp/tests/test_drawing_render_v2.py`: a flange from derived top, front, isometric, and section views renders with
  eight anchored dimensions, two hatched cut surfaces, a cutting line with arrows and letters, a border with zones, a title block, a datum,
  two supported frames, one frame with a review mark, and one unsupported GPS line; the PDF metadata names the hash of the DXF file;
  a free-text tolerance gets a finding; a view on the title block and a long field value fail.
- `drawing2cad-mcp/tests/test_drawing_contract_v2.py`: the complete 2.0 example renders.
