# 32. Independent verification of the final drawing PDF

Date: 2026-10-20

## Status

Accepted. Uses the drawing contract of [ADR 0029](0029-drawing-contract-2-with-projection-sheet-and-gps-data.md),
the derived views of [ADR 0030](0030-views-derived-from-the-validated-model.md), and the rendering of [ADR 0031](0031-render-complete-drawings-from-contract-2.md).
Implemented in the MCP (`drawing2cad-mcp/src/drawing2cad_mcp/pdf_verifier.py`, `drawing_verification.py`, `adapters/poppler.py`, `adapters/tesseract.py`).

## Context

The renderer checks its own entities before it writes the DXF and the PDF. That check does not examine the stored PDF bytes.
A defect in the PDF backend, a changed file, or a stale binding can give a PDF that differs from the validated drawing.
The PDF of the renderer contains text as outlines, so text extraction gives no text.

## Decision

### Tool and workers

- The domain tool `drawing_verify` verifies stored PDF bytes. It takes `artifact_id` and `expected_sha256` for the PDF of the current drawing,
  or `source_id` and `expected_sha256` for a supplied PDF without a binding.
- Two fresh restricted workers do the work. The sandbox permits no new process, so each worker calls one fixed program in its own process:
  - `render_pdf_poppler` replaces the worker with Poppler `pdftoppm` (execve). It renders each page at 300 dpi in gray. The parent collects the pages.
    A missing or skipped page fails.
  - `verify_drawing_pdf` reads the PDF, the raster, and the bound STEP candidate. It calls Tesseract 5 through its C API (ctypes)
    with the Debian language data `eng` and `deu`.
- The service checks the hash and the binding before the workers start. The expectations come from a new validation of the stored drawing,
  not from the DXF and not from the entity list of the renderer.

### Layers and rules

Each finding has a rule ID, a status (`pass`, `fail`, `needs_review`, `not_tested`), a severity, the page, a sheet region in mm,
the feature, the expected and observed values, and the evidence.

| Layer | Rules |
|---|---|
| PDF integrity and binding | `PDF-INTEGRITY-01` hash, `PDF-STRUCT-01` to `-04` open, one page, no rotation, page box, `PDF-BIND-01` revision, description, and DXF hash in the metadata |
| Raster | `RENDER-01` each page rendered at the fixed size, `RENDER-02` not blank, `RENDER-03` no content at the page edge |
| Views | `VIEW-REQ-01` isometric view, `VIEW-REQ-02` section view, `ISO-01` isometric projection |
| Model | `MODEL-01` visible, `MODEL-02` hidden, and `MODEL-03` section edges of the model projected again: each edge must be present in the raster; `MODEL-04` each drawn primitive lies on a model edge |
| Dimensions | `DIM-01` value read from the raster, `DIM-02` anchor on the model, `DIM-03` each round model feature has a dimension, `DIM-04` value agrees with the model |
| Sheet | `UNITS-01` units, `REV-02` part revision, `TEXT-01` title block fields, `TEXT-02` view labels, `SEC-01` section letters |
| GPS | `GPS-01` frame present, `needs_review` outside the profile; `GPS-02` value; `GPS-03` REVIEW mark; `GPS-04` unsupported GPS lines |
| Not tested | `STYLE-01` line types and widths, `REVIEW-01` identified review |

### Text recognition

- OCR reads each expected text in its expected region. The verifier tries the expected text directions, because the renderer turns
  round-dimension values along their leaders. Text in a title block field or a frame compartment is read inside the cell borders.
- A critical value (dimension, tolerance value, units, revision, section letter, review mark) must contain each expected number exactly.
  A diameter sign can be read as one confusable character before the value. An unreadable critical value fails.
  It never passes because the recognition gave no text.
- Other texts pass at a similarity of at least 0.8.
- OCR is never the only test: the model, the raster coverage, and the PDF structure are separate layers.

### Results and validity

- The worker writes `verification-report.json` (schema 1.0) and `verification-preview.png` with the regions of the failed and review findings.
  The report records the verifier version, the thresholds, the tool versions, the binding, and the untested rules.
- The overall status is `fail` if a rule fails, `needs_review` if a rule needs review, and `pass` otherwise. `not_tested` rules are listed. They never count as a pass.
- The drawing state stores the verification record with its binding: part revision, description, build candidate, drawing, and PDF hash.
  `drawing_read` reports `current` or `stale`. A changed PDF file, a new drawing, a new build, or a part change makes the record stale.
- A PDF without a binding gets `fail` for the required views, because no bound drawing declares them, and `not_tested` for the model and the texts.
- A result is a result of the profile `drawing2cad-verify-1`. It is not ISO conformity and not a manufacturing release.

## Consequences

- The MCP image contains `libtesseract5`, `tesseract-ocr-eng`, and `tesseract-ocr-deu`.
- The model projections of the verifier and of `drawing_derive_views` use the same hidden-line code. The verifier derives them again from the
  bound STEP, but a defect of that code can affect both. The raster comparison is independent of it.
- A view without a projection (DrawingSpec 1.0) has no model-bound coordinates. Its model rules are not run.
- OCR thresholds are fixed values of this profile. A new font or a new text size can need new thresholds and a new profile revision.

## Tests

- `drawing2cad-mcp/tests/test_pdf_verification.py`: the flange drawing passes each layer (status `needs_review` because of a frame outside the profile);
  an additional model hole, larger bolt holes, a larger bore, a moved bolt hole, and a deeper blind bore give findings;
  a removed dimension, wrong units, content at the page edge, a blank page, and malformed bytes fail after the final-byte rendering;
  changed bytes and a stale revision fail; a PDF without a binding fails the required views and does not test the model;
  the supplied flange PDF fails the required views when `DRAWING2CAD_FLANGE_PDF` names it; the verification runs in the verified sandbox.
- `drawing2cad-mcp/tests/test_drawing_verification_service.py`: binding, the stored record, stale status after a PDF change and a new build,
  removal after a part change, hash and target checks, and the unbound source mode.
