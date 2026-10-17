# 19. Review measurements in the web backend for the benefit figures

Date: 2026-10-18

## Status

Proposed. Builds on [ADR 0015](0015-web-ui-on-tanstack-shadcn-with-service-adapter.md) and [ADR 0018](0018-agent-runner-in-the-web-backend.md).

## Context

The overview shows what the CAD runs delivered: models, released models, dimensions from the drawing, and run time.
A time saving needs two more values that no run contains:

- the time that a person uses to review the flagged items of a drawing,
- the time that a manual rebuild of the part would take.

The second value is an estimate. A drafter (for example, from BCT) can give a better estimate than the team.
Every figure must show if it is measured, calculated, estimated, or assumed, so that a reader can check it.

## Decision

- **Measurement:** step 3 "Prüfen" starts a stopwatch when it opens. "Prüfung abgeschlossen" stops it. Then the UI asks once
  who reviewed (drafter, guest or jury, team) and how long a manual rebuild would take (fixed answers from 30 min to 1 day).
  The user can save the review time without an estimate.
- **Storage in the web backend:** `POST /api/sources/{id}/measurements` stores one record per review in
  `DRAWING2CAD_DATA_DIR/web-measurements/<source_id>.json`. `GET /api/measurements` lists all records.
  Deleting a source deletes its measurements. The measurements are web-adapter data like the run records.
  They are not domain data, so the domain service and the MCP do not change.
- **Calculation in the UI:** `lib/benefit.ts` calculates the median review time, the mean estimate, and the saving
  (estimate minus median machine time minus median review time, for each drawing with a STEP model of the current revision).
  Without a measured machine time and review time, the UI shows no saving.
- **Assumptions:** the hourly rate and a fallback manual time are settings of the browser (`localStorage`).
  The fallback applies only while no estimate exists. The key figures dialog marks it as an assumption.
- **Export:** the key figures dialog shows one sentence, a bar comparison, the origin of each figure, and all measurements as CSV.

## Consequences

- The pitch can use estimates from drafters instead of an estimate from the team.
- A review that the user leaves open (another tab, a break) gives a too-long time. The median limits the effect of single
  long values. The service rejects review times above 24 hours.
- Simulated runs give machine times of a few seconds. The dialog states that simulated figures are not for the pitch.
- Measurements have no user identity, because the demo deployment has no login.

## Alternatives considered

| Alternative | Reason for rejection |
|---|---|
| Only `localStorage` | Values stay in one browser profile and get lost with it. The CSV of a stand computer would be incomplete |
| Run notes of the domain service | A note belongs to a part run. A review happens before a run and also without one |
| A fixed manual time in the pitch | Not traceable. The jury cannot check it |
