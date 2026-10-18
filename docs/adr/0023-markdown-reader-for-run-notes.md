# 23. Markdown reader for run notes

Date: 2026-10-18

## Status

Accepted.

## Context

The agent writes its run report into the run note as Markdown: headings, bold values, lists, and a table of artifact IDs.
The Notes tab showed this text only in a text field, so the report read as raw Markdown syntax.
The note is also a pitch screenshot, and a readable report shows the result better than the source text.

## Decision

- The Notes tab shows the note as rendered Markdown. An Edit button opens the source in the text field; Preview returns to the rendered view.
- An empty note opens in the editor. While the run is active, the note stays read-only.
- Rendering uses `react-markdown` with `remark-gfm` for tables and task lists, both pinned to exact versions.
- Raw HTML in the note is not rendered. `react-markdown` escapes it by default, so a note cannot inject markup.
- The styles live in `app/frontend/src/index.css` under `.markdown` and use the theme tokens of [ADR 0015](0015-web-ui-on-tanstack-shadcn-with-service-adapter.md).

## Consequences

- The `Markdown` component can also render other agent texts, for example the report in the Review tab.
- The frontend has two more runtime dependencies.

## Alternatives considered

| Alternative | Reason for rejection |
|---|---|
| Own Markdown parser | Tables and nested lists are error-prone; no gain for a demo |
| `marked` with `dangerouslySetInnerHTML` | Needs a separate HTML sanitizer |
| `@tailwindcss/typography` | One more build plugin for a single text block |
