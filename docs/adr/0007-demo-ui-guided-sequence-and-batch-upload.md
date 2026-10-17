# 7. Demo UI: guided sequence ("pitch story") with batch upload

Date: 2026-10-16

## Status

Accepted. The visual design is replaced by ADR 0008 (2026-10-17). The sequence and the batch upload stay valid.

## Context

The demo app (ADR 0006) had four design drafts in the same UI, with a switch:
A · Hackathon (navy/neon yellow, dark), B · Engineering (dense CAD tool with layers and status bar),
C · Pitch story (guided steps Drawing → Recognized → Review → 3D model) and D · Workshop (calm operations dashboard with tiles).

Constraints:

- The pitch is 5 minutes. "Solution & Demo" is the largest pitch criterion with 17.5 %. The UI must tell the story
  "old drawing → recognized in a traceable way → unclear items marked, not guessed → 3D model" without explanation.
- An AI evaluates code and architecture for 50 % of the score. A switch with three unused drafts is dead code.
- BCT has a stock of drawings, not one drawing. The demo must show that the sequence works for a batch.

## Decision

Draft C is the only UI. A, B, D, the switch, and all items that were visible only there are removed.

Several PDFs can be uploaded at once. The queue is in the browser: each file is a separate request to the existing
`POST /api/extract`, with a maximum of 2 at the same time. Each PDF shows its status. A click changes the shown drawing.
The current step stays the same.

## Consequences

**Positive:**
- One UI, one CSS without draft prefixes, less code for the evaluation.
- The API does not change and stays stateless. PDFs are not saved. No batch endpoint, no job store.
- A defective file does not stop the batch. It is marked.

**Negative / trade-offs:**
- Results are only in browser memory (including the page image as a data URI). For approx. 10–20 drawings this is not a problem.
  Hundreds of drawings would need a server-side job store, which is against the stateless design (ADR 0006).
- The parallelism (2) is an assumption about the container. It is not measured against the CPU of the jury computer.

## Considered alternatives

| Option | Assessment |
|---|---|
| A · Hackathon | Strong brand, but the dark table takes attention from the sheet. No guided sequence |
| B · Engineering | Good for experts, too dense for a 5-minute pitch |
| D · Workshop (dashboard) | Calm and clear, but a dashboard does not tell a sequence |
| Batch endpoint `POST /api/extract-batch` | One long request without intermediate status, or a job store with polling: more code and state without value for the demo |
| Uploads strictly one after the other | Simpler, but 9 drawings take noticeably longer. The thread pool can do 2 in parallel |
