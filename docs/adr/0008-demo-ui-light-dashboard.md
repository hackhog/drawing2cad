# 8. Demo UI: light dashboard with overview page, guided sequence kept

Date: 2026-10-17

## Status

Accepted. Replaces the visual design of ADR 0007. The sequence and the batch upload of ADR 0007 stay valid.

## Context

ADR 0007 selected the "pitch story" draft and rejected a tile dashboard (draft D), because a dashboard does not tell a sequence.

On 2026-10-17, the user gave a screen recording of a light SaaS dashboard as the style reference:
app window with window dots, sidebar with icons, white tiles (small capital label, large number,
change in green or red), one highlighted tile in cream/orange, one tile with a number/gauge switch,
cards with pill badges, a change list with dot, title, subtitle and time on the right, floating notifications,
and segmented tabs in the page header.

## Decision

The UI uses this style. It does not use names, logos, or content of the reference. Mapping to Drawing2CAD:

| Reference | Drawing2CAD |
|---|---|
| Sidebar navigation | *Overview* and the batch of uploaded PDFs. The selected item has a peach highlight |
| "Dashboards" page | **Overview** page for the full batch: tiles *drawings*, *explained* (number/gauge), *texts read*, *to review* (highlighted if items are open), and a table with one row for each drawing. A click opens the drawing |
| Segmented tabs | The sequence as tabs directly above the sheet: 1 Drawing · 2 Recognized · 3 Review · 4 3D model "soon" |
| Chart card | "Drawing" card with the sheet, an explanation sentence and "Next" below it |
| Change list | "Review" card: review flags with dot, title, type, sheet position |
| Notifications | A toast for each drawing that was read (duration, number of open items) |

The guided sequence stays: the steps control what the sheet shows. Thus, the dashboard also tells the sequence,
which was the objection to draft D in ADR 0007. Font: Plus Jakarta Sans, served locally (OFL).

Addendum 2026-10-17 (1): the sequence was first in the sidebar. This was not intuitive, because the steps change only the sheet
but were far from it. The steps are now tabs on the item that they control. The sidebar selects only *which* drawing.

Addendum 2026-10-17 (2): the tiles were first above the sheet and took height from it. They also describe the batch more than
one drawing. Thus, there are two pages (`<body data-view>`): *Overview* (tiles and table, start page, updates while the PDFs are read)
and *Drawing* (only the sheet and the review list; the key numbers of the drawing are in the header).

## Consequences

**Positive:**
- The tiles show the performance of the extractor at a glance (for example 100 % explained). This helps "Solution & Demo".
- Batch and sequence are visible at the same time. Changing between drawings does not take space from the sheet.
- No change to the API or to the stateless design. Only `static/` changes.

**Negative / trade-offs:**
- The sheet area is a little smaller than in the pitch story (review list on the right).
- The look is different from the hackathon brand (navy/neon yellow).

## Considered alternatives

| Option | Assessment |
|---|---|
| Keep the pitch story (ADR 0007) | Replaced by the user with the style reference |
| Dashboard without steps (draft D only) | Loses the sequence that the pitch needs |
