import type { ExtractResult } from "./api";

export const fmt = (n: number) => n.toLocaleString("de-DE");
export const pct = (x: number) => `${(x * 100).toLocaleString("de-DE", { maximumFractionDigits: 1 })} %`;
export const partName = (filename: string) => filename.replace(/_dwg\.pdf$/i, "").replace(/\.pdf$/i, "");

export function explainedShare(result: ExtractResult) {
  const { strokes, by_kind: byKind } = result.drawing.summary;
  const explained = strokes - (byKind.unclear ?? 0);
  return { total: strokes, explained, share: strokes ? explained / strokes : 1 };
}
