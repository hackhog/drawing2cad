# 26. Complete skill in agent runs, with references for each step

Date: 2026-10-19

## Status

Accepted. Replaces the decision of [ADR 0024](0024-embedded-drawing-references-and-required-drawing.md) to embed only two references.

## Context

The system prompt of an agent run contained `SKILL.md` and two references: `drawing-delivery.md` and `verification-loop.md`.
`SKILL.md` links 12 more references, for example `projection-and-measurement.md`, `draft-and-fillets.md`, and `tolerances-and-changes.md`.
The agent had no tool to open linked files, so it did not see their rules. Standalone MCP clients can read the complete skill.
The agent must always have access to the complete skill. The token use must stay low, so the agent receives a reference only when a step needs it.

## Decision

- `SKILL.md` has the section "References for each step". Its table assigns the tools of each step to the references of that step. CLI agents read the table as an instruction. The bounded client reads the same table.
- The system prompt contains `SKILL.md` only. The client supplies the references of the first step with the task.
- At the first tool request of a step, the client supplies the references of that step once, as a user message after the tool results. The model client shortens older tool results, but not text messages, so a supplied reference stays available.
- The client tool `skill_read` returns any file of the loaded skill, for example `references/ap242-adapter.md`. It uses no MCP call and does not count against the tool budget. The turn limit bounds it.
- The client loads `SKILL.md` and all reference files once at run start and records their SHA-256 values in the trace. The skill files have a limit of 256 KiB.
- The domain profile still requires `drawing-delivery.md` and `verification-loop.md`.
- The backend image and the root `.dockerignore` include the complete `references/` directory.

## Consequences

- The first model turn carries `SKILL.md` and the references of the first step: about 24 KB of skill text. Before, it carried about 25 KB with two fixed references.
- The skill text grows when the run enters a new step. A run that passes all steps carries about 86 KB of skill text in its last turns. Embedding the complete skill would carry about 104 KB from the first turn.
- A new reference file is available through `skill_read` without a code change. To supply it automatically, add it to the step table.
- A table row that names a missing reference file stops the run at start.
- The agent can skip `skill_read`. The step table makes sure that the references of each executed step arrive without a request.

## Alternatives considered

| Alternative | Reason for rejection |
|---|---|
| Embed the complete skill in the system prompt | About 25,000 tokens in each turn, most of them unrelated to the current step |
| Only a tool that reads skill references | The agent must decide to call it. A low-effort run would likely skip it. |
| Replace the references in the system prompt for each step | A changed system prompt prevents prompt caching. A reference of an earlier step is no longer available for a correction. |
