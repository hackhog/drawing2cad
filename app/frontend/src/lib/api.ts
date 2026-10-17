// Typen und Aufrufe der Demo-API (app/backend/src/drawing_demo/api.py). Koordinaten in Blatt-mm, y nach unten.

export type Box = [number, number, number, number];
export type Point = [number, number];

export type StrokeKind =
  | "contour" | "hidden" | "centerline" | "hatch" | "dimension"
  | "arrow" | "extension" | "cutting_plane" | "unclear";

interface StrokeBase { id: number; kind: StrokeKind; width_mm: number }
export type Stroke =
  | (StrokeBase & { type: "line"; p0: Point; p1: Point })
  | (StrokeBase & { type: "circle"; center: Point; radius: number })
  | (StrokeBase & { type: "arc"; center: Point; radius: number; start_deg: number; sweep_deg: number });

export interface Drawing {
  schema_version: number;
  source: string;
  sheet_size_mm: [number, number];
  summary: { strokes: number; by_kind: Partial<Record<StrokeKind, number>>; views: number; text_blocks: number };
  views: { id: number; bbox: Box; is_iso: boolean; stroke_ids: number[] }[];
  text_blocks: { id: number; text: string; angle_deg: number; bbox: Box; glyph_count: number }[];
  strokes: Stroke[];
}

export interface ReviewFlag {
  kind: "no_views" | "unclear_strokes" | "unreadable_text" | string;
  message: string;
  bbox: Box | null;
  stroke_ids: number[];
}

export interface ExtractResult {
  drawing: Drawing;
  page_png: string;
  page_px_per_mm: number;
  review: ReviewFlag[];
}

async function post(path: string, file: File): Promise<Response> {
  const body = new FormData();
  body.append("file", file);
  const res = await fetch(path, { method: "POST", body });
  if (!res.ok) {
    const detail = await res.json().then((j: { detail?: string }) => j.detail, () => undefined);
    throw new Error(detail || res.statusText);
  }
  return res;
}

// Relative Pfade, damit die App auch hinter einem Pfad-Präfix läuft
export const extractDrawing = async (pdf: File): Promise<ExtractResult> => (await post("api/extract", pdf)).json();

/** STEP → GLB (serverseitig vernetzt), Rückgabe als Object-URL für den Viewer. */
export async function stepToGlbUrl(step: File): Promise<string> {
  const glb = await (await post("api/model", step)).blob();
  return URL.createObjectURL(glb);
}
