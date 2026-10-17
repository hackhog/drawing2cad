# Work instructions for drawing2cad

## Documentation language

- Use technical English in accordance with ASD-STE100 for all project documentation.
- Apply this rule to README files, skill instructions, reference guides, technical plans, and new reports.
- Use technical English for new code comments, docstrings, tool descriptions, and architecture decision records.
- Keep user-facing interface text in its specified product language. This exception does not apply to technical documentation.
- Use [documentation-language.md](skills/drawing2cad/references/documentation-language.md) for the reference edition, project terms, and review procedure.
- Keep original source text, identifiers, code with recorded hashes, and historical evidence unchanged. Write explanations of these items in English.
- Do not state full STE conformity without a review against the applicable rules and dictionary.

## Issues and pull requests

- Start each work item from a GitHub issue. If no issue exists, create one with `gh issue create`.
- Create one branch for each issue. Name the branch `<type>/<issue-number>-<short-name>`, for example, `feat/12-pdf-upload`.
- Do not commit directly to `main`.
- Use a Git worktree when the user asks for one. Otherwise, use a branch in the main checkout.
- Create one pull request for each issue. Add `Closes #<number>` to the pull request description.
- Keep each pull request within its issue scope. Create a separate issue for additional work.
- Describe the tests and their actual results in the pull request description. Identify checks that did not run.
- Do not report historical results as new tests.
- Merge a pull request only after CI passes and review is complete.
- Before removal, preserve uncommitted changes and needed ignored files. Remove the issue worktree after merge.

## CAD workflow

- For CAD work, use [skills/drawing2cad/SKILL.md](skills/drawing2cad/SKILL.md). The workflow must work without previous chat messages or a specific agent model.
- **First, create a dimensioned technical drawing. Then, do the drawing review. Use that drawing to build the native parametric 3D model. Export STEP last.**
- Native 2D sketches alone do not meet the drawing requirement. Use [drawing-first.md](skills/drawing2cad/references/drawing-first.md) for changes and STEP import tests.
- Include the necessary views, sections, dimensions, units, manufacturing data, and uncertainty markers in the drawing. Give evidence for these data.
- Mark radii without dimensions and all unclear details. Keep approved assumptions identified as assumptions.
- Keep model operations and parameters editable. A STEP end body alone does not meet the construction-history or semantic-PMI requirement.
- Test AP242 content, reconstruction from STEP alone, and changes through import adapters separately.
- Use only `drawing2cad-mcp` and its FreeCAD proxy for PDF preparation and CAD execution. You can send inline code to the MCP.
- The production target is a fully headless server. All required phases must work without a FreeCAD GUI session or GUI dispatcher.
- Test drawing creation and rendering, editable construction, AP242, PMI, reconstruction, and validation on that server. A GUI bridge is a development path only.
- Do not create ad hoc model scripts, macros, or executable helper files. This restriction does not prohibit authorized development of versioned MCP server code.
- Use only permitted sources. Do not use verification resources as unreported construction inputs. Keep original resources unchanged.
- Give suitable independent review tasks to subagents. Run CAD changes to the same document in sequence. Review their results before delivery.

## Files and evidence

- Put generated CAD files, drawings, images, tool catalogs, and reports in ignored output directories, for example `output/<run_id>/`.
- Do not commit generated outputs. Keep maintained skill references and original resources under version control.
- Do not commit machine-specific configuration, credentials, environments, or caches. Obey the existing `.gitignore` rules.
- Keep a run manifest. Include input and output hashes, tool versions, drawing and contract revisions, and actual test results.
- Do not report a historical result as a new test.
- Maintain skill changes in the project. Compare changed files with the local skill installation, if present.
- Keep the skill independent of project data. Do not package or link customer parts, resource files, model data, host snapshots, or historical run results.
- Supply authorized model inputs and validation evidence separately for each run. Keep removed historical evidence outside the skill package.
- Work instructions specify requirements. Do not state that the MCP enforces a requirement without an implementation and a test.

## Architecture diagram

- The source of the README image is `docs/diagrams/drawing2cad-overview.json` ([ADR 0011](docs/adr/0011-diagrams-in-readme-checked-by-ci.md)).
- Do not edit the HTML or the SVGs in `docs/diagrams/` by hand. Change the JSON, run `npm run build --prefix tools/diagrams`, and commit all files in `docs/diagrams/`.
- If the architecture changes (new component, new interface, new client), update the overview in the same PR.
