# 19. Review flag decisions in the domain service

Date: 2026-10-18

## Status

Proposed. Builds on [ADR 0013](0013-vector-analysis-in-mcp.md), [ADR 0016](0016-shared-domain-service-and-drawing-delivery.md),
and [ADR 0018](0018-agent-runner-in-the-web-backend.md).

## Context

The vector analysis (`drawing_extract`) classifies each stroke with deterministic rules. A stroke that no rule explains gets
the class `unclear`. A text with an unknown glyph contains `?`. The web backend made review flags from these results.
The flags were display only: a user could not record what a flag means, and agent runs did not get this knowledge.

On 2026-10-18, all 22 drawings in `resources/Drawing2CAD/` went through the analysis. The 9 original NX drawings have no flags.
Twelve drawings from other templates have 183 flags. Most flags are drawing elements that the rules do not know:
frame zone marks, table and title block lines, leaders, pitch circles, tangent edges, and hatching in thin sections.
The analysis profile uses fixed frame and title block coordinates of the NX A3 template.
Some flags hide dimensions, for example rotated diameters and stacked tolerances.

ADR 0018 keeps storage and release rules out of the web adapter. Run notes are stored in the domain service for this reason.

## Decision

- **Flags in the domain service:** `drawing2cad_mcp.source_flags` makes the flags from the analysis of a source page.
  Each flag has a stable ID (`views`, `strokes-<first stroke ID>`, `text-<text block ID>`). The ID is stable for the same
  source bytes and analysis version. The domain service keeps the flags of recent pages in memory, because the source bytes do not change.
- **Decisions:** a human reviewer can ignore a flag, assign a stroke class to unclear strokes, or correct an unreadable text.
  An optional note explains the flag to the developers. The stroke classes include the analysis classes and five classes that the
  analysis does not know yet (`frame`, `table`, `leader`, `pitch_circle`, `tangent_edge`).
  The domain store keeps one decision for each source page and flag, with the flag, its stroke geometry, the source SHA-256,
  and the analysis version. Deleting a source deletes its decisions.
- **Tools:** `source_flags_read` (flags with decisions), `source_flags_decide` (record or reopen a decision), and
  `source_flags_export` (all decisions of the principal as labeled feedback). The agent loop permits only `source_flags_read`.
  The agent applies decisions as user input and records values from them as user decisions, not as source dimensions.
- **Web adapter:** the analysis response keeps the flags without decisions. `GET`/`PUT /api/sources/{id}/flags` and
  `GET /api/feedback` pass the tools through and add German messages for the UI.

## Consequences

**Positive:**
- A user decision reaches every MCP client and every new agent run, not only web runs.
- The feedback export gives the developers labeled examples for missing stroke classes and glyphs, with geometry,
  without the PDF. A decision without a current flag shows that a new analysis version explains the location.

**Negative:**
- Flag IDs depend on the analysis version. After a rule change, old decisions can lose their flag. They stay in the export
  and appear as `decisions_without_flag`.
- A decision on a corrected text is not checked against the drawing. The agent must compare it with the source image.
- The first flag read of a page runs a second analysis in the domain service, in addition to the web analysis.
