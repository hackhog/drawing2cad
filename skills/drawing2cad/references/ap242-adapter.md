# AP242 adapter workflow

Use this workflow only if the live MCP advertises AP242 support and returns `pmi_schema`.
Do not infer support from the skill version.

1. Prepare the authorized part description and dimensioned drawing with the normal workflow.
2. Read `pmi_schema`. Supply only supported nominal dimensions with feature and evidence IDs.
   Use geometric selectors that identify one intended face or face pair. Do not use unstable face indices.
3. Build with `export_profile="ap242"` and the optional PMI specification.
4. Inspect the actual schema, fresh geometric import, STEP-only reconstruction report,
   independent analysis, and separate PMI read-back report. A geometry pass does not establish a PMI pass.
   Confirm that the independent report has the candidate hash and a different worker identity.
   Read its scope. A schema read does not establish full EXPRESS conformity.
5. Review the current drawing and model. Release and download through the normal gates.
   Before release, use `part_render_pmi` with the current run and revision when available.
   Inspect every detail page through `artifact_preview`. Read stored strokes in their
   annotation plane: fixed overview views can reverse the text or show it edge-on.
   Compare labels, leaders, geometry associations, and uncertainty markers with the
   semantic values and source evidence. Record the reviewer and actual outcome.
   A renderer pass is not a visual-review pass. Use `step_render_pmi` with an artifact
   ID and exact hash for the same inspection after release.
6. For a replay test, call `step_reconstruct` with the STEP artifact ID and exact hash.
   Optional `parameter_changes` can change named values. Existing source measurements
   remain binding. A conflicting edit fails until a separate reviewed design change is supported.
7. Inspect the recovered description, new STEP, and validation report. Replay outputs are
   diagnostic artifacts. They do not approve a drawing or mutate the original run.

The STEP carries an application-specific construction record for the installed adapter.
This is not proof of standard procedural construction or native target-CAD history.
CAD-specific export and native feature adapters are a separate optional workflow.
They are not required for neutral STEP delivery. Use
[target-format-exports.md](target-format-exports.md) only for a requested target derivative.
The remote operation uses an existing generated artifact for internal validation.
External STEP upload and session restoration are out of scope. Product input is PDF.

Keep semantic PMI, graphical geometry, target-viewer display, independent conformance,
and native feature reconstruction as separate results. Never change `not_tested` to `pass`
because another result passed. Report unsupported tolerances, datums, and thread semantics.
The headless inspection renderer uses the same OCCT reader as the server. Record this
limit; it is not independent-kernel or third-party CAD evidence. Neither preview tool
approves a drawing or model. Run the normal review gates separately.
