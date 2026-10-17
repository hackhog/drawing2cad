"""Versioned, path-free contracts shared by MCP and web adapters."""

from copy import deepcopy

from .cad_tools import CAD_DESCRIPTIONS, CAD_SCHEMAS
from .measurements_tools import MEASUREMENT_DESCRIPTIONS, MEASUREMENT_SCHEMAS
from .step_tools import STEP_DESCRIPTIONS, STEP_SCHEMAS
from .vector.model import Kind


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
DOMAIN_SCHEMAS["part_create"]["properties"]["sources"]["items"] = _object({
    "source_id": ID, "sha256": HASH, "role": {"enum": ["construction", "verification"]}})
DOMAIN_DESCRIPTIONS["part_create"] = "Create a part from uploaded source IDs and exact hashes. Evidence must use these source IDs. Verification sources cannot supply construction values."
DOMAIN_DESCRIPTIONS["part_export_review"] = "Export path-free JSON part, run manifest, drawing review, and recorded run trace as immutable artifacts."
DOMAIN_DESCRIPTIONS["export_step"] = "Release validated STEP after the current drawing passes layout checks and an identified review. Drawing and part revisions must agree. AP242 and semantic PMI remain separate M3 requirements."

_EXTRA = {
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
    "drawing_schema": (_object({}), "Read DrawingSpec version 1.0 and its supported geometry, dimension, and review scope."),
    "drawing_validate": (_object({**REVISION, "drawing_spec": DRAWING}), "Check supplied views, dimensions, evidence, uncertainty markers, and layout against the current part. Does not render or prove CAD equivalence."),
    "drawing_render": (_object({**REVISION, "drawing_spec": DRAWING}), "Render supplied geometry and native DXF dimensions in the restricted worker. Return matching DXF and PDF artifacts on success. Layout failures can return bounded collision details and diagnostic PDF/JSON artifacts bound to the exact drawing and part revision. Diagnostic artifacts cannot be reviewed or released. Invalidate the previous drawing review before worker execution; schema or non-layout preflight failures leave it unchanged."),
    "drawing_read": (_object(RUN), "Read current drawing state, artifact IDs, and review binding."),
    "drawing_review": (_object({**REVISION, "drawing_sha256": HASH, "reviewer": {"type": "string", "minLength": 1, "maxLength": 200},
                                "reason": TEXT, "source_hashes": {"type": "array", "items": HASH, "minItems": 1, "uniqueItems": True},
                                "decision": {"enum": ["accepted", "rejected"]}}),
                       "Record an identified human or agent review of the exact drawing and part revision. This attestation does not convert untested CAD equivalence into an automatic pass."),
    "job_submit": (_object({"operation": {"enum": ["build_from_description", "build_code", "drawing_render", "export_step"]},
                            "arguments": {"type": "object"}, "idempotency_key": {"type": "string", "minLength": 1, "maxLength": 128}}),
                   "Queue a durable CAD or drawing job. Validate ownership and revision at submission and execution. Reuse a key only for an identical request."),
    "job_get": (_object({"job_id": ID}), "Read job state, result, and structured error."),
    "job_list": (_object({**RUN, "limit": LIST["limit"]}, []), "List bounded recent jobs for this principal."),
    "job_cancel": (_object({"job_id": ID}), "Request cancellation. Queued jobs do not start. Active operations may finish; cancellation does not undo their effects."),
    "pdf_info": (_object({"source_id": ID}), "Inspect an uploaded PDF and its exact source SHA-256. No OCR."),
    "pdf_read_text": (_object({"source_id": ID, "pages": {"type": ["array", "null"], "items": PAGE, "minItems": 1, "uniqueItems": True},
                               "max_chars": {"type": "integer", "minimum": 1, "maximum": 1000000}}, ["source_id"]),
                      "Read native PDF text by source ID. No OCR or dimension inference."),
    "pdf_render_page": (_object({"source_id": ID, "page": PAGE, "dpi": DPI, "include_image": {"type": "boolean"}}, ["source_id"]),
                        "Render an uploaded PDF page. Return an immutable PNG artifact and an optional bounded inline preview."),
    "pdf_crop_region": (_object({"source_id": ID, "page": PAGE, "dpi": DPI, "include_image": {"type": "boolean"},
                                 "bbox": {"type": "array", "items": {"type": "number", "minimum": 0, "maximum": 1}, "minItems": 4, "maxItems": 4}}, ["source_id", "page", "bbox"]),
                        "Render a detail crop. Normalized coordinates refer to the displayed page, from its top-left corner."),
    "drawing_extract": (_object({"source_id": ID, "page": PAGE, "include_strokes": {"type": "boolean"},
                                 "stroke_kinds": {"type": "array", "items": {"enum": [k.value for k in Kind]}, "minItems": 1, "uniqueItems": True}}, ["source_id"]),
                        "Analyze native drawing vectors with the limited BCT/NX A3 profile. Verify detected text and dimensions against source images."),
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
