// Synthetic contract fixtures. They describe a fictitious plate, not a customer part.
// Simulated data does not establish end-to-end acceptance.
import type { Assumption, Operation, Parameter, ProjectionCheck, ProjectionStatus, Uncertainty, ValidationResult } from "./contract";
import type { Drawing, ExtractResult, Stroke } from "./drawing";

/** Synthetic projection data for display tests, never an executed geometry check. */
export function fixtureProjection(status: ProjectionStatus, revision: number): ProjectionCheck {
  return {
    status, revision, simulated: true, report_artifact_id: null, overlay_artifact_id: null,
    reason: status === "not_tested" ? "No simulated projection check exists for this revision." : null,
    page: status === "not_tested" ? null : 1, sheet_size_mm: [297, 210],
    views: status === "not_tested" ? [] : [{
      view_id: "front", status: status === "matches" ? "pass" : "fail", reason: null,
      region_sheet_mm: [20, 20, 200, 140], max_capped: false,
      metrics: { p95_mm: status === "matches" ? 0.12 : 0.49, max_mm: 0.8, coverage: 0.98 },
      limits: { p95_mm: 0.3, max_mm: 1, coverage_min: 0.85 },
      checks: { p95: status === "matches" ? "pass" : "fail", max: "pass", coverage: "pass" },
    }],
  };
}

const SHEET: [number, number] = [297, 210];

// A light page image with a frame and a title block, so the sheet is visibly marked as simulated.
const PAGE_SVG = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 297 210">
<rect width="297" height="210" fill="#fff"/>
<rect x="10" y="10" width="277" height="190" fill="none" stroke="#000" stroke-width=".5"/>
<rect x="187" y="175" width="100" height="25" fill="none" stroke="#000" stroke-width=".35"/>
<text x="192" y="186" font-family="sans-serif" font-size="6" font-weight="700">SIMULATED</text>
<text x="192" y="195" font-family="sans-serif" font-size="4">Synthetic plate · no customer data</text>
</svg>`;

const line = (id: number, kind: Stroke["kind"], p0: [number, number], p1: [number, number]): Stroke =>
  ({ id, kind, width_mm: kind === "contour" ? 0.5 : 0.25, type: "line", p0, p1 });

/** Front view (plate outline with a hole) and top view (thickness band). */
function plateDrawing(filename: string): Drawing {
  const strokes: Stroke[] = [
    line(1, "contour", [40, 40], [160, 40]), line(2, "contour", [160, 40], [160, 120]),
    line(3, "contour", [160, 120], [40, 120]), line(4, "contour", [40, 120], [40, 40]),
    { id: 5, kind: "contour", width_mm: 0.5, type: "circle", center: [100, 80], radius: 10 },
    line(6, "centerline", [85, 80], [115, 80]), line(7, "centerline", [100, 65], [100, 95]),
    line(8, "contour", [40, 140], [160, 140]), line(9, "contour", [160, 140], [160, 150]),
    line(10, "contour", [160, 150], [40, 150]), line(11, "contour", [40, 150], [40, 140]),
    line(12, "hidden", [90, 140], [90, 150]), line(13, "hidden", [110, 140], [110, 150]),
    line(14, "dimension", [40, 30], [160, 30]), line(15, "extension", [40, 38], [40, 27]),
    line(16, "extension", [160, 38], [160, 27]), line(17, "dimension", [170, 40], [170, 120]),
    line(18, "unclear", [150, 112], [158, 118]),
  ];
  const byKind: Drawing["summary"]["by_kind"] = {};
  for (const s of strokes) byKind[s.kind] = (byKind[s.kind] ?? 0) + 1;
  return {
    schema_version: 1,
    source: filename,
    sheet_size_mm: SHEET,
    summary: { strokes: strokes.length, by_kind: byKind, views: 2, text_blocks: 3 },
    views: [
      { id: 1, bbox: [36, 24, 176, 124], is_iso: false, stroke_ids: [1, 2, 3, 4, 5, 6, 7, 14, 15, 16, 17, 18] },
      { id: 2, bbox: [36, 136, 164, 154], is_iso: false, stroke_ids: [8, 9, 10, 11, 12, 13] },
    ],
    text_blocks: [
      { id: 1, text: "120", angle_deg: 0, bbox: [94, 24, 106, 29], glyph_count: 3 },
      { id: 2, text: "80", angle_deg: 90, bbox: [172, 75, 177, 85], glyph_count: 2 },
      { id: 3, text: "Ø20", angle_deg: 0, bbox: [112, 66, 124, 71], glyph_count: 3 },
    ],
    strokes,
  };
}

export function fixtureAnalysis(filename: string): ExtractResult {
  return {
    drawing: plateDrawing(filename),
    page_png: "data:image/svg+xml;charset=utf-8," + encodeURIComponent(PAGE_SVG),
    page_px_per_mm: 4,
    review: [{
      id: "strokes-18",
      kind: "unclear_strokes",
      message: "1 stroke(s) without a certain meaning",
      bbox: [150, 112, 158, 118],
      stroke_ids: [18],
      text: null,
      decision: null,
    }],
  };
}

export const fixtureParameters = (): Parameter[] => [
  { name: "length", value: 120, unit: "mm", origin: "source", editable: true, feature: "base_plate" },
  { name: "width", value: 80, unit: "mm", origin: "source", editable: true, feature: "base_plate" },
  { name: "thickness", value: 10, unit: "mm", origin: "assumed", editable: true, feature: "base_plate" },
  { name: "hole_diameter", value: 20, unit: "mm", origin: "source", editable: true, feature: "center_hole" },
  { name: "corner_radius", value: 5, unit: "mm", origin: "assumed", editable: true, feature: "corner_fillet" },
];

export const FIXTURE_OPERATIONS: Operation[] = [
  { index: 1, kind: "extrude", label: "Extrude base plate", parameters: ["length", "width", "thickness"] },
  { index: 2, kind: "hole", label: "Center hole", parameters: ["hole_diameter"] },
  { index: 3, kind: "fillet", label: "Fillet bottom right corner", parameters: ["corner_radius"] },
];

export const FIXTURE_ASSUMPTIONS: Assumption[] = [
  {
    id: "A1", feature: "base_plate", parameter: "thickness", value: 10, unit: "mm",
    reason: "Thickness not dimensioned; measured from the top view at scale 1:1.", source_region: [36, 136, 164, 154],
  },
  {
    id: "A2", feature: "corner_fillet", parameter: "corner_radius", value: 5, unit: "mm",
    reason: "Radius without dimension; estimated from the arc at the corner.", source_region: [150, 112, 158, 118],
  },
];

export const FIXTURE_UNCERTAINTIES: Uncertainty[] = [
  { id: "U1", feature: "corner_fillet", message: "Stroke at the corner not assignable to a class with certainty.", source_region: [150, 112, 158, 118] },
];

export function fixtureValidation(failed: boolean): ValidationResult[] {
  return [
    { check: "solid_valid", status: "pass", detail: "One closed solid." },
    { check: "dimensions_match", status: "pass", detail: "All source dimensions within ±0.01 mm." },
    failed
      ? { check: "step_reimport", status: "fail", detail: "STEP reimport in a fresh worker gave a different volume." }
      : { check: "step_reimport", status: "pass", detail: "STEP reimported and checked in a fresh worker." },
    { check: "target_cad_open", status: "not_tested", detail: "Opening in the target CAD not tested." },
  ];
}

// Synthetic PNG with grey source lines, blue model lines, and a red deviation marker.
export const FIXTURE_PROJECTION_PNG = "iVBORw0KGgoAAAANSUhEUgAAASkAAADSCAIAAACZ2aG7AAAAOXRFWHREZXNjcmlwdGlvbgBTSU1VTEFURUQgT1ZFUkxBWSAtIG5vdCB2ZXJpZmljYXRpb24gZXZpZGVuY2XVHnOuAAACVElEQVR42u3VQQqAIBCG0TlnR/RM3qUCYWjRMhzJ93BRW38+jBOoEK4AtAfaA7QH2gO0B9oDtAfaA7QH2gO0B9oD7QHaA+0B2gPtAdoD7QHaA+0B2gPtgfYA7YH2AO2B9gDtgfYA7YH2AO2B9gDtgfZAe4D2QHuA9kB7gPZAe4D2QHuA9kB7oD1Ae6A9QHugPUB7oD1Ae6A9VtUjxnEV2mN2eM8PtMe88F5/+XN7rbU4ulN17tLyO/PTw0btGaD23csVvHvaY3Z+4w0UnvYoyE942sMK2rO69tAeVtCe1bWH9rCC9qyuPbSHFbRnde2hPaygPatrD+1hBe1hBe1ZXXtoDytoz+raQ3tYQXtW1x7awwras7r20B5W0J7VtYf2sIL2rK497Vlde2gPK2jP6tpDe1hBe1bXHtrDCtqzuvbQHlbQntW1h/awgvasrj20pz0raA8raM/q2kN7WEF7Vtce2sMK2rO69tAeVtCe1bWH9rCC9qyuPbSHFbSH9rRnde2hPaygPatrD+1hBe19s7qzwpHBXu2B9gDtgfYA7YH2AO2B9gDtgfYA7YH2AO2B9kB7gPZAe4D2QHuA9kB7gPZAe4D2QHugPUB7oD1Ae6A9QHugPUB7oD1Ae6A90J4rAO2B9gDtgfYA7YH2AO2B9gDtgfYA7YH2QHuA9kB7gPZAe4D2QHuA9kB7gPZAe6A9QHugPUB7oD1Ae6A9QHugPUB7oD1Ae6A90B6gPdAeoD3QHqA90B6gPdAeoD3QHmgP0B5oD9AeaA/QHmgP0B5oD9AeLOICOrQI2hBmP1kAAAAASUVORK5CYII=";
