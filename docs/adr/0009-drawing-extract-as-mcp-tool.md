# 9. Vector extractor as the MCP tool `drawing_extract`

Date: 2026-10-17

## Status

Proposed. Uses ADR 0003 (vector extractor) and ADR 0004 (text).

Superseded by [ADR 0012](0012-vector-analysis-in-mcp.md) for packaging, status, process isolation, and timeout behavior.
The `drawing_extract` call remains available with the same parameters.
The former package paths and test results below describe the original implementation only.

## Context

The agent does the CAD work through `drawing2cad-mcp` only (AGENTS.md).
Before this decision, the server supplied two sources of drawing content: `pdf_read_text` and rendered images.

The BCT drawings have no text layer. An end-to-end test with a real stdio MCP client (17.10.2026) gave this result:

| Drawing | `pdf_read_text` | `drawing_extract` |
|---|---|---|
| `Maschinenteil_dwg.pdf` | `native_text_missing`, 0 characters | 5 views, 33 text blocks (for example `Ø100`, `A (2:1)`, `nicht bemaßte Radien R=1`), 3,707 classified strokes |
| Demo drawing from `Flansch_dwg.pdf` | `native_text_missing`, 0 characters | 4 views, 20 text blocks, `38?1` marked with `?`, 9 strokes of kind `unclear` |

Thus, the agent got all dimensions only from images. It had to estimate positions and values from pixels.
The extractor (ADR 0003) has exact vector coordinates and the read text, but the agent could not use it through the MCP.

## Decision

We add the local tool `drawing_extract` to `drawing2cad-mcp`.

- Parameters: `path`; `include_strokes` (default `false`); `stroke_kinds` (filter, only with `include_strokes=true`).
- `PdfService` does the path check, the size limit, and the SHA-256 snapshot, as for the other PDF tools.
  The extractor reads a temporary copy of that snapshot. Thus, the result agrees with `source.sha256`.
- The call runs in a worker thread and uses the same `pdf_concurrency` limit as the other PDF tools.
- The result is the extractor JSON (`drawing_extractor.export.to_dict`). `source` is replaced by the server source metadata.
- Without strokes, each view gives `stroke_count` instead of `stroke_ids`.
  The stroke ids were 75 % of the response and refer to nothing without the strokes.
- The extractor is an optional dependency. If the package is not installed, the tool returns `EXTRACTOR_UNAVAILABLE`.
  All other tools work. `drawing2cad_status` shows the extractor version.

The review flags of the demo app (`app/src/drawing_demo/review.py`) are not part of this tool.

## Consequences

**Positive:**
- The agent gets exact sheet coordinates and read text instead of pixel estimates.
- Unknown characters (`?`) and `unclear` strokes show the agent where to examine a detail image. This decreases visual work and model cost.
- Same source identity and the same limits as the other PDF tools.

**Negative / trade-offs:**
- With all strokes, the response is large (approx. 290 to 450 kB for an A3 drawing). Strokes are off by default.
- The extractor supports only the BCT template (A3, NX export) and page 1. Other drawings can give wrong classes.
- The server has a timeout for Poppler but not for the extractor.
- A fresh installation needs a second install step (`pip install -e ../extractor`). The extractor uses `uv_build`; pip downloads it as a build backend.
- The extractor needs Python 3.12. The server alone needs Python 3.11.
- `stroke_kinds` in the server schema is a copy of `drawing_extractor.Kind`. A test compares both lists.

## Considered alternatives

| Option | Assessment |
|---|---|
| Keep `pdf_read_text` and images only | No exact data. On BCT drawings, the text tool gives nothing |
| Separate MCP server for the extractor | A second registration and a second path check. AGENTS.md permits only `drawing2cad-mcp` |
| Mandatory dependency of `drawing2cad-mcp` | Python 3.12 and PyMuPDF for all users, also for PDF work without the extractor |
| Extractor reads the path directly | Simpler, but the file can change between hash and extraction |
| Review flags in the tool | Useful, but the logic is in the demo app. To move it to `drawing_extractor` first is a separate decision |
