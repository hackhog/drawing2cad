// Synthetic contract fixtures. They describe a fictitious plate, not a customer part.
// Simulated data does not establish end-to-end acceptance.
import type { Assumption, Operation, Parameter, Uncertainty, ValidationResult } from "./contract";
import type { Drawing, ExtractResult, Stroke } from "./drawing";

const SHEET: [number, number] = [297, 210];

// A light page image with a frame and a title block, so the sheet is visibly marked as simulated.
const PAGE_SVG = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 297 210">
<rect width="297" height="210" fill="#fff"/>
<rect x="10" y="10" width="277" height="190" fill="none" stroke="#000" stroke-width=".5"/>
<rect x="187" y="175" width="100" height="25" fill="none" stroke="#000" stroke-width=".35"/>
<text x="192" y="186" font-family="sans-serif" font-size="6" font-weight="700">SIMULIERT</text>
<text x="192" y="195" font-family="sans-serif" font-size="4">Synthetische Platte · keine Kundendaten</text>
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
      kind: "unclear_strokes",
      message: "1 Strich ohne sichere Klasse (Ecke rechts unten)",
      bbox: [150, 112, 158, 118],
      stroke_ids: [18],
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
  { index: 1, kind: "extrude", label: "Grundplatte extrudieren", parameters: ["length", "width", "thickness"] },
  { index: 2, kind: "hole", label: "Mittelbohrung", parameters: ["hole_diameter"] },
  { index: 3, kind: "fillet", label: "Ecke rechts unten verrunden", parameters: ["corner_radius"] },
];

export const FIXTURE_ASSUMPTIONS: Assumption[] = [
  {
    id: "A1", feature: "base_plate", parameter: "thickness", value: 10, unit: "mm",
    reason: "Dicke nicht bemaßt; aus der Draufsicht im Maßstab 1:1 gemessen.", source_region: [36, 136, 164, 154],
  },
  {
    id: "A2", feature: "corner_fillet", parameter: "corner_radius", value: 5, unit: "mm",
    reason: "Radius ohne Maß; aus dem Bogen an der Ecke geschätzt.", source_region: [150, 112, 158, 118],
  },
];

export const FIXTURE_UNCERTAINTIES: Uncertainty[] = [
  { id: "U1", feature: "corner_fillet", message: "Strich an der Ecke keiner Klasse sicher zuordenbar.", source_region: [150, 112, 158, 118] },
];

export function fixtureValidation(failed: boolean): ValidationResult[] {
  return [
    { check: "solid_valid", status: "pass", detail: "Ein geschlossener Körper." },
    { check: "dimensions_match", status: "pass", detail: "Alle Quellmaße innerhalb ±0,01 mm." },
    failed
      ? { check: "step_reimport", status: "fail", detail: "STEP-Reimport im frischen Worker ergab abweichendes Volumen." }
      : { check: "step_reimport", status: "pass", detail: "STEP im frischen Worker neu eingelesen und geprüft." },
    { check: "target_cad_open", status: "not_tested", detail: "Öffnen im Ziel-CAD nicht geprüft." },
  ];
}
