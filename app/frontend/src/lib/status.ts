// German status labels for sources, uploads, and runs.
import type { Run, RunPhase } from "./contract";
import type { ExtractResult } from "./drawing";
import type { Upload } from "./uploads";

// Status colors of the established UI: wait, run, done, flag (to review), error.
export type Tone = "wait" | "run" | "done" | "flag" | "error";

export function uploadStatus(upload: Upload): [Tone, string] {
  if (upload.state === "wait") return ["wait", "wartet"];
  if (upload.state === "send") return ["run", `lädt ${Math.round(upload.progress * 100)} %`];
  if (upload.state === "read") return ["run", "liest"];
  return ["error", "Fehler"];
}

export function analysisStatus(analysis: ExtractResult | undefined, failed: boolean): [Tone, string] {
  if (failed) return ["error", "Fehler"];
  if (!analysis) return ["run", "lädt"];
  const n = analysis.review.length;
  return n ? ["flag", `${n} prüfen`] : ["done", "fertig"];
}

export const PHASE_LABEL: Record<RunPhase, string> = {
  queued: "wartet", analyzing: "liest Zeichnung", modeling: "baut Modell", drawing: "erstellt Zeichnung",
  validating: "prüft", done: "fertig", failed: "fehlgeschlagen", cancelled: "abgebrochen",
};

export function runStatus(run: Run): [Tone, string] {
  if (run.phase === "failed" || run.phase === "cancelled") return ["error", PHASE_LABEL[run.phase]];
  if (run.phase !== "done") return ["run", PHASE_LABEL[run.phase]];
  return run.review?.release_state === "released" ? ["done", "freigegeben"] : ["flag", "nicht freigegeben"];
}
