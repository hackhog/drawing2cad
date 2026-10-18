import type { Box, Stroke } from "./drawing";

function pt(cx: number, cy: number, r: number, deg: number): [number, number] {
  const a = (deg * Math.PI) / 180;
  return [cx + r * Math.cos(a), cy + r * Math.sin(a)];
}

/** A stroke of the extractor as an SVG path in sheet mm. */
export function strokePath(s: Stroke): string {
  if (s.type === "line") return `M${s.p0[0]} ${s.p0[1]}L${s.p1[0]} ${s.p1[1]}`;
  const [cx, cy] = s.center;
  const r = s.radius;
  if (s.type === "circle") {
    return `M${cx - r} ${cy}A${r} ${r} 0 1 1 ${cx + r} ${cy}A${r} ${r} 0 1 1 ${cx - r} ${cy}`;
  }
  // Angle in the y-down system, positive = clockwise from 3 o'clock (as in the extractor)
  const [x0, y0] = pt(cx, cy, r, s.start_deg);
  const [x1, y1] = pt(cx, cy, r, s.start_deg + s.sweep_deg);
  const large = Math.abs(s.sweep_deg) > 180 ? 1 : 0;
  const sweep = s.sweep_deg > 0 ? 1 : 0;
  return `M${x0} ${y0}A${r} ${r} 0 ${large} ${sweep} ${x1} ${y1}`;
}

/** viewBox [x, y, w, h] around a rectangle [x0, y0, x1, y1] with a margin. */
export const boxToViewBox = ([x0, y0, x1, y1]: Box, margin: number): Box =>
  [x0 - margin, y0 - margin, x1 - x0 + 2 * margin, y1 - y0 + 2 * margin];
