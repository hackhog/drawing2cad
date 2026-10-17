// Behavior of the simulated service that the UI depends on. These tests do not establish
// end-to-end acceptance; the real shared services replace the fixture for that.
import { describe, expect, it } from "vitest";
import { ApiFailure } from "../errors";
import { FixtureApi } from "../fixtureApi";
import type { Artifact } from "../contract";
import { delivery, isReleased, latestShown } from "../release";

const pdf = (name = "platte.pdf") => new File(["%PDF-1.7\n%synthetic\n"], name, { type: "application/pdf" });

function setup() {
  let clock = 0;
  const api = new FixtureApi({ now: () => clock, phaseMs: 10, latencyMs: 0 });
  return { api, advance: (ms: number) => { clock += ms; } };
}

async function finishedRun(name?: string) {
  const { api, advance } = setup();
  const source = await api.uploadSource(pdf(name), () => {});
  const created = await api.createRun(source.source_id);
  advance(1000);
  return { api, advance, source, run: await api.getRun(created.run_id) };
}

const failureOf = (promise: Promise<unknown>) => promise.then(() => null, (err: ApiFailure) => err);

describe("upload", () => {
  it("returns an opaque source ID with the SHA-256 of the bytes", async () => {
    const { api } = setup();
    const progress: number[] = [];
    const source = await api.uploadSource(pdf(), (f) => progress.push(f));
    expect(source.source_id).toMatch(/^src_/);
    expect(source.sha256).toMatch(/^[0-9a-f]{64}$/);
    expect(source.upload_state).toBe("complete");
    expect(progress.at(-1)).toBe(1);
    expect(source.source_id).not.toMatch(/[/\\]/);
    expect(Object.keys(source)).not.toContain("path");
  });

  it("rejects bytes that are not a PDF", async () => {
    const { api } = setup();
    const err = await failureOf(api.uploadSource(new File(["hello"], "x.pdf"), () => {}));
    expect(err?.code).toBe("UNSUPPORTED_MEDIA_TYPE");
  });

  it("rejects unknown IDs with NOT_FOUND", async () => {
    const { api } = setup();
    expect((await failureOf(api.getSource("../../etc/passwd")))?.code).toBe("NOT_FOUND");
    expect((await failureOf(api.getRun("run_missing")))?.code).toBe("NOT_FOUND");
    expect((await failureOf(api.readArtifact("art_missing")))?.code).toBe("NOT_FOUND");
  });
});

describe("delete", () => {
  it("removes a source with its runs once no run is active", async () => {
    const { api, advance } = setup();
    const source = await api.uploadSource(pdf(), () => {});
    const run = await api.createRun(source.source_id);
    expect((await failureOf(api.deleteSource(source.source_id)))?.code).toBe("RUN_ACTIVE");
    advance(1000);
    await api.deleteSource(source.source_id);
    expect(await api.listSources()).toEqual([]);
    expect((await failureOf(api.getRun(run.run_id)))?.code).toBe("NOT_FOUND");
    expect((await failureOf(api.deleteSource(source.source_id)))?.code).toBe("NOT_FOUND");
  });
});

describe("run lifecycle", () => {
  it("passes the phases and releases artifacts of one revision", async () => {
    const { api, advance } = setup();
    const source = await api.uploadSource(pdf(), () => {});
    const run = await api.createRun(source.source_id);
    expect(run.phase).toBe("queued");
    expect(run.simulated).toBe(true);
    advance(25);
    expect((await api.getRun(run.run_id)).phase).toBe("modeling");
    advance(1000);
    const done = await api.getRun(run.run_id);
    expect(done.phase).toBe("done");
    expect(done.review?.release_state).toBe("released");
    expect(new Set(done.artifacts.map((a) => a.model_revision))).toEqual(new Set([1]));
    expect(delivery(done).released).toBe(true);
    expect(done.review?.validation.find((v) => v.check === "target_cad_open")?.status).toBe("not_tested");
  });

  it("blocks a failed run and does not release its outputs", async () => {
    const { run } = await finishedRun("fail-case.pdf");
    expect(run.phase).toBe("failed");
    expect(run.error?.code).toBe("STEP_REIMPORT_FAILED");
    expect(run.review?.release_state).toBe("blocked");
    expect(delivery(run).released).toBe(false);
    expect(delivery(run).reasons[0]).toMatch(/Prüfung ist fehlgeschlagen/);
  });

  it("shows the latest draft drawing of the current revision, but not a stale one", async () => {
    const { run } = await finishedRun("fail-case.pdf");
    const pdf = (id: string, revision: number): Artifact => ({ artifact_id: id, role: "drawing_pdf", media_type: "application/pdf",
      filename: `${id}.pdf`, sha256: "0".repeat(64), byte_count: 1, source_sha256: "1".repeat(64), model_revision: revision });
    const current = run.part!.revision;
    const drafts = { ...run, artifacts: [pdf("first", current), pdf("latest", current), pdf("stale", current - 1)] };
    expect(latestShown(drafts, "drawing_pdf")?.artifact_id).toBe("latest");
    expect(latestShown({ ...drafts, artifacts: [pdf("stale", current - 1)] }, "drawing_pdf")).toBeUndefined();
    expect(latestShown({ ...drafts, job: { ...drafts.job, status: "running" } }, "drawing_pdf")).toBeUndefined();
  });

  it("does not report a failed check for a valid build without release", async () => {
    const { run } = await finishedRun("fail-case.pdf");
    const unreleased = { ...run, review: { ...run.review!, validation: run.review!.validation.filter((v) => v.status !== "fail") } };
    expect(delivery(unreleased).reasons).toEqual(["Modell gebaut, aber nicht freigegeben: Die STEP-Freigabe fehlt."]);
  });
});

describe("parameter change", () => {
  it("creates a new revision and marks old artifacts stale until regeneration", async () => {
    const { api, advance, run } = await finishedRun();
    const changed = await api.changeParameters(run.run_id, 1, [{ name: "length", value: 140 }]);
    expect(changed.part?.revision).toBe(2);
    expect(changed.part?.parameters.find((p) => p.name === "length")).toMatchObject({ value: 140, origin: "user" });
    expect(changed.review?.release_state).toBe("stale");
    expect(changed.artifacts.every((a) => !isReleased(delivery(changed), changed, a))).toBe(true);
    advance(1000);
    const regenerated = await api.getRun(run.run_id);
    expect(regenerated.review?.release_state).toBe("released");
    expect(regenerated.artifacts.every((a) => a.model_revision === 2)).toBe(true);
  });

  it("rejects a wrong expected revision", async () => {
    const { api, run } = await finishedRun();
    await api.changeParameters(run.run_id, 1, [{ name: "width", value: 90 }]);
    const err = await failureOf(api.changeParameters(run.run_id, 1, [{ name: "width", value: 95 }]));
    expect(err?.code).toBe("REVISION_CONFLICT");
    expect(err?.status).toBe(409);
  });

  it("rejects invalid values with the affected field", async () => {
    const { api, run } = await finishedRun();
    const err = await failureOf(api.changeParameters(run.run_id, 1, [{ name: "thickness", value: -1 }]));
    expect(err?.code).toBe("INVALID_PARAMETER");
    expect(err?.field).toBe("thickness");
  });

  it("removes an assumption when the user sets its value", async () => {
    const { api, advance, run } = await finishedRun();
    expect(run.review?.assumptions.map((a) => a.parameter)).toContain("thickness");
    await api.changeParameters(run.run_id, 1, [{ name: "thickness", value: 12 }]);
    advance(1000);
    const next = await api.getRun(run.run_id);
    expect(next.review?.assumptions.map((a) => a.parameter)).not.toContain("thickness");
  });
});

describe("concurrent reads", () => {
  it("create the outputs of a finished revision once", async () => {
    const { api, advance } = setup();
    const source = await api.uploadSource(pdf(), () => {});
    const run = await api.createRun(source.source_id);
    advance(1000);
    const [a, b] = await Promise.all([api.getRun(run.run_id), api.getRun(run.run_id)]);
    expect(a.artifacts.map((x) => x.artifact_id)).toEqual(b.artifacts.map((x) => x.artifact_id));
    for (const artifact of a.artifacts) await expect(api.readArtifact(artifact.artifact_id)).resolves.toBeInstanceOf(Blob);
  });
});

describe("notes", () => {
  it("stores a revisioned note and rejects a stale revision", async () => {
    const { api, run } = await finishedRun();
    expect(await api.getNote(run.run_id)).toEqual({ revision: 0, text: "" });
    const first = await api.saveNote(run.run_id, 0, "Radius mit Konstruktion klären");
    expect(first.revision).toBe(1);
    expect((await failureOf(api.saveNote(run.run_id, 0, "zweite")))?.code).toBe("REVISION_CONFLICT");
    expect(await api.getNote(run.run_id)).toEqual(first);
  });
});

describe("release presentation", () => {
  it("does not present mixed revisions as released", async () => {
    const { run } = await finishedRun();
    const mixed = { ...run, artifacts: run.artifacts.map((a, i) => (i === 0 ? { ...a, model_revision: 0 } : a)) };
    const state = delivery(mixed);
    expect(state.released).toBe(false);
    expect(state.revisionsAgree).toBe(false);
  });
});

describe("flag decisions", () => {
  it("stores a decision per flag, exports it, and removes it on reopen", async () => {
    const { api } = setup();
    const source = await api.uploadSource(pdf(), () => {});
    const [flag] = (await api.getFlags(source.source_id)).flags;
    expect(flag.decision).toBeNull();

    const decided = await api.decideFlag(source.source_id, flag.id, { action: "classify", stroke_class: "table", note: "Passmaß-Tabelle" });
    expect(decided.flags[0].decision).toMatchObject({ action: "classify", stroke_class: "table", note: "Passmaß-Tabelle" });
    const feedback = JSON.parse(await (await api.exportFeedback()).text());
    expect(feedback.decisions).toEqual([expect.objectContaining({ source_id: source.source_id, flag_id: flag.id, stroke_class: "table" })]);

    const reopened = await api.decideFlag(source.source_id, flag.id, { action: "reopen" });
    expect(reopened.flags[0].decision).toBeNull();
  });

  it("rejects an unknown flag", async () => {
    const { api } = setup();
    const source = await api.uploadSource(pdf(), () => {});
    expect((await failureOf(api.decideFlag(source.source_id, "strokes-999", { action: "ignore" })))?.code).toBe("NOT_FOUND");
  });
});
