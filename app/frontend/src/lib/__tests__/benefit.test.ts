// Benefit figures of the overview, from synthetic runs.
import { describe, expect, it } from "vitest";
import { benefit } from "../benefit";
import type { Artifact, JobStatus, Parameter, ReleaseState, Run } from "../contract";

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
