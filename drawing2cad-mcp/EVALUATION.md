# Evaluation protocol

Use this protocol to compare a recorded baseline with a candidate revision.
Fix tasks, inputs, settings, budgets, and acceptance criteria before execution.
Report actual evidence. Do not infer model performance from unit tests.

## Evaluation levels

| Level | Purpose | Acceptance evidence | Excluded claim |
|---|---|---|---|
| Deterministic tests | Verify parsers, schemas, source restrictions, revision conflicts, and evidence gates. | Actual test command, environment identity, exit status, test results, and artifact hashes. | No proof of model decisions, drawing quality, CAD execution, or complete AP242 support. |
| Synthetic model decisions | Measure tool selection, argument construction, error recovery, and next actions on generic inputs. | Model transcript, tool-call trace, expected decisions, gate results, and independent scoring. | No proof of customer-drawing interpretation or physical CAD correctness. |
| M1 reconstruction | Measure PDF interpretation, editable JSON construction, geometry checks, and fresh STEP import. | Source inventory, description, geometry measurements, candidate/release, review records, manifest, and trace. | A technical release does not prove source completeness, independent STEP conformance, NX opening, or AP242. |
| Complete-service matrix | Measure the M2 drawing/service requirements and M3 AP242 requirements on permitted fixtures. | Actual drawing, model, STEP, PMI, reconstruction, change, and independent validation artifacts. | No success claim for an unavailable or unexecuted phase. |

[ADR 0014](../docs/adr/0014-headless-build123d-metric-prototype.md) defines the current issue 12 milestones.
The headless worker is part of M1. M2 upload/drawing delivery and M3 AP242 acceptance remain separate requirements.
Do not apply the former deferral to issues 7 and 11 to the current M1 implementation.

The maintained `drawing2cad_mcp.evaluation_client` replays declared MCP calls and records their results.
The [local model client](../docs/local-model-evaluation.md) runs a bounded Ollama trial through MCP.
These are evaluation clients, not production provider routing or evidence of model quality.
Keep unavailable or unexecuted claims as `not_tested`.
A diagnostic trial can use one repetition, but it cannot establish a model ranking.

## Baseline and candidate records

Capture the baseline before changes when execution is possible.
If no baseline was executed, record `not_tested` and its reason.
An old report is historical evidence, not a new baseline run.
Keep generated records in ignored output storage.
Do not commit transcripts, generated CAD files, or machine-specific configuration.

Each baseline and candidate manifest must contain:

| Field group | Required content |
|---|---|
| Identity | Protocol version, evaluation ID, run ID, baseline or candidate label, UTC timestamps, and repository commit. |
| Source revision | Dirty-tree status, changed-source hashes when applicable, skill version and hash, schema versions, and adapter code hashes. |
| Toolchain | MCP package version, live tool-catalog hash, dependency versions, backend identity, renderer identity, and container digest when applicable. |
| Tasks | Task IDs, fixture IDs, exact input hashes, permitted pages, task-specification hash, and validation-policy hash. |
| Authorization | Source authorization reference, permitted roles, permitted execution environment, and any provider-transmission authorization. |
| Model | Provider, exact requested model ID, resolved version when available, generation settings, reasoning settings, and supported-setting differences. |
| Limits | Repetitions, token and tool-call limits, timeout, retry policy, and approved cost limit. |
| Results | Phase outcomes, gate defects, expected and actual decisions, measurement reports, artifact paths, and exact-byte hashes. |
| Usage | Tool calls, input/output tokens, actual cost and currency, model time, tool time, and total wall time. |
| Missing data | `null` values with field-specific reasons. Do not replace unavailable measurements with zero. |

Hash the complete execution prompt and each fixture or tool response supplied to the model.
Keep the prompt, catalog, fixture, and transcript hashes linked to the corresponding repetition.
Record resolved model identity as unavailable when the provider supplies only a moving alias.
Do not claim an exact model-version comparison from that alias alone.

Use the same fixture and policy revisions for the baseline and candidate.
Record intended tool or skill changes explicitly.
Do not compare unrelated historical runs as if only the candidate change differed.

## Source roles and isolation

| Role | Permitted use |
|---|---|
| `construction` | M1 source role for interpretation and construction within the declared task. Legacy evidence calls use `construction_source`. |
| `verification` | M1 source role for independent comparison. Exclude it from model context and construction values. Legacy evidence calls use `verification_only`. |
| Tool reference | Interface and adapter instructions supplied as evaluation context. The legacy evidence profile calls this `tool_reference`; it is not an M1 part-source role. |

Use generic synthetic inputs for model decision tests.
Keep permitted drawing inputs separate from reference STEP and native CAD files.
During STEP-only reconstruction, STEP is the only source of model content.
Make independent expectations available only to the subsequent validator.
A new process alone does not enforce isolation.
Record and restrict actual file access and model-context inputs.

Do not inspect or record secret values.
Do not transmit customer data to an external provider without explicit authorization.
A local source allowlist does not authorize provider transmission.
Do not incur provider charges without an approved provider and cost limit.

## Model matrix and repetitions

Select strong, cheaper, and local model profiles before a comparative evaluation.
Record the reason for each selection. Do not select profiles from favorable results.
If a required runtime is unavailable, record `not_tested` and its reason.
Use exact provider model identifiers and record the evaluation date.
Use the same tasks, scoring rules, supported settings, and repetition count for all three models.
Use at least three repetitions per model and fixture for the initial comparison.
Fix repetition count and random seeds, where supported, before the first run.
Record any unsupported setting or model-specific limit.
Do not silently treat different reasoning or token budgets as equivalent.

Start each repetition with a fresh model context and fresh managed run.
Do not supply previous successful transcripts as hidden assistance.
Use the same predefined retry policy for every model.
Record failed attempts and retries in the usage totals.

## Fixed measurable criteria

| Level or phase | Criterion fixed before execution |
|---|---|
| Deterministic tests | All required tests pass. Identify skipped checks and their effect on the requested claims. |
| Synthetic tool selection | The selected tool and required arguments match the expected permitted action. |
| Synthetic gate handling | Reject every forbidden transition, stale hash, stale revision, and prohibited source role in the task set. |
| Synthetic recovery | Return the expected corrective action within the fixed tool-call, token, and time limits. |
| Capability decision | Identify missing CAD capabilities. Do not report a successful build or export from an evidence-gate result. |
| PDF observation | Each used dimension and note has source provenance. Unresolved data remain visible. |
| Drawing and review (M2) | Editable dimensioned sheet and inspected preview agree with the final model revision. Either can be created first. |
| Description and build (M1) | Validate named parameters, supported operations, units, evidence references, and measured geometry within the declared profile. |
| Source coverage (M1) | A separate reviewer compares every required view, feature, and printed callout with the declared model and measurements. |
| Drawing/model comparison | Independent measurements meet the fixed dimension, projection, and section tolerances. |
| AP242 and PMI (M3) | Verify final BREP, constructive data, semantics, associations, and graphical presentation separately. |
| Reconstruction and change | Reconstruct from STEP alone, apply the specified change, export again, and verify another fresh reconstruction. |
| Delivery | All required phase evidence exists and passes. Otherwise identify a limited candidate and its missing claims. |

Fix geometry tolerances, required PMI types, operation scope, and change cases in the fixture policy.
Do not change expected values or thresholds after examination of candidate outputs.
A parameter list, embedded JSON, or readable model tree alone does not prove driving parameters or transferable history.

## Outcomes and comparison

Use one test status per required claim:

| Status | Meaning |
|---|---|
| `pass` | The test executed and all fixed criteria passed. |
| `fail` | The test executed and at least one fixed criterion failed. |
| `not_tested` | The test did not execute. Record the reason and any blocking prerequisite. |

Keep original status fields in historical records unchanged.
For comparison, map legacy `passed` to `pass`, `failed` to `fail`, and `not_run` to `not_tested`.
A legacy `blocked` phase maps to `not_tested` with its blocking reason.
Client stop reasons and `released` are execution outcomes, not replacements for these acceptance statuses.

A correct rejection of an unsupported action can pass a synthetic decision test.
It does not pass the blocked CAD phase.
Do not count a model decision error as an infrastructure failure.
Keep gate failures, model errors, and infrastructure defects separate.

Report counts for every model, fixture, repetition, and phase.
Show passed, failed, blocked, and unexecuted counts together.
State denominators for every rate. Do not omit blocked or unexecuted work from the full task count.
Report expected gate rejections separately from unexpected failures.

Count total, successful, rejected, and failed tool calls, including retries.
Report input, output, cached, and reasoning tokens separately when available.
Use actual billed cost when available. Label any separate cost estimate and its price-source date.
Record unavailable usage or cost as `null` with a reason.
Report model time, tool time, and total elapsed time without silently combining overlapping durations.

Publish deterministic, synthetic-model, M1 reconstruction, and complete-service results in separate tables.
Do not fill empty model rows with unit-test results.
Do not claim improvement before comparable baseline and candidate evidence exists.

## Technical release and source accuracy

`export_step` validates the stored geometry checks and the structure of an identified source-review attestation.
It does not automatically identify omitted source features or omitted printed dimensions.
Keep the callout-to-measurement inventory and an independent source review with the release evidence.
Do not treat a bounding-box pass as proof of an internal web, perimeter rim, rib, or drill tip.
If source review finds an omission, mark source accuracy and the metric result as failed.
Keep the technical release response as historical evidence; it does not override the failed source review.
Independent conformance, NX opening, and complete M2/M3 claims remain separate results.
