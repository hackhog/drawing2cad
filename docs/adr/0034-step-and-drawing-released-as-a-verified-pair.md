# 34. STEP and drawing released as a verified pair

Date: 2026-10-21

## Status

Accepted. Uses the PDF verification of [ADR 0032](0032-independent-verification-of-the-final-drawing-pdf.md)
and the acceptance gate of [ADR 0033](0033-drawing-acceptance-gate.md).
Implemented in the MCP (`domain_service.py`, `domain_tools.py`), the web backend (`agent/mapping.py`), and the web UI (`ArtifactsPanel.tsx`).

## Context

`export_step` releases the STEP bytes of the validated build candidate and records the drawing status.
The drawing verification compares the PDF with the build candidate. The release did not require that the drawing was verified against the released STEP bytes,
and it did not record which STEP file, PDF, and report formed the delivery. A changed file after the release was not visible.

## Decision

- `export_step` takes `delivery`:
  - `step_only` (default): the validated model gates the release, as before. The drawing status is recorded. A STEP-only release does not claim a matching drawing.
  - `complete_service`: the release also needs an accepted drawing (ADR 0033) whose verification is bound to the STEP bytes of this release.
    Otherwise it fails with `RELEASE_PAIR_REQUIRED` and names the reason.
- The released STEP bytes are the bytes of the validated candidate after the fresh-worker re-import of the build. The verification binds the same candidate hash.
  The service checks after the export that the released hash and the hash of the registered STEP copy are the verified hash,
  and that the stored PDF still has its verified bytes. A change during the release fails with `RELEASE_PAIR_REQUIRED`.
- The release record has `delivery` and `pair`: the STEP hash and artifact, the PDF hash and artifact, the verification report hash and artifact, the profile,
  the drawing hash, the part revision, and the digest of the review. Without an accepted, verified drawing, `pair` is null.
- `export_step` and a read of the release (`part_read`) give `pair_current` and `pair_reason`. The pair is current while the released STEP file and the PDF file have their recorded bytes,
  and the drawing is still accepted with the same verification and review. A change of either file, or a new drawing, verification, or review, makes it false.
- The web backend shows a release drawing as not current when `pair_current` is false. The web UI names a complete-service delivery and shows when it is outdated.

## Consequences

- A complete-service delivery contains one STEP file and one PDF that were verified against each other.
- The pair binding depends on the drawing verification. Its limits (ADR 0032) also limit the pair: only the rules of the verification profile are checked.
- Comparison of each dimension with the STEP geometry and complete feature coverage are separate decisions.

## Tests

- `drawing2cad-mcp/tests/test_verified_release_pair.py`: a complete-service release records one verified pair with matching STEP, PDF, and report hashes;
  a drawing that is not accepted cannot be released as a pair, but a STEP-only release still works and records no pair;
  a pair from different revisions and a pair from other candidate bytes of the same revision fail;
  a changed STEP file and a changed PDF file after the release make the pair not current.
- `app/backend/tests/test_agent_runs.py`: a changed complete-service pair shows the release drawing as not current.
