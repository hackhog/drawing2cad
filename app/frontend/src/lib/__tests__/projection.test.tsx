import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";
import { JobCard } from "../../components/run/JobCard";
import { ProjectionSection } from "../../components/run/ProjectionSection";
import type { ProjectionStatus, Run } from "../contract";
import { FixtureApi } from "../fixtureApi";
import { fixtureProjection } from "../fixtures";

vi.mock("@/lib/apiContext", () => ({ useApi: () => ({}) }));
vi.mock("@/lib/artifacts", () => ({ useArtifactUrl: () => ({ url: "blob:synthetic-overlay", error: null }) }));

function run(status: ProjectionStatus): Run {
  return {
    run_id: "run_synthetic", source_id: "src_synthetic", phase: "done", simulated: false, error: null, artifacts: [{ artifact_id: "art_released", role: "step", filename: "model.step", media_type: "model/step",
      sha256: "0".repeat(64), source_sha256: "1".repeat(64), byte_count: 1, model_revision: 1, released: true }],
    job: { job_id: "job", status: "succeeded", progress: 1, started_at: "2026-10-21T12:00:00Z", finished_at: null },
    part: { revision: 1, parameters: [], operations: [], capabilities: { parameter_edit: false } },
    review: { release_state: "released", assumptions: [], uncertainties: [], validation: [] },
    projection: { ...fixtureProjection(status, 1), simulated: false, overlay_artifact_id: "art_synthetic" },
  };
}

describe("source projection review", () => {
  it.each(["matches", "deviates", "not_tested"] as const)("shows %s independently from the release", (status) => {
    const value = run(status);
    const html = renderToStaticMarkup(<ProjectionSection run={value} />);
    expect(html).toContain(status === "not_tested" ? "not tested" : status);
    expect(html).toContain("Does the model match the drawing?");
    expect(html.includes("The release does not prove agreement with the source drawing.")).toBe(status === "not_tested");
  });

  it("crops the full-sheet image to each view and shows exact measurements with limits", () => {
    const html = renderToStaticMarkup(<ProjectionSection run={run("deviates")} />);
    expect(html).toContain('viewBox="20 20 180 120"');
    expect(html).toContain('href="blob:synthetic-overlay"');
    expect(html).toContain("0.490 mm");
    expect(html).toContain("Limit 0.300 mm");
    expect(html).toContain("98.0%");
    expect(html).toContain("Minimum 85.0%");
    expect(html).toContain("Grey = source drawing");
    expect(html).toContain("Blue = built model");
    expect(html).toContain("Red = largest deviations");
  });

  it("keeps an absent image separate from the check and marks simulated evidence", () => {
    const value = run("matches");
    value.projection!.overlay_artifact_id = null;
    value.simulated = true;
    const html = renderToStaticMarkup(<ProjectionSection run={value} />);
    expect(html).toContain("No overlay image");
    expect(html).toContain("Simulated projection data");
    expect(html).not.toContain("Loading projection");
  });

  it("clips only the image when a failed view extends beyond the sheet", () => {
    const value = run("deviates");
    value.projection!.sheet_size_mm = [210, 297];
    value.projection!.views[0].region_sheet_mm = [100, 20, 215, 140];
    const html = renderToStaticMarkup(<ProjectionSection run={value} />);
    expect(html).toContain('viewBox="100 20 110 120"');
    expect(html).toContain("deviates");
    expect(html).toContain("0.490 mm");
  });

  it("keeps metrics for a view entirely outside the sheet and distinguishes duplicate IDs", () => {
    const value = run("deviates");
    const view = value.projection!.views[0];
    value.projection!.views = [view, { ...view, region_sheet_mm: [300, 20, 320, 140] }];
    const html = renderToStaticMarkup(<ProjectionSection run={value} />);
    expect(html).toContain(`aria-label="Projection view ${view.view_id} (1)"`);
    expect(html).toContain(`aria-label="Projection view ${view.view_id} (2)"`);
    expect(html).toContain("The view region is outside the source sheet.");
    expect(html.match(/0\.490 mm/g)?.length).toBeGreaterThanOrEqual(2);
    expect(html).not.toContain('viewBox="300');
  });

  it.each(["matches", "deviates", "not_tested"] as const)("shows %s in the job card", (status) => {
    const html = renderToStaticMarkup(<QueryClientProvider client={new QueryClient()}><JobCard run={run(status)} /></QueryClientProvider>);
    expect(html).toContain('role="group" aria-label="Source drawing agreement"');
    expect(html).toContain(status === "not_tested" ? "not tested" : status);
    expect(html).toContain("released");
  });

  it("treats older servers without projection data as not tested", () => {
    const value = run("matches");
    delete value.projection;
    const html = renderToStaticMarkup(<ProjectionSection run={value} />);
    expect(html).toContain("not tested");
    expect(html).toContain("The release does not prove agreement");
  });

  it("shows a missing report as a warning and keeps the released run successful", () => {
    const value = run("matches");
    value.warning = {
      code: "AGENT_REPORT_MISSING",
      message: "Final report missing: RuntimeError: Model endpoint returned HTTP 429",
    };
    const html = renderToStaticMarkup(<QueryClientProvider client={new QueryClient()}><JobCard run={value} /></QueryClientProvider>);
    expect(html).toContain("Hinweis: Abschlussbericht fehlt");
    expect(html).toContain("Freigabe erfolgt; nur der Abschlussbericht fehlt.");
    expect(html).toContain("Die Dateien sind freigegeben. Der Lauf ist erfolgreich abgeschlossen.");
    expect(html).toContain("HTTP 429");
    expect(html).toContain("released");
    expect(html).not.toContain("text-destructive");
  });

  it("shows no report warning for an older run without the warning field", () => {
    const html = renderToStaticMarkup(<QueryClientProvider client={new QueryClient()}><JobCard run={run("matches")} /></QueryClientProvider>);
    expect(html).not.toContain("Abschlussbericht fehlt");
    expect(html).toContain("released");
  });
});

describe("simulated projection service", () => {
  it.each(["matches", "deviates", "not_tested"] as const)("supplies %s with simulation labels", async (status) => {
    let now = 0;
    const api = new FixtureApi({ projection: status, latencyMs: 0, phaseMs: 1, now: () => now });
    const source = await api.uploadSource(new File(["%PDF-1.7"], "plate.pdf"), () => {});
    const created = await api.createRun(source.source_id);
    now = 20;
    const finished = await api.getRun(created.run_id);
    expect(finished.projection).toMatchObject({ status, revision: 1, simulated: true });
    if (status !== "not_tested") {
      const overlay = await api.readArtifact(finished.projection!.overlay_artifact_id!);
      expect(overlay.type).toBe("image/png");
      expect(Array.from(new Uint8Array(await overlay.arrayBuffer()).slice(0, 8))).toEqual([137, 80, 78, 71, 13, 10, 26, 10]);
      expect(finished.artifacts.find((artifact) => artifact.artifact_id === finished.projection!.overlay_artifact_id)?.filename).toMatch(/\.png$/);
    }
    const changed = await api.changeParameters(created.run_id, 1, [{ name: "length", value: 140 }]);
    expect(changed.projection).toMatchObject({ status: "not_tested", revision: 2 });
  });
});
