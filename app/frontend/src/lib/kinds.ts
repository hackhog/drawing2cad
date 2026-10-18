import type { FlagDecision, StrokeClass, StrokeKind } from "./drawing";

// Keep the established drawing-class colors for the existing UI.
export const KINDS: [StrokeKind, string, string][] = [
  ["contour", "Kontur", "#141414"],
  ["hidden", "verdeckt", "#965a00"],
  ["centerline", "Mittellinie", "#00aa50"],
  ["hatch", "Schraffur", "#0096dc"],
  ["dimension", "Maßlinie", "#e628a0"],
  ["arrow", "Pfeil", "#e628a0"],
  ["extension", "Maßhilfslinie", "#f08cc8"],
  ["cutting_plane", "Schnittverlauf", "#8c28dc"],
  ["annotation", "Beschriftung", "#7a7a7a"],
  ["unclear", "unklar", "#ff0000"],
];
export const OFF_BY_DEFAULT = new Set<StrokeKind>(["hatch"]);

export const FLAG_KIND: Record<string, string> = {
  unclear_strokes: "Striche keiner Klasse sicher zuordenbar",
  unreadable_text: "Zeichen nicht sicher erkannt",
};

/** Classes that a user can assign to unclear strokes. The last five are unknown to the analysis. */
export const STROKE_CLASSES: [StrokeClass, string][] = [
  ...KINDS.flatMap(([k, label]): [StrokeClass, string][] => (k === "unclear" ? [] : [[k, label]])),
  ["frame", "Rahmen/Schriftfeld"],
  ["table", "Tabelle"],
  ["leader", "Hinweislinie"],
  ["pitch_circle", "Lochkreis"],
  ["tangent_edge", "Tangentenkante"],
];

export function decisionLabel(d: FlagDecision): string {
  if (d.action === "classify") return `→ ${STROKE_CLASSES.find(([k]) => k === d.stroke_class)?.[1] ?? d.stroke_class}`;
  if (d.action === "correct") return `→ „${d.text}“`;
  return "ignoriert";
}
