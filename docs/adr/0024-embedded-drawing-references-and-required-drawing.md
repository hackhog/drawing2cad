# 24. Embedded drawing references and a required drawing

Date: 2026-10-18

## Status

Accepted.

## Context

Web run `run_b582d739…` released a STEP with a drawing that showed only a top view of the base. The arm, rib, window, and clamp were missing.
The trace showed three causes:

- The system prompt contained `SKILL.md` only. Its rules for complete drawings live in `references/drawing-delivery.md` and `references/verification-loop.md`. The agent has no tool to open linked files, so it never saw them.
- The prompt called drawings untested and told the agent to release the STEP if the drawing failed. The user message did not mention a drawing.
- The agent rejected its own drawing in `drawing_review` and called `export_step` next, with 27 of 45 tool requests left.

## Decision

- In the domain profile, `skill_text()` in `local_model_client.py` appends `drawing-delivery.md` and `verification-loop.md` to `SKILL.md`, each in a `<reference>` block. The web runner and the local client both use it.
- The domain prompt makes the complete dimensioned drawing a required deliverable. After a rejected `drawing_review`, the agent corrects and reviews the drawing again. It calls `export_step` only after an accepted review, or when the remaining budget cannot fit another drawing attempt plus the export.
- The user message of a domain run asks for the drawing.
- `export_step` still does not gate on the drawing. A run that runs out of budget still releases the validated STEP and reports the drawing status.
- The backend image and its `.dockerignore` include the two reference files.

## Consequences

- Each model turn carries about 16 KB more prompt text, about 4,000 tokens.
- Drawing attempts use more of the tool budget, so runs can take longer.
- Other references stay unavailable to the agent. A new reference that the agent needs must be added to `DOMAIN_SKILL_REFERENCES`.
- Drawing views remain hand-written by the agent. Projecting views from the solid is a separate decision.

## Alternatives considered

| Alternative | Reason for rejection |
|---|---|
| A tool that reads skill references | The agent must decide to call it; a low-effort run would likely skip it, and each call uses budget |
| Embed all references | About 90 KB per turn, most of it unrelated to the drawing |
| Gate `export_step` on an accepted drawing | A run without an accepted drawing would deliver no STEP at all |
