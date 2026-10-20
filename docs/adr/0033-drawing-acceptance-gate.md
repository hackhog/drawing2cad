# 33. Drawing acceptance gate

Date: 2026-10-20

## Status

Accepted. Uses the PDF verification of [ADR 0032](0032-independent-verification-of-the-final-drawing-pdf.md).
Implemented in the MCP (`drawing_verification.py`, `pdf_verifier.py`, `domain_service.py`), the web backend (`agent/mapping.py`, `api.py`),
and the web UI (`ReviewPanel.tsx`, `ArtifactsPanel.tsx`).

## Context

`drawing_review` records an identified review of a drawing. Until now an accepted review of the current model was sufficient for the drawing status `accepted`.
`drawing_verify` checks the final PDF bytes, but its result did not gate the acceptance. A drawing with a failed or untested verification could be accepted.

## Decision

### Acceptance

- The drawing status `accepted` needs all of these:
  - an accepted `drawing_review` of the current drawing and the current build,
  - a current verification record (`drawing_read`): no bound input changed,
  - the verification profile `drawing2cad-verify-1`,
  - the acceptance gate passes,
  - the review names the verification report that it covers (`verification_report_sha256`, recorded automatically).
- Otherwise an accepted review gives the new status `unverified`, with the reason and the blocking findings.
  The other statuses stay: `unreviewed`, `rejected`, `failed` (diagnostic files only), and `missing`.

### Mandatory rules

- `pdf_verifier.MANDATORY_RULES` lists the rules of the profile that the acceptance needs. `STYLE-01` is reported, but it is not mandatory.
  `REVIEW-01` is the identified review itself.
- The verifier gives each mandatory rule a finding. A rule without content gets `not_applicable` with a fixed reason
  (for example "The drawing has no tolerance frames."). Only the reasons in `ABSENT_REASONS` are permitted. Any other missing rule gets `not_tested`.
  The units and the part revision in the title block have no such reason, so a drawing without a title block cannot be accepted.
- A view without a projection gets `MODEL-01` `not_tested`.

### Gate

- A mandatory finding with `fail` or `not_tested` blocks. It cannot be decided in review.
- A mandatory finding with `needs_review` blocks until the identified review decides it.
  `drawing_review` takes `verification_decisions`: the rule ID, the feature, and a reason for each decided finding.
  A decision must name a `needs_review` finding of the current verification. Other decisions fail with `REVIEW_DECISION_INVALID`.
- A `not_applicable` finding needs a reason.
- The drawing state keeps the mandatory findings that are not a pass (at most 300). A truncated record blocks.

### Invalidation

- The verification binding contains the part revision, the description, the construction source hashes, the profile, the stored build candidate bytes,
  the drawing hash, and the stored PDF bytes. A change of any of them makes the record stale, and the drawing is not accepted.
- A new verification with another report needs a new review. A review covers only the report that it names.

### Release and interface

- The STEP release keeps its policy: the validated model gates it, and it records the drawing status. A STEP-only release does not imply an accepted drawing.
- `drawing_read` returns `acceptance` with the status, the reason, and the gate.
- The web backend maps the verification report and preview to the roles `verification_report` and `verification_preview`.
  Diagnostic PDFs keep the role `drawing_diagnostic`. The review data has `drawing_acceptance`.
- The web UI shows the drawing status, the verification state, the blocking findings with their own status, and the number of decided findings.
  `not_tested` is never shown as a pass.

## Consequences

- An accepted review alone no longer gives an accepted drawing. Existing runs show `unverified` until `drawing_verify` passes.
- A drawing with content outside the GPS profile needs explicit review decisions.
- The gate is a profile result. It is not ISO conformity.

## Tests

- `drawing2cad-mcp/tests/test_drawing_acceptance.py`: a passed verification with an accepted review gives `accepted`;
  a failed and an untested mandatory rule block; `needs_review` blocks until a decision; a decision for a finding that is not open fails;
  a PDF change after acceptance makes the release drawing status outdated; a new verification needs a new review; the gate needs a current record of the profile.
- `drawing2cad-mcp/tests/test_pdf_verification.py`: the verifier gives each mandatory rule a finding, and the correct flange passes the gate after its review decisions.
- `app/backend/tests/test_agent_runs.py`: the acceptance view and the separate artifact roles.
- `app/frontend/src/lib/__tests__/drawingAcceptance.test.tsx`: the review panel shows blocking findings, their status, and outdated verifications.
