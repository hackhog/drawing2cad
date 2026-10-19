# 26. Complete skill in agent runs

Date: 2026-10-19

## Status

Accepted. Replaces the decision of [ADR 0024](0024-embedded-drawing-references-and-required-drawing.md) to embed only two references.

## Context

The system prompt of an agent run contained `SKILL.md` and two references: `drawing-delivery.md` and `verification-loop.md`.
`SKILL.md` links 12 more references, for example `projection-and-measurement.md`, `draft-and-fillets.md`, and `tolerances-and-changes.md`.
The agent has no tool to open linked files, so it did not see their rules. Standalone MCP clients can read the complete skill.
The agent must always use the complete skill.

## Decision

- `skill_text()` in `local_model_client.py` appends every Markdown file directly under `references/` to `SKILL.md`, each in a `<reference>` block. The web runner and the local client both use it.
- The domain profile still requires `drawing-delivery.md` and `verification-loop.md`. If one is missing, `skill_text()` fails.
- The complete skill text has a limit of 256 KiB.
- `SKILL.md` states that the skill is `SKILL.md` and all files under `references/`. It tells the agent to read every reference file before the first CAD tool call.
- The backend image and the root `.dockerignore` include the complete `references/` directory.

## Consequences

- Each model turn carries the complete skill: about 103 KB of prompt text, about 25,000 tokens. Before, it carried about 25 KB.
- A model deployment with a low tokens-per-minute limit waits longer for rate limits. A run can fail if one turn exceeds that limit.
- A new reference file is available to the agent without a code change.
- The skill size limit stops a run if the skill grows above 256 KiB.

## Alternatives considered

| Alternative | Reason for rejection |
|---|---|
| A tool that reads skill references | The agent must decide to call it. Older tool results are shortened to limit tokens, so a reference read early can be lost later. |
| Embed only the references of the current phase | The agent must always have the complete skill. A phase list must be maintained for each new reference. |
