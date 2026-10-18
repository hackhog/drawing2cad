// Drawing analysis types of the demo API (app/backend/src/drawing_demo/api.py). Coordinates in sheet mm, Y axis down.

export type Box = [number, number, number, number];
export type Point = [number, number];

export type StrokeKind =
  | "contour" | "hidden" | "centerline" | "hatch" | "dimension"
  | "arrow" | "extension" | "cutting_plane" | "annotation" | "unclear";

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

/** Stroke classes that a user can assign to unclear strokes: the analysis classes and classes the analysis does not know yet. */
export type StrokeClass = Exclude<StrokeKind, "unclear"> | "frame" | "table" | "leader" | "pitch_circle" | "tangent_edge";
export type FlagAction = "ignore" | "classify" | "correct";

/** A user decision on a flag. New agent runs read it through the MCP. */
export interface FlagDecision {
  action: FlagAction;
  stroke_class: StrokeClass | null;
  text: string | null;
  note: string | null;
  decided_at: string;
}

export interface FlagChange { action: FlagAction | "reopen"; stroke_class?: StrokeClass; text?: string; note?: string }

export interface ReviewFlag {
  /** Stable for the same source bytes and analysis version. */
  id: string;
  kind: "no_views" | "unclear_strokes" | "unreadable_text" | string;
  message: string;
  bbox: Box | null;
  stroke_ids: number[];
  /** The extracted text of an unreadable-text flag. */
  text: string | null;
  decision: FlagDecision | null;
}

export interface FlagsPage {
  flags: ReviewFlag[];
  /** Decisions whose flag the current analysis no longer produces. */
  decisions_without_flag: number;
}

export interface ExtractResult {
  drawing: Drawing;
  page_png: string;
  page_px_per_mm: number;
  review: ReviewFlag[];
  provenance?: { source_sha256: string; source_size_bytes: number; drawing2cad_mcp_version: string };
}
