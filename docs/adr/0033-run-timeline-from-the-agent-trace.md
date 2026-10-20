# 33. Run timeline from the agent trace

Date: 2026-10-20

## Status

Accepted. Uses the agent runner of [ADR 0018](0018-agent-runner-in-the-web-backend.md) and the UI structure of [ADR 0015](0015-web-ui-on-tanstack-shadcn-with-service-adapter.md).
Implemented in `app/backend/src/drawing_demo/agent/timeline.py` and `app/frontend/src/components/run/TimelinePanel.tsx`.

## Context

The run page shows the result of a run in four tabs: parameters, review, results, and notes.
These tabs do not show the process of the agent. A user cannot see:

- which tool the model called, with which arguments, and what the MCP server returned,
- which tool calls failed, with which error code, and which corrections the agent loop sent,
- where the time went: model inference or MCP and CAD calls.

The agent trace of each run has these data. `drive()` writes one JSON file for each event (`<sequence>-<kind>.json`).
The trace is large: each model request repeats the complete conversation with all images, and tool responses contain base64 images.
The run files show the raw trace, but users who do not know the skill and the MCP cannot read it.

## Decision

- The web backend condenses the trace into steps. `GET /api/runs/{run_id}/steps` returns a bounded list of steps and the final loop summary.
  `GET /api/runs/{run_id}/steps/{sequence}` returns the full arguments, the result text, the problem, and up to four images of one step.
- A step is a skill reference supply, a model turn, a tool call, or a corrective instruction. A tool step joins the tool request with its response.
- The backend never reads model requests. It reads only the event files that it presents. Texts in the step list are shortened.
- For a failed tool call, the backend names the most specific problem: a service error, then a build error with its feature, then the first validation defect.
  This is presentation only. The backend adds no CAD, drawing, or release rule.
- The run page opens a new first tab "Timeline". It shows the end of the loop in plain words, the four layers of a run (skill, agent loop, MCP server, CAD worker and release),
  a time bar (width = duration), the problems grouped by tool and error code, and a step list with a detail pane.
- The UI polls the steps every 2 s while the run is active. The job status is part of the query key, so a run that ends between two polls shows its final steps.
- The other four tabs do not change.

## Consequences

- A user can see during and after a run how the skill, the agent loop, and the MCP work together, and where the run had problems.
- The step list of a run with 45 tool calls is about 40 KB. Images load only with the details of one step.
- The step format depends on the trace format of `drive()`. A change of the trace format must also change `timeline.py` and its tests.
- A simulated run of the fixture service has no trace and shows no steps.
