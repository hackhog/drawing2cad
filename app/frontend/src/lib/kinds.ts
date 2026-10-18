import type { FlagDecision, StrokeClass, StrokeKind } from "./drawing";

// Keep the established drawing-class colors for the existing UI.
export const KINDS: [StrokeKind, string, string][] = [
  ["contour", "Contour", "#141414"],
  ["hidden", "Hidden", "#965a00"],
  ["centerline", "Centerline", "#00aa50"],
  ["hatch", "Hatch", "#0096dc"],
  ["dimension", "Dimension line", "#e628a0"],
  ["arrow", "Arrow", "#e628a0"],
  ["extension", "Extension line", "#f08cc8"],
  ["cutting_plane", "Cutting plane", "#8c28dc"],
  ["annotation", "Annotation", "#7a7a7a"],
  ["unclear", "Unclear", "#ff0000"],
];
export const OFF_BY_DEFAULT = new Set<StrokeKind>(["hatch"]);

export const FLAG_KIND: Record<string, string> = {
  unclear_strokes: "Strokes not assignable to a class with certainty",
  unreadable_text: "Characters not recognized with certainty",
};

/** Classes that a user can assign to unclear strokes. The last five are unknown to the analysis. */
export const STROKE_CLASSES: [StrokeClass, string][] = [
  ...KINDS.flatMap(([k, label]): [StrokeClass, string][] => (k === "unclear" ? [] : [[k, label]])),
  ["frame", "Frame/title block"],
  ["table", "Table"],
  ["leader", "Leader"],
  ["pitch_circle", "Pitch circle"],
  ["tangent_edge", "Tangent edge"],
];

export function decisionLabel(d: FlagDecision): string {
  if (d.action === "classify") return `→ ${STROKE_CLASSES.find(([k]) => k === d.stroke_class)?.[1] ?? d.stroke_class}`;
  if (d.action === "correct") return `→ “${d.text}”`;
  return "ignored";
}
