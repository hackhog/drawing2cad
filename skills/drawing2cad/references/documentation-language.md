# Documentation language

Use technical English in accordance with ASD-STE100 for all documentation that this project creates or updates.
The reference edition is Issue 9, dated 2025-01-15.
Use the [official standard](https://www.asd-ste100.org/assets/files/ASD-STE100_ISSUE9.pdf), including its rules and dictionary.
This project guide does not replace the standard.

## Scope

Apply the language rule to README files, skill instructions, reference guides, technical plans, and new reports.
Apply the rule to new code comments, docstrings, tool descriptions, and architecture decision records.
Keep user-interface text in its specified product language.
Keep original drawings, source quotations, measured data, file paths, identifiers, and schema fields unchanged.
Keep verified reference code and records from completed runs unchanged.
If an English account of a historical run is necessary, create a separate report with a reference to the original record.
Keep project records outside the reusable skill package. Do not link project data from this skill.
If a skill revision removes project-specific content, preserve its original evidence separately.
Revalidate changed adapter code. Do not apply old code hashes to changed blocks.

This rule applies to documentation. It does not change the user's language for normal conversation.

## Authoring rules

1. Use approved words with their approved meanings and parts of speech.
2. Use consistent technical nouns and technical verbs for CAD and software operations.
3. Write direct instructions in the imperative form. Use the active voice.
4. Put a condition before the action when the reader must know the condition first.
5. Give one instruction in each work step. Keep descriptive information separate from instructions.
6. Limit procedural sentences to 20 words. Limit descriptive sentences to 25 words.
7. Use American English spelling. Keep necessary names, units, and literal interface text unchanged.
8. Use `check` as a noun, for example, "do a check". Do not use it as a verb.

The [official Issue 9 text](https://www.asd-ste100.org/assets/files/ASD-STE100_ISSUE9.pdf) defines word categories, sentence limits, and word-count rules.
Use its dictionary to resolve an uncertain word. Do not invent an approved meaning.

## Project terms

These technical nouns identify project concepts. They do not extend the approved general dictionary.

| Term | Project meaning |
|---|---|
| dimensioned technical drawing | An editable drawing sheet with dimensions and the necessary views, sections, and notes. |
| controlling drawing | The verified drawing revision used for design requirements and model comparison. |
| part description | The versioned JSON source of parameters, ordered features, evidence, and review data for the M1 prototype. |
| model contract | Declarative data that specify sources, parameters, relations, operations, PMI, review data, and tests. |
| fixed contract | A model contract with a recorded revision and hash. Changes require a new revision. |
| operation graph | The directed acyclic graph of construction operations and their dependencies. |
| native feature | An editable object in the CAD application's construction history. |
| candidate | An output that has not passed all tests necessary for release. |
| master file | The current released file that has passed the necessary tests. |
| STEP-only reconstruction | Reconstruction that uses STEP as its only source of model content. |
| boundary representation (BREP) | The faces, edges, and vertices that define the model boundary. |
| product and manufacturing information (PMI) | Dimensions, tolerances, and other product data associated with model geometry. |
| review register | The record of derived values, assumptions, unresolved details, and conflicts. |
| review marker | A visible reference to a review-register entry. It is separate from original PMI. |
| run manifest | The record of inputs, outputs, hashes, tool versions, phase results, and the next action. |
| source evidence | A recorded observation or quotation from a permitted source. |
| historical MCP proxy | The removed component that forwarded tool calls to an external CAD server. |

Use exact software names when necessary: `build123d`, `OCP`, `OpenCascade`, `FreeCAD`, `STEP AP242`, and `drawing2cad-mcp`.
Define a new technical term at first use. Use the same term for the same concept in subsequent text.
Do not rename a code identifier to meet a prose rule.

## Review and evidence

First, compare the revised text with the source requirements.
Make sure that conditions, prohibitions, limits, units, and evidence status have not changed.
Then, review the prose against the applicable writing rules and dictionary.
Record necessary technical terms and unresolved language questions.

Test local links after changes to headings or file paths.
Compare recorded hashes for reference code, source data, and historical fixtures.
A link test or a sentence-length scan does not prove STE conformity.

Record the actual review scope. Do not state full conformity after only translation or automated checks.
The current language conversion has no full dictionary-conformity result.
Use the [STEMG guidance](https://www.asd-ste100.org/STEsoftware.html) when you assess a language-checking tool.
