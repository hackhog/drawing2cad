// Benefit figures of the overview: what the CAD runs delivered across all drawings, and what they save
// compared with a manual rebuild. Each drawing counts with its latest run, the same run that the drawing page shows.
import type { Estimator, Measurement, Run } from "./contract";
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
  const durations = finished.flatMap((run) => runSeconds(run) ?? []);
  return {
    models: finished.filter((run) => run.artifacts.some((a) => a.role === "step" && a.model_revision === run.part?.revision)).length,
    released: finished.filter((run) => delivery(run).released).length,
    fromDrawing: parameters.filter((p) => p.origin === "source").length,
    parameters: parameters.length,
    assumed: parameters.filter((p) => p.origin === "assumed").length,
    medianSeconds: median(durations),
    active: latest.length - finished.length,
    simulated: latest.some((run) => run.simulated),
  };
}

/** Start-to-finish time of a succeeded run, in seconds; null for any other run. */
export function runSeconds(run: Run): number | null {
  if (run.job.status !== "succeeded" || !run.job.finished_at) return null;
  return (Date.parse(run.job.finished_at) - Date.parse(run.job.started_at)) / 1000;
}

export function median(values: number[]): number | null {
  if (!values.length) return null;
  const sorted = [...values].sort((a, b) => a - b);
  const mid = sorted.length >> 1;
  return sorted.length % 2 ? sorted[mid] : (sorted[mid - 1] + sorted[mid]) / 2;
}

const mean = (values: number[]) => (values.length ? values.reduce((a, b) => a + b, 0) / values.length : null);

/** Human effort from the review measurements: measured review time and estimated manual rebuild time. */
export interface Effort {
  reviews: number;
  /** Median stopwatch time of all reviews, in seconds; null without a review. */
  reviewSeconds: number | null;
  estimates: number;
  /** Mean estimated manual rebuild time, in hours; null without an estimate. */
  manualHours: number | null;
  estimators: Estimator[];
}

export function effort(measurements: Measurement[]): Effort {
  const estimated = measurements.filter((m) => m.manual_hours !== null);
  return {
    reviews: measurements.length,
    reviewSeconds: median(measurements.map((m) => m.review_seconds)),
    estimates: estimated.length,
    manualHours: mean(estimated.map((m) => m.manual_hours!)),
    estimators: [...new Set(estimated.flatMap((m) => m.estimator ?? []))],
  };
}

/** Values that the user sets. The manual effort applies only while no measured estimate exists. */
export interface Assumptions { hourlyRate: number; manualHours: number }

export interface Saving {
  /** Manual rebuild time per part, in hours, and whether it is the assumption instead of measured estimates. */
  manualHours: number;
  manualAssumed: boolean;
  /** Machine time plus review time per part, in seconds. */
  toolSeconds: number;
  /** Manual time divided by the time with the tool. */
  factor: number;
  /** Saved hours and euros for all drawings with a STEP model. */
  hours: number;
  euros: number;
}

/** The time saving per part and for all built parts; null without a measured machine time and review time. */
export function saving(built: Benefit, human: Effort, assumptions: Assumptions): Saving | null {
  if (built.medianSeconds === null || human.reviewSeconds === null) return null;
  const manualHours = human.manualHours ?? assumptions.manualHours;
  const toolSeconds = built.medianSeconds + human.reviewSeconds;
  const hours = (built.models * (manualHours * 3600 - toolSeconds)) / 3600;
  return {
    manualHours, manualAssumed: human.manualHours === null, toolSeconds,
    factor: (manualHours * 3600) / toolSeconds, hours, euros: hours * assumptions.hourlyRate,
  };
}

const csvCell = (value: string | number | null) => {
  const text = value === null ? "" : String(value);
  return /[";\n]/.test(text) ? `"${text.replaceAll('"', '""')}"` : text;
};

/** One CSV row per measurement, with the machine time of the latest run of its drawing. Separator ";" for German Excel. */
export function measurementsCsv(measurements: Measurement[], drawings: Map<string, { name: string; machineSeconds: number | null }>): string {
  const rows = measurements.map((m) => {
    const drawing = drawings.get(m.source_id);
    const machine = drawing?.machineSeconds ?? null;
    return [drawing?.name ?? m.source_id, machine === null ? null : Math.round(machine), Math.round(m.review_seconds),
      m.manual_hours, m.estimator, m.recorded_at];
  });
  return [["drawing", "machine_s", "review_s", "manual_h", "estimator", "recorded"], ...rows]
    .map((row) => row.map(csvCell).join(";")).join("\n");
}
