// German status labels for sources, uploads, and runs.
import type { Run, RunPhase } from "./contract";
import type { ExtractResult, ReviewFlag } from "./drawing";
import type { Upload } from "./uploads";

// Status colors of the established UI: wait, run, done, flag (to review), error.
export type Tone = "wait" | "run" | "done" | "flag" | "error";

export function uploadStatus(upload: Upload): [Tone, string] {
  if (upload.state === "wait") return ["wait", "queued"];
  if (upload.state === "send") return ["run", `uploading ${Math.round(upload.progress * 100)}%`];
  if (upload.state === "read") return ["run", "liest"];
  return ["error", "error"];
}

/** Flags without a user decision. `flags` holds the current decisions; the cached analysis has none. */
export function openFlags(analysis: ExtractResult, flags?: ReviewFlag[]): number {
  return (flags ?? analysis.review).filter((f) => !f.decision).length;
}

export function analysisStatus(analysis: ExtractResult | undefined, failed: boolean, flags?: ReviewFlag[]): [Tone, string] {
  if (failed) return ["error", "error"];
  if (!analysis) return ["run", "loading"];
  const n = openFlags(analysis, flags);
  return n ? ["flag", `${n} to review`] : ["done", "done"];
}

export const PHASE_LABEL: Record<RunPhase, string> = {
  queued: "queued", analyzing: "reading drawing", modeling: "building model", drawing: "creating drawing",
  validating: "checking", done: "done", failed: "failed", cancelled: "cancelled",
};

export function runStatus(run: Run): [Tone, string] {
  if (run.phase === "failed" || run.phase === "cancelled") return ["error", PHASE_LABEL[run.phase]];
  if (run.phase !== "done") return ["run", PHASE_LABEL[run.phase]];
  return run.review?.release_state === "released" ? ["done", "released"] : ["flag", "not released"];
}
