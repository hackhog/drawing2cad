// Benefit figures of the overview: what the CAD runs delivered across all drawings.
// Each drawing counts with its latest run, the same run that the drawing page shows.
import type { Run } from "./contract";
import { delivery, isActive } from "./release";

export interface Benefit {
  /** Drawings with a STEP model of the current part revision. */
  models: number;
  /** Drawings whose latest run the service released. */
  released: number;
  /** Parameters read from the drawing, of all parameters of the latest parts. */
  fromDrawing: number;
  parameters: number;
  assumed: number;
  /** Median duration from start to finish of the finished runs, in seconds; null without one. */
  medianSeconds: number | null;
  active: number;
  simulated: boolean;
}

export function benefit(runsBySource: Run[][]): Benefit {
  const latest = runsBySource.flatMap((runs) => (runs.length ? [runs[runs.length - 1]] : []));
  const finished = latest.filter((run) => !isActive(run));
  const parameters = finished.flatMap((run) => run.part?.parameters ?? []);
  const durations = finished
    .filter((run) => run.job.status === "succeeded" && run.job.finished_at)
    .map((run) => (Date.parse(run.job.finished_at!) - Date.parse(run.job.started_at)) / 1000)
    .sort((a, b) => a - b);
  const mid = durations.length >> 1;
  return {
    models: finished.filter((run) => run.artifacts.some((a) => a.role === "step" && a.model_revision === run.part?.revision)).length,
    released: finished.filter((run) => delivery(run).released).length,
    fromDrawing: parameters.filter((p) => p.origin === "source").length,
    parameters: parameters.length,
    assumed: parameters.filter((p) => p.origin === "assumed").length,
    medianSeconds: !durations.length ? null : durations.length % 2 ? durations[mid] : (durations[mid - 1] + durations[mid]) / 2,
    active: latest.length - finished.length,
    simulated: latest.some((run) => run.simulated),
  };
}
