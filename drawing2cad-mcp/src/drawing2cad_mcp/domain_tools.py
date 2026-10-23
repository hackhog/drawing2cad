"""Versioned, path-free contracts shared by MCP and web adapters."""

from copy import deepcopy

from .cad_tools import CAD_DESCRIPTIONS, CAD_SCHEMAS
from .measurements_tools import MEASUREMENT_DESCRIPTIONS, MEASUREMENT_SCHEMAS
from .source_flags import ACTIONS, STROKE_CLASSES
from .step_tools import STEP_DESCRIPTIONS, STEP_SCHEMAS
from .vector.model import Kind
from .tolerances import TOLERANCE_OBSERVATIONS_SCHEMA


def _object(properties, required=None):
    return {"type": "object", "additionalProperties": False, "properties": deepcopy(properties),
            "required": list(properties) if required is None else required}


ID = {"type": "string", "pattern": "^[a-z]+_[0-9a-f]{32}$"}
HASH = {"type": "string", "pattern": "^[0-9a-f]{64}$"}
RUN = deepcopy(CAD_SCHEMAS["part_read"]["properties"])
REVISION = {key: deepcopy(CAD_SCHEMAS["build_from_description"]["properties"][key])
            for key in ("run_id", "expected_revision")}
PAGE = {"type": "integer", "minimum": 1}
DPI = {"type": "integer", "minimum": 36, "maximum": 600}
LIST = {"limit": {"type": "integer", "minimum": 1, "maximum": 100},
        "cursor": {"type": ["string", "null"], "maxLength": 200}}
TEXT = {"type": "string", "minLength": 1, "maxLength": 2000}
DRAWING = {"type": "object", "description": "The complete DrawingSpec from drawing_schema."}

DOMAIN_SCHEMAS = deepcopy(CAD_SCHEMAS)
DOMAIN_DESCRIPTIONS = deepcopy(CAD_DESCRIPTIONS)
DOMAIN_DESCRIPTIONS["part_read"] = "Read current part, revision, build state, budget, and events, plus retained diagnostic last_results. Audit reads remain available after the execution budget is reached."
DOMAIN_SCHEMAS["part_create"]["properties"]["sources"]["items"] = _object({
    "source_id": ID, "sha256": HASH, "role": {"enum": ["construction", "verification"]}})
DOMAIN_DESCRIPTIONS["part_create"] = "Create a part from uploaded source IDs and exact hashes. Evidence must use these source IDs. Verification sources cannot supply construction values."
DOMAIN_DESCRIPTIONS["part_export_review"] = "Export path-free JSON part, run manifest, drawing review, and recorded run trace as immutable artifacts."
DOMAIN_SCHEMAS["export_step"]["properties"]["delivery"] = {
    "enum": ["step_only", "complete_service"],
    "description": "step_only (default): the validated model gates the release, and release.drawing records the drawing status. "
                   "complete_service: the release also needs an accepted drawing whose PDF verification is bound to the released STEP bytes."}
DOMAIN_DESCRIPTIONS["export_step"] = ("Release validated STEP of the current model build. With delivery step_only (default), the drawing does not gate the release: "
                                      "release.drawing records its status (accepted, unverified, unreviewed, rejected, failed, or missing) with the drawing files or the reason. "
                                      "With delivery complete_service, the release fails unless the drawing is accepted and verified against the released STEP bytes; "
                                      "release.pair records the STEP, PDF, and verification report hashes. release.pair_current is false after a change of either file. "
                                      "Use delivery complete_service for a complete delivery. After a drawing change, repeat acceptance and release the new pair. AP242 and semantic PMI are optional unless requested.")

PROJECTION_VIEW = _object({
    "view_id": {"type": "string", "pattern": "^[A-Za-z][A-Za-z0-9_-]{0,63}$"},
    "region": {"type": "array", "items": {"type": "number", "minimum": 0, "maximum": 2000}, "minItems": 4, "maxItems": 4,
               "description": "View bounds on the sheet in mm [left, top, right, bottom], from the top-left corner, as in drawing_extract."},
    "toward_viewer": {"enum": ["+X", "-X", "+Y", "-Y", "+Z", "-Z"],
                      "description": "Model axis from the part to the viewer, for example -Y for a front view that looks along +Y."},
    "up": {"enum": ["+X", "-X", "+Y", "-Y", "+Z", "-Z"], "description": "Model axis that points up in the view."},
    "mm_per_sheet_mm": {"type": "number", "minimum": 0.01, "maximum": 100,
                        "description": "Part mm per sheet mm from pdf_calibrate in sheet_mm: 1:2 gives 2.0."},
}, ["view_id", "region", "toward_viewer", "up", "mm_per_sheet_mm"])

VECTOR3 = {"type": "array", "items": {"type": "number", "minimum": -100000, "maximum": 100000}, "minItems": 3, "maxItems": 3}
DERIVED_VIEW = _object({
    "id": {"type": "string", "pattern": "^[A-Za-z][A-Za-z0-9_-]{0,47}$"},
    "kind": {"enum": ["orthographic", "isometric", "section"]},
    "projection_type": {"enum": ["parallel", "perspective"], "description": "Only parallel is supported."},
    "view_direction": {**VECTOR3, "description": "Model direction from the part toward the viewer, for example [0, -1, 0] for a front view. Not for a section."},
    "up": {**VECTOR3, "description": "Model direction that points up in the view."},
    "scale_convention": {"enum": ["true_size", "isometric_drawing", "isometric_projection"]},
    "hidden_lines": {"type": "boolean"},
    "cutting_plane": _object({"letter": {"type": "string", "pattern": "^[A-Z]$"}, "origin": VECTOR3, "normal": VECTOR3,
                              "viewing_side": {"enum": ["positive_normal", "negative_normal"]},
                              "source_view_id": {"type": "string", "pattern": "^[A-Za-z][A-Za-z0-9_-]{0,47}$"}}),
}, ["id", "kind", "up"])

_EXTRA = {
    "drawing_verify": (_object({**REVISION, "artifact_id": ID, "source_id": ID, "expected_sha256": HASH},
                               ["run_id", "expected_revision", "expected_sha256"]),
        "Verify stored PDF bytes in restricted workers: PDF structure and binding, a Poppler raster at 300 dpi, the bound model projected again, "
        "the isometric projection, dimensions and their anchors, tolerance frames, and texts read with OCR (Tesseract). "
        "Give artifact_id for the PDF of the current drawing, or source_id for a supplied PDF without a binding. "
        "Return a versioned report with rule IDs and an annotated preview. An unreadable critical value fails. "
        "A changed PDF, drawing, revision, or build makes the report stale. A pass is a result of the supported profile, not ISO conformity."),
    "drawing_derive_views": (_object({**REVISION, "views": {"type": "array", "items": DERIVED_VIEW, "minItems": 1, "maxItems": 8}}),
        "Derive orthographic, isometric, and section views from the current validated build in the restricted worker. "
        "Return DrawingSpec 2.0 view drafts: projection matrix, visible and hidden edges, center lines, circles, arcs, ellipses, "
        "polylines for other curves with their approximation error, section boundaries with hatching, and the cutting line in the source view. "
        "Local view coordinates are matrix * model point. An isometric view needs a body-diagonal view_direction; dimetric, trimetric, "
        "and perspective requests fail. The derivation is bound to the part revision and the build hash. "
        "A model change makes it stale, and drawing_validate and drawing_render reject a stale derivation."),
    "model_projection_check": (_object({**REVISION, "source_id": ID, "page": PAGE,
                                        "views": {"type": "array", "items": PROJECTION_VIEW, "minItems": 1, "maxItems": 8}}),
        "Project the current validated build into orthographic drawing views in the restricted worker and compare the edges "
        "with the contour strokes of the construction source in each view region. A translation aligns each view; the scale "
        "and the axes come from the arguments. Fixed limits: p95 at most 0.3 mm, maximum at most 1.0 mm (part mm), coverage "
        "at least 0.85. Return per-view deviations, worst points, uncovered drawing points, a mirror candidate, and an overlay "
        "PNG artifact. Each view has its own status; a view that is not tested makes the result fail. Tangent edges count only for "
        "coverage. Hidden edges and sections are not compared. The result does not gate the release."),
    "step_render_pmi": (_object({"artifact_id": ID, "expected_sha256": HASH}),
        "Render imported AP242 model edges and stored PMI graphics from an authorized STEP artifact in a restricted worker. Return hash-bound inspection PDF and PNG artifacts. This does not establish visual approval, target-CAD support, or full conformance."),
    "part_render_pmi": (_object(REVISION),
        "Render the current validated AP242 build candidate before release. Return revision-bound inspection artifacts from actual stored PMI graphics. Keep the part, drawing review, and release state unchanged. Fixed views can show reversed or edge-on annotations; inspect the annotation-plane detail pages."),
    "step_reconstruct": (_object({"artifact_id": ID, "expected_sha256": HASH,
        "parameter_changes": {"type": "object", "maxProperties": 100,
            "propertyNames": {"pattern": "^[A-Za-z][A-Za-z0-9_-]{0,63}$"},
            "additionalProperties": {"type": "number"}}}, ["artifact_id", "expected_sha256"]),
        "Replay supported embedded AP242 construction from an authorized STEP artifact alone in a fresh restricted worker. Optional named parameter changes must pass existing measurements. Return diagnostic artifacts, not a released part or native target-CAD history."),
    "domain_schema": (_object({}), "Read versioned shared-domain tool inputs, public record schemas, and integration boundaries."),
    "upload_begin": (_object({"filename": {"type": "string", "minLength": 1, "maxLength": 255},
                              "size_bytes": {"type": "integer", "minimum": 1, "maximum": 20 * 1024 * 1024}, "sha256": HASH}),
                     "Begin a bounded PDF upload. The filename is metadata, never a server path."),
    "upload_get": (_object({"upload_id": ID}), "Read the committed upload offset and state."),
    "upload_chunk": (_object({"upload_id": ID, "offset": {"type": "integer", "minimum": 0},
                              "data_base64": {"type": "string", "maxLength": 699052}}),
                     "Append one base64 PDF chunk at its exact committed offset. Identical chunk retries are safe."),
    "upload_complete": (_object({"upload_id": ID}), "Verify uploaded byte count, SHA-256, and basic PDF markers. Return an immutable source ID. This does not validate PDF structure."),
    "upload_abort": (_object({"upload_id": ID}), "Abort an incomplete upload."),
    "source_get": (_object({"source_id": ID}), "Read metadata for an authorized uploaded source."),
    "source_list": (_object(LIST, []), "List uploaded sources for the authenticated principal."),
    "artifact_get": (_object({"artifact_id": ID}), "Read immutable artifact metadata and SHA-256."),
    "artifact_list": (_object({**LIST, **RUN}, []), "List this principal's artifacts. A run filter selects a part run or source ID."),
    "artifact_read": (_object({"artifact_id": ID, "offset": {"type": "integer", "minimum": 0},
                               "length": {"type": "integer", "minimum": 1, "maximum": 524288}}, ["artifact_id"]),
                      "Read bounded artifact bytes as base64. Verify SHA-256 after complete download."),
    "artifact_preview": (_object({"artifact_id": ID, "page": PAGE, "dpi": DPI,
                                  "include_image": {"type": "boolean"}}, ["artifact_id"]),
                         "Render an authorized PDF artifact or preview a PNG artifact. Return bounded image content for drawing review. Other artifact formats are unsupported."),
    "notes_read": (_object(RUN), "Read a run note and its independent note revision."),
    "notes_update": (_object({**RUN, "expected_revision": {"type": "integer", "minimum": 0},
                              "text": {"type": "string", "maxLength": 65536}}),
                     "Replace a run note with optimistic note revision control. Does not change the part revision."),
    "drawing_schema": (_object({"schema_version": {"type": "string", "enum": ["1.0", "2.0"]}}, required=[]),
                       "Read DrawingSpec version 1.0 (default) or 2.0 and its supported geometry, dimension, and review scope. "
                       "Version 2.0 adds isometric projection, ellipses, sections with cutting planes and hatching, sheet data, and a GPS profile. "
                       "drawing_render draws 2.0 content with a title block, a border, section marks, and tolerance frames. Use native angular and radius dimensions plus source-linked notes for wall draft and inside fillets. Notes must identify their affected regions."),
    "drawing_validate": (_object({**REVISION, "drawing_spec": DRAWING}), "Check supplied views, dimensions, evidence, uncertainty markers, and layout against the current part. Does not render or prove CAD equivalence."),
    "drawing_render": (_object({**REVISION, "drawing_spec": DRAWING}), "Render supplied geometry and native DXF dimensions in the restricted worker. Return matching DXF and PDF artifacts on success. Layout failures can return bounded collision details and diagnostic PDF/JSON artifacts bound to the exact drawing and part revision. Diagnostic artifacts cannot be reviewed as an accepted drawing. A STEP release links them as the files of a failed drawing. Invalidate the previous drawing review before worker execution; schema or non-layout preflight failures leave it unchanged."),
    "drawing_read": (_object(RUN), "Read current drawing state, artifact IDs, review binding, release membership, and retained diagnostic last_results."),
    "drawing_review": (_object({**REVISION, "drawing_sha256": HASH, "reviewer": {"type": "string", "minLength": 1, "maxLength": 200},
                                "reason": TEXT, "source_hashes": {"type": "array", "items": HASH, "minItems": 1, "uniqueItems": True},
                                "decision": {"enum": ["accepted", "rejected"]},
                                "verification_decisions": {"type": "array", "maxItems": 200, "items": _object({
                                    "rule_id": {"type": "string", "pattern": "^[A-Z]+(-[A-Z]+)?-[0-9]{2}$"},
                                    "feature": {"type": ["string", "null"], "maxLength": 128}, "reason": TEXT})}},
                               ["run_id", "expected_revision", "drawing_sha256", "reviewer", "reason", "source_hashes", "decision"]),
                       "Record an identified human or agent review of the exact drawing and part revision. Compare manufacturing notes, including draft and fillet requirements, with source evidence and model measurements. "
                       "A drawing is accepted only when this review is accepted and the current drawing_verify result passes the acceptance gate. "
                       "verification_decisions resolve needs_review findings of the current verification, each with a reason; they cannot resolve a fail or not_tested finding. "
                       "This attestation does not convert untested CAD equivalence into an automatic pass."),
    "job_submit": (_object({"operation": {"enum": ["build_from_description", "build_code", "drawing_render", "export_step"]},
                            "arguments": {"type": "object"}, "idempotency_key": {"type": "string", "minLength": 1, "maxLength": 128}}),
                   "Queue a durable CAD or drawing job. Validate ownership and revision at submission and execution. Reuse a key only for an identical request."),
    "job_get": (_object({"job_id": ID}), "Read job state, result, and structured error."),
    "job_list": (_object({**RUN, "limit": LIST["limit"]}, []), "List bounded recent jobs for this principal."),
    "job_cancel": (_object({"job_id": ID}), "Request cancellation. Queued jobs do not start. Active operations may finish; cancellation does not undo their effects."),
    "pdf_info": (_object({"source_id": ID}), "Inspect an uploaded PDF and its exact source SHA-256. No OCR."),
    "pdf_read_text": (_object({"source_id": ID, "pages": {"type": ["array", "null"], "items": PAGE, "minItems": 1, "uniqueItems": True},
                               "max_chars": {"type": "integer", "minimum": 1, "maximum": 1000000},
                               "tolerance_observations": TOLERANCE_OBSERVATIONS_SCHEMA}, ["source_id"]),
                      "Read native PDF text and source-linked tolerance candidates by source ID. Optional bounded client transcriptions use displayed regions and the current source hash. Candidates need source review and feature association. No OCR."),
    "pdf_render_page": (_object({"source_id": ID, "page": PAGE, "dpi": DPI, "include_image": {"type": "boolean"}}, ["source_id"]),
                        "Render an uploaded PDF page. Return an immutable PNG artifact and an optional bounded inline preview."),
    "pdf_crop_region": (_object({"source_id": ID, "page": PAGE, "dpi": DPI, "include_image": {"type": "boolean"},
                                 "bbox": {"type": "array", "items": {"type": "number", "minimum": 0, "maximum": 1}, "minItems": 4, "maxItems": 4}}, ["source_id", "page", "bbox"]),
                        "Render a detail crop. Normalized coordinates refer to the displayed page, from its top-left corner."),
    "drawing_extract": (_object({"source_id": ID, "page": PAGE, "include_strokes": {"type": "boolean"},
                                 "stroke_kinds": {"type": "array", "items": {"enum": [k.value for k in Kind]}, "minItems": 1, "uniqueItems": True},
                                 "stroke_offset": {"type": "integer", "minimum": 0},
                                 "stroke_limit": {"type": "integer", "minimum": 1, "maximum": 50000}}, ["source_id"]),
                        "Analyze native drawing vectors with the detected template profile (BCT A3, CAx A3, or A4 portrait). With include_strokes, strokes come in pages of stroke_limit (default 500); use strokes_page.next_offset. Verify detected text and dimensions against source images."),
    "source_flags_read": (_object({"source_id": ID, "page": PAGE}, ["source_id"]),
        "Read the review flags of a source page: unclear strokes, unreadable text, or missing views of drawing_extract, with stable flag IDs. Each flag includes the user decision, if one exists. Apply a decision as user input: ignore the flagged strokes, use the assigned stroke class, or use the corrected text instead of the extracted text. Record a decision that a construction value uses as a user decision, not as a source dimension. Decisions without a current flag are listed separately."),
    "source_flags_decide": (_object({"source_id": ID, "page": PAGE, "flag_id": {"type": "string", "pattern": "^(views|strokes-[0-9]+|text-[0-9]+)$"},
                                     "action": {"enum": [*ACTIONS, "reopen"]}, "stroke_class": {"enum": list(STROKE_CLASSES)},
                                     "text": {"type": "string", "minLength": 1, "maxLength": 200},
                                     "note": {"type": "string", "maxLength": 2000},
                                     "reviewer": {"type": "string", "minLength": 1, "maxLength": 200}},
                                    ["source_id", "flag_id", "action"]),
        "Record the decision of a human reviewer on one review flag: ignore it, classify its strokes, or correct its text. reopen removes the decision. An optional note explains the flag for the developers of the analysis. Return the updated flags of the page."),
    "source_flags_export": (_object({}),
        "Export all flag decisions of this principal with the flag, region, source identity, and analysis version. The export is labeled feedback for the developers of the vector analysis."),
}
for _name, (_schema, _description) in _EXTRA.items():
    DOMAIN_SCHEMAS[_name], DOMAIN_DESCRIPTIONS[_name] = _schema, _description
for _name, _schema in MEASUREMENT_SCHEMAS.items():
    _schema = deepcopy(_schema)
    del _schema["properties"]["path"]
    _schema["properties"]["source_id"] = deepcopy(ID)
    _schema["required"] = ["source_id" if key == "path" else key for key in _schema["required"]]
    DOMAIN_SCHEMAS[_name] = _schema
    DOMAIN_DESCRIPTIONS[_name] = MEASUREMENT_DESCRIPTIONS[_name]
for _name, _schema in STEP_SCHEMAS.items():
    if _name == "step_append_review_properties":
        continue
    _schema = deepcopy(_schema)
    del _schema["properties"]["path"]
    _schema["properties"]["artifact_id"] = deepcopy(ID)
    _schema["required"] = ["artifact_id" if key == "path" else key for key in _schema["required"]]
    DOMAIN_SCHEMAS[_name] = _schema
    DOMAIN_DESCRIPTIONS[_name] = STEP_DESCRIPTIONS[_name]
