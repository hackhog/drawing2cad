# 17. Add a bounded AP242 construction adapter and nominal PMI

Date: 2026-10-17

## Status

Initial implementation for [issue 25](https://github.com/hackhog/drawing2cad/issues/25).
This decision does not close M3 acceptance. It extends ADR 0014.
CAD-specific export and native feature adapters are a separate feature in
[issue 33](https://github.com/hackhog/drawing2cad/issues/33). They do not block neutral AP242 delivery.

## Decision

Keep AP214 as the default export. Select AP242 explicitly with
`build_from_description(export_profile="ap242")`. Use the OCCT XDE writer with
`AP242DIS`; do not convert a file by replacing its schema header.
Record the actual file schema and installed OCP binding version in each result.
The initial writer emits
`AP242_MANAGED_MODEL_BASED_3D_ENGINEERING_MIM_LF {1 0 10303 442 1 1 4 }`.
This records the writer profile; it does not establish full edition conformity.

Store a versioned application construction record in a product-bound STEP property.
The record contains the closed part description and the supported PMI specification.
Bind it to the evaluated BREP. Limit its size, reject duplicate fields and unsupported
profiles, and never execute code or load paths from this record.
The maintained adapter rebuilds the ordered features in a restricted worker.
It compares occupied material in both directions and bounding boxes before a parameter edit.
Re-import the new STEP in another restricted worker before publication.

This property is an application-specific interchange contract. It is not a standard
procedural representation or proof of a native NX or SOLIDWORKS feature tree.
Existing historical adapters and their recorded hashes remain unchanged.

Create nominal diameter and linear PMI with XDE dimension objects and explicit face
associations. Select analytic faces by geometry. Reject missing or ambiguous matches.
Read values, associations, and presentation geometry back through XDE separately from
the BREP import. The reader and writer share OCCT; this is not independent-kernel acceptance.
Keep uncertain evidence distinct from authoritative source dimensions.

## Interface and release rules

The MCP exposes `pmi_schema` and an optional PMI specification on the AP242 build.
The remote `step_reconstruct` operation uses an owner-bound artifact ID and exact hash.
It passes STEP bytes and optional parameter values to a new worker, without the run's
part description. It returns diagnostic artifacts under a separate replay identity.
It does not update or release the original run.

Existing source measurements remain in force after parameter changes. A change that
conflicts with those measurements fails. The adapter must not remove a failed source
expectation or treat it as an approved design change.

AP242 builds retain the normal drawing, revision, source-review, and release gates.
A profile or PMI change requires a new build and a new drawing review.
No FreeCAD service or GUI becomes a production dependency.

## Remaining M3 work

- Accept externally supplied STEP bytes in a new service through a bounded public interface.
  The initial remote replay operates on existing artifacts.
- Test supported AP242 entities and rules with an external analyzer.
- Open graphical PMI in a supported target viewer and inspect its actual display.
- Extend or explicitly constrain tolerances, datums, thread semantics, feature scope,
  and geometry associations across edits.
- Approve the edition and conformance profile against the complete acceptance matrix.
  A writer setting, file header, or successful OCCT round trip is insufficient.

## Separate CAD-specific feature

Issue 33 owns native NX, SOLIDWORKS, and other target-format derivatives, their
licenses and deployment constraints, and native feature reconstruction tests.
Run those adapters after neutral STEP validation. Generic import is not a native-history test.
Issue 25 keeps the neutral drawing2cad adapter, STEP-only parameter regeneration,
and semantic and graphical PMI acceptance.

## Sources

The [OCCT STEP guide](https://github.com/Open-Cascade-SAS/OCCT/blob/master/dox/user_guides/step/step.md)
documents XDE data exchange and the AP242 writer selection.
The [NIST STEP File Analyzer](https://www.nist.gov/services-resources/software/step-file-analyzer-and-viewer)
supports separate semantic and graphical PMI analysis. Its documented Windows and Excel
requirements make it an external acceptance option, not a required Linux production phase.
