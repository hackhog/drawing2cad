// Benefit figures of the overview, from synthetic runs.
import { describe, expect, it } from "vitest";
import { benefit, effort, measurementsCsv, saving } from "../benefit";
import type { Artifact, JobStatus, Measurement, Parameter, ReleaseState, Run } from "../contract";

const param = (name: string, origin: Parameter["origin"]): Parameter =>
  ({ name, value: 10, unit: "mm", origin, editable: true, feature: "base" });

const step = (revision: number): Artifact => ({
  artifact_id: `art_${revision}`, role: "step", media_type: "model/step", filename: "part.stp", sha256: "0".repeat(64),
  byte_count: 1, source_sha256: "1".repeat(64), model_revision: revision,
});

function run(status: JobStatus, seconds: number, opts: { release?: ReleaseState; params?: Parameter[]; artifacts?: Artifact[]; simulated?: boolean } = {}): Run {
  const done = status !== "queued" && status !== "running";
  return {
    run_id: `run_${seconds}`, source_id: "src_synthetic", phase: done ? "done" : "modeling",
    job: {
      job_id: "job", status, progress: null, started_at: "2026-01-01T00:00:00Z",
      finished_at: done ? new Date(Date.parse("2026-01-01T00:00:00Z") + seconds * 1000).toISOString() : null,
    },
    part: { revision: 1, parameters: opts.params ?? [], operations: [], capabilities: { parameter_edit: true } },
    artifacts: opts.artifacts ?? [],
    review: { release_state: opts.release ?? "draft", assumptions: [], uncertainties: [], validation: [] },
    error: null, simulated: opts.simulated ?? false,
  };
}

describe("benefit", () => {
  it("counts each drawing with its latest run", () => {
    const b = benefit([
      [run("failed", 5), run("succeeded", 60, { release: "released", artifacts: [step(1)], params: [param("l", "source"), param("r", "assumed")] })],
      [run("succeeded", 120, { artifacts: [step(1)], params: [param("d", "source")] })],
      [run("succeeded", 90, { artifacts: [step(1)] }), run("running", 0)],
      [],
    ]);
    expect(b).toMatchObject({ models: 2, released: 1, fromDrawing: 2, parameters: 3, assumed: 1, active: 1, simulated: false });
    expect(b.medianSeconds).toBe(90);
  });

  it("ignores a STEP model of an older revision", () => {
    expect(benefit([[run("succeeded", 10, { artifacts: [step(0)] })]]).models).toBe(0);
  });

  it("has no duration without a finished run and reports simulated runs", () => {
    const b = benefit([[run("failed", 10, { simulated: true })]]);
    expect(b.medianSeconds).toBeNull();
    expect(b.simulated).toBe(true);
  });
});

const measurement = (source: string, seconds: number, hours: number | null = null, estimator: Measurement["estimator"] = null): Measurement => ({
  measurement_id: `msr_${source}_${seconds}`, source_id: source, review_seconds: seconds, manual_hours: hours, estimator,
  recorded_at: "2026-01-01T00:00:00Z",
});

describe("effort", () => {
  it("takes the median review time and the mean of the estimates only", () => {
    const e = effort([measurement("a", 60, 2, "drafter"), measurement("b", 200), measurement("c", 100, 4, "guest"), measurement("d", 90, 3, "drafter")]);
    expect(e).toEqual({ reviews: 4, reviewSeconds: 95, estimates: 3, manualHours: 3, estimators: ["drafter", "guest"] });
  });

  it("has no values without measurements", () => {
    expect(effort([])).toEqual({ reviews: 0, reviewSeconds: null, estimates: 0, manualHours: null, estimators: [] });
  });
});

describe("saving", () => {
  const built = benefit([[run("succeeded", 120, { artifacts: [step(1)] })], [run("succeeded", 120, { artifacts: [step(1)] })]]);
  const assumptions = { hourlyRate: 100, manualHours: 3 };

  it("needs a machine time and a review time", () => {
    expect(saving(benefit([]), effort([measurement("a", 60)]), assumptions)).toBeNull();
    expect(saving(built, effort([]), assumptions)).toBeNull();
  });

  it("uses measured estimates before the assumption", () => {
    const s = saving(built, effort([measurement("a", 240, 1, "drafter")]), assumptions)!;
    // 1 h by hand against 2 min machine + 4 min review, for 2 built parts.
    expect(s.manualAssumed).toBe(false);
    expect(s.toolSeconds).toBe(360);
    expect(s.factor).toBe(10);
    expect(s.hours).toBeCloseTo(1.8);
    expect(s.euros).toBeCloseTo(180);
  });

  it("falls back to the assumption and marks it", () => {
    const s = saving(built, effort([measurement("a", 240)]), assumptions)!;
    expect(s.manualAssumed).toBe(true);
    expect(s.manualHours).toBe(3);
  });
});

describe("measurementsCsv", () => {
  it("writes one row per measurement and quotes cells with a separator", () => {
    const csv = measurementsCsv([measurement("a", 95.4, 2, "drafter"), measurement("x", 30)],
      new Map([["a", { name: "Flansch; groß", machineSeconds: 101.6 }]]));
    expect(csv.split("\n")).toEqual([
      "drawing;machine_s;review_s;manual_h;estimator;recorded",
      '"Flansch; groß";102;95;2;drafter;2026-01-01T00:00:00Z',
      "x;;30;;;2026-01-01T00:00:00Z",
    ]);
  });
});
