// Synthetic service responses test presentation only. They do not prove CAD or release acceptance.
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";
import { ArtifactsPanel } from "../../components/run/ArtifactsPanel";
import { ReviewPanel } from "../../components/run/ReviewPanel";
import type { Artifact, Run } from "../contract";
import { delivery, isReleased, lastResultArtifacts, lastResultModel, latestShown } from "../release";
import { runStatus } from "../status";

vi.mock("@/lib/apiContext", () => ({ useApi: () => ({}) }));
vi.mock("@/lib/artifacts", () => ({ useArtifactUrl: (_api: unknown, id: string) => ({ url: "blob:" + id, error: null }) }));
vi.mock("@/components/ModelPanel", () => ({ ModelFrame: ({ url, name }: { url: string; name: string }) => <div data-model-url={url}>{name}</div> }));

const EXTENSIONS: Partial<Record<Artifact["role"], string>> = { step_candidate: ".step", drawing_dxf: ".dxf", verification_report: ".json", verification_preview: ".png" };
const artifact = (id: string, role: Artifact["role"], revision = 1): Artifact => ({
  artifact_id: id, role, filename: id + (EXTENSIONS[role] ?? ".pdf"), model_revision: revision,
  media_type: "application/octet-stream", byte_count: 100, sha256: "0".repeat(64), source_sha256: "1".repeat(64), released: false,
  release_status: "not_released", reason: "Drawing verification failed: DIM-06.",
});
function failedRun(): Run {
  return {
    run_id: "run_synthetic", source_id: "src_synthetic", phase: "failed", failed_phase: "validating", simulated: false,
    job: { job_id: "job", status: "failed", progress: 0.8, started_at: "2026-10-23T10:00:00Z", finished_at: null },
    error: { code: "DRAWING_UNVERIFIED", message: "Drawing verification failed.", field: null, recovery: null },
    part: { revision: 2, parameters: [], operations: [], capabilities: { parameter_edit: false } },
    review: { release_state: "blocked", assumptions: [], uncertainties: [], validation: [] },
    artifacts: [artifact("old-model", "step_candidate"), artifact("last-drawing", "drawing_pdf"), artifact("last-dxf", "drawing_dxf"),
      artifact("last-report", "verification_report"), artifact("last-preview", "verification_preview")],
    last_results: { released: false, failed_phase: "validating", reason: "Drawing verification failed: DIM-06.",
      blocking: [{ rule_id: "DIM-06", feature: "base", status: "fail", message: "A required dimension is missing." }],
      artifact_ids: ["old-model", "last-drawing", "last-dxf", "last-report", "last-preview"],
      model: { artifact_id: "old-model", model_revision: 1, validation: [{ check: "solid_validity", status: "pass", detail: "One valid solid." },
        { check: "target_cad_open", status: "not_tested", detail: "Not tested." }] }, no_model_reason: null },
  };
}
function render(run: Run) {
  const client = new QueryClient();
  client.setQueryData(["capabilities"], { downloads: true, model_preview: true });
  return renderToStaticMarkup(<QueryClientProvider client={client}><ArtifactsPanel run={run} /></QueryClientProvider>);
}

describe("last results presentation", () => {
  it("shows selected historical outputs, failed phase, blocking findings and model validation as not released", () => {
    const html = render(failedRun());
    expect(html).toContain('aria-label="Last results (not released)"');
    expect(html).toContain("Failed phase: checking");
    expect(html).toContain("DIM-06");
    expect(html).toContain("A required dimension is missing.");
    expect(html).toContain("Last validated build · Rev. 1 · not released");
    expect(html).toContain("solid_validity · pass · One valid solid.");
    expect(html).toContain("target_cad_open · not tested · Not tested.");
    for (const id of ["old-model.step", "last-drawing.pdf", "last-dxf.dxf", "last-report.json", "last-preview.png"]) {
      expect(html).toContain('aria-label="Download ' + id + '"');
      expect(html).not.toContain('disabled="" aria-label="Download ' + id + '"');
    }
    expect(html).toContain('data-model-url="blob:old-model"');
    expect(html).toContain("old-model.step · not released");
    expect(html).toContain('data="blob:last-drawing"');
    expect(html).toContain('src="blob:last-preview"');
    expect(html).not.toContain("outdated");
    expect(html).not.toContain("Released: model");
  });

  it("uses only API-selected model IDs and does not replace a historical candidate with the newest artifact", () => {
    const run = failedRun();
    run.artifacts.push(artifact("new-unselected", "step_candidate", 2));
    expect(lastResultModel(run)?.artifact_id).toBe("old-model");
    expect(lastResultArtifacts(run).map((a) => a.artifact_id)).not.toContain("new-unselected");
    expect(latestShown(run, "step_candidate")).toBeUndefined();
    expect(render(run)).not.toContain('data-model-url="blob:new-unselected"');
  });

  it("states that no STEP exists when the run failed before its first valid build", () => {
    const run = failedRun();
    run.artifacts = [];
    run.last_results = { ...run.last_results!, artifact_ids: [], model: null, failed_phase: "modeling", no_model_reason: "No validated build exists." };
    const html = render(run);
    expect(html).toContain("No STEP model is available: No validated build exists.");
    expect(html).toContain("Failed phase: building model");
    expect(html).not.toContain("Download");
    expect(html).not.toContain("data-model-url");
    expect(html).not.toContain("Last validated build");
  });

  it("keeps older responses without last_results compatible", () => {
    const run = failedRun();
    delete run.last_results;
    expect(render(run)).not.toContain("Last results (not released)");
  });
});

describe("candidate release isolation", () => {
  it.each([true, undefined])("excludes candidate roles even when released is %s", (released) => {
    const run = failedRun();
    delete run.last_results;
    run.phase = "done";
    run.job.status = "succeeded";
    run.review!.release_state = "released";
    const candidate = { ...artifact("candidate", "step_candidate", 2), released, release_status: undefined };
    const step = { ...artifact("released-step", "step", 2), released: true, release_status: undefined };
    run.artifacts = [step, candidate];
    const state = delivery(run);
    expect(state.released).toBe(true);
    expect(isReleased(state, run, candidate)).toBe(false);
    expect(isReleased(state, run, step)).toBe(true);
    expect(latestShown(run, "step_candidate")).toBeUndefined();
    run.artifacts = [candidate, { ...artifact("pdf", "drawing_pdf", 2), released: true, release_status: undefined }];
    expect(delivery(run).released).toBe(false);
    expect(runStatus(run)).toEqual(["flag", "not released"]);
    const review = renderToStaticMarkup(<ReviewPanel run={run} />);
    expect(review).not.toContain(">released<");
  });

  it("does not trust released flags on selected last results", () => {
    const run = failedRun();
    run.phase = "done";
    run.job.status = "succeeded";
    run.review!.release_state = "released";
    run.artifacts = run.artifacts.map((a) => ({ ...a, released: true, release_status: undefined, model_revision: 2 }));
    expect(delivery(run).released).toBe(false);
    expect(run.artifacts.some((a) => isReleased({ released: true, revisionsAgree: true, reasons: [] }, run, a))).toBe(false);
    expect(render(run)).not.toContain("Released: model");
  });
});

describe("drawing status and release membership", () => {
  it.each(["accepted", "failed"] as const)("keeps an %s drawing separate from a STEP-only release", (status) => {
    const run = failedRun();
    delete run.last_results;
    run.phase = "done";
    run.job.status = "succeeded";
    run.error = null;
    run.review!.release_state = "released";
    run.review!.drawing = { status, reason: null, current: true, delivery: "step_only", pair_current: null };
    run.artifacts = [
      { ...artifact("released-step", "step", 2), released: true, release_status: undefined },
      { ...artifact("unreleased-drawing", "drawing_pdf", 2), released: false },
    ];
    const html = render(run);
    expect(html).toContain("Released: model of revision 2");
    expect(html).toContain(status === "accepted" ? "Drawing reviewed and verified." : "Drawing faulty. The diagnostic files are not released.");
    expect(html).not.toContain("Drawing reviewed, verified, and released.");
    expect(html).not.toContain("diagnostic files belong to the release");
    expect(html).toContain("Drawing · Rev. 2 · draft, not released");
    const drawingRow = html.slice(html.indexOf("Technical drawing (PDF)"), html.indexOf("Download unreleased-drawing.pdf"));
    expect(drawingRow).toContain(">not released<");
    expect(drawingRow).not.toContain(">released<");
  });
});
