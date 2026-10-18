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

- This authorship rule applies to all agents and all agent models.
- The person who starts the agent is the responsible author. Use that person's Git identity for commits.
- Agents must not add themselves as authors, co-authors, or collaborators.
- Do not add agent attribution to commit trailers, pull request text, issue text, or review comments.
- This prohibition includes `Co-Authored-By:` trailers and "Generated with ..." text that identifies an agent.
- Start each work item from a GitHub issue. If no issue exists, create one with `gh issue create`.
- Before work starts, assign the issue to the authenticated GitHub user with `gh issue edit <number> --add-assignee @me`.
- Verify the assignment on GitHub before work starts. Use the person's account, not an agent identity.
- If another user is already assigned, resolve responsibility with the user before work starts. Do not remove existing assignees without authorization.
- Create one branch for each issue. Name the branch `<type>/<issue-number>-<short-name>`, for example, `feat/12-pdf-upload`.
- Do not commit directly to `main`.
- Use a Git worktree when the user asks for one. Otherwise, use a branch in the main checkout.
- Create one pull request for each issue. Add `Closes #<number>` only when the pull request completes the issue. Use `Refs #<number>` for a partial milestone and list the remaining acceptance work.
- Keep each pull request within its issue scope. Create a separate issue for additional work.
- Describe the tests and their actual results in the pull request description. Identify checks that did not run.
- Do not report historical results as new tests.
- Do not refer to GitHub issues or pull requests in the documentation, code comments, or the diagram source. Put work status and history in issues and pull requests. Document only the current state, the decisions, and the necessary references. Commit messages and pull request descriptions can refer to issues. CI checks the Markdown files and the diagram source.
- Merge a pull request only after CI passes and review is complete.
- Before removal, preserve uncommitted changes and needed ignored files. Remove the issue worktree after merge.

## CAD workflow

- For CAD work, use [skills/drawing2cad/SKILL.md](skills/drawing2cad/SKILL.md). The workflow must work without previous chat messages or a specific agent model.
- Use only `drawing2cad-mcp` for PDF preparation and CAD execution. Keep backend-specific code in maintained server adapters.
- Follow [ADR 0014](docs/adr/0014-headless-build123d-metric-prototype.md) for the M1 prototype, M2 complete service, and M3 AP242 boundaries.
- The complete service must deliver a dimensioned technical drawing and a verified 3D model. Either can be created first. Compare their final revisions before delivery.
- Native 2D sketches alone do not meet the drawing requirement. Use [drawing-delivery.md](skills/drawing2cad/references/drawing-delivery.md) for drawing delivery and STEP-only tests.
- Include necessary views, sections, dimensions, units, manufacturing data, and uncertainty markers. Give evidence for these data.
- If a dimension or position is missing, infer a reasonable value from the drawing geometry. Record `assumed`, its reason, source region, units, and affected feature.
- Mark radii without dimensions and all unclear details. Keep assumptions distinct from source dimensions and user design decisions.
- Build a feature when a reasonable assumption supports it. Block only when no reasonable assumption is possible.
- M1 uses a versioned JSON part description as the editable construction source. It does not prove editable construction or semantic PMI inside STEP.
- AP242 and semantic PMI are optional for the hackathon metric. M3 covers construction, parameter changes through adapters, and semantic PMI. Test these claims separately from geometry export.
- Export a STEP candidate from the validated build. Re-import it in a fresh worker and validate it before release.
- Record independent STEP analysis and target-CAD opening separately. `not_tested` never means `pass`.
- The production target is a fully headless Docker service. No required phase may depend on a CAD GUI or GUI dispatcher.
- Use only a verified sandbox profile for CAD execution. Do not silently fall back to an unsandboxed host process.
- The current MCP executes CAD only through the headless build123d worker. It has no FreeCAD proxy.
- Keep historical adapter code and recorded hashes unchanged. Historical FreeCAD calls are unavailable through the current MCP.
- Do not create ad hoc model scripts, macros, or executable helper files. This restriction does not prohibit authorized development of versioned MCP server code.
- Use only permitted sources. Do not use verification resources as unreported construction inputs. Keep original resources unchanged.
- Give suitable independent review tasks to subagents when available. A separate reviewer is optional for the hackathon metric. The acting agent can supply its identified review attestation. Run changes to the same model in sequence. Review the results before delivery.
- Create requested target-format derivatives after the required STEP tests. Distinguish an imported body from reconstructed native features.

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
