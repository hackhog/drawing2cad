// Simulated service for UI work before the shared services exist. Every run is marked `simulated`.
// It imitates the contract behavior that the UI must handle: job phases, revisions, stale artifacts,
// revision conflicts, failed jobs, and unknown IDs. It does not execute CAD or analyze the uploaded PDF.
import type { Artifact, ArtifactRole, Capabilities, Part, Run, RunFiles, RunNote, RunPhase, Source } from "./contract";
import { CONTRACT_VERSION } from "./contract";
import type { ExtractResult } from "./drawing";
import { ApiFailure, notFound } from "./errors";
import {
  FIXTURE_ASSUMPTIONS, FIXTURE_OPERATIONS, FIXTURE_UNCERTAINTIES, fixtureAnalysis, fixtureParameters, fixtureValidation,
} from "./fixtures";
import { sha256Hex } from "./http";
import { isActive } from "./release";
import type { ParameterChange, WebApi } from "./webApi";

const MAX_PDF_BYTES = 20 * 1024 * 1024;
const PHASES: RunPhase[] = ["queued", "analyzing", "modeling", "drawing", "validating"];
const OUTPUTS: [ArtifactRole, string, string][] = [
  ["drawing_pdf", "application/pdf", "zeichnung"],
  ["drawing_dxf", "image/vnd.dxf", "zeichnung"],
  ["step", "model/step", "modell"],
  ["manifest", "application/json", "manifest"],
];
const EXTENSION: Record<ArtifactRole, string> = {
  drawing_pdf: "pdf", drawing_dxf: "dxf", step: "step", part_description: "json", manifest: "json", trace: "json", events: "json", report: "json",
};

interface RunRecord {
  runId: string;
  source: Source;
  /** A filename with "fail" simulates a failed STEP re-import, so the error path can be shown. */
  failing: boolean;
  part: Part;
  startedAt: number;
  firstPhase: number;
  artifacts: Artifact[];
  note: RunNote;
  /** Output creation in progress, shared by concurrent reads of the same finished revision. */
  building: Promise<void> | null;
}

export interface FixtureOptions { now?: () => number; phaseMs?: number; latencyMs?: number }

export class FixtureApi implements WebApi {
  private readonly sources = new Map<string, Source>();
  private readonly runs = new Map<string, RunRecord>();
  private readonly contents = new Map<string, Blob>();
  private readonly now: () => number;
  private readonly phaseMs: number;
  private readonly latencyMs: number;
  private serial = 1;

  constructor({ now = () => Date.now(), phaseMs = 900, latencyMs = 120 }: FixtureOptions = {}) {
    this.now = now;
    this.phaseMs = phaseMs;
    this.latencyMs = latencyMs;
  }

  async capabilities(): Promise<Capabilities> {
    await this.latency();
    return {
      contract_version: CONTRACT_VERSION, simulated: true, runs: true, parameter_edit: true, notes: true,
      downloads: true, model_preview: false, step_preview_upload: false, max_pdf_bytes: MAX_PDF_BYTES,
    };
  }

  async listSources(): Promise<Source[]> {
    await this.latency();
    return [...this.sources.values()];
  }

  async getSource(sourceId: string): Promise<Source> {
    await this.latency();
    return this.source(sourceId);
  }

  async uploadSource(file: File, onProgress: (fraction: number) => void): Promise<Source> {
    if (file.size > MAX_PDF_BYTES) {
      throw new ApiFailure({ code: "UPLOAD_TOO_LARGE", message: "PDF größer als 20 MB.", field: "file" }, 413);
    }
    const bytes = await file.arrayBuffer();
    if (new TextDecoder().decode(bytes.slice(0, 5)) !== "%PDF-") {
      throw new ApiFailure({ code: "UNSUPPORTED_MEDIA_TYPE", message: "Keine PDF-Datei.", field: "file" }, 415);
    }
    for (const step of [0.25, 0.5, 0.75, 1]) {
      await this.latency();
      onProgress(step);
    }
    const source: Source = {
      source_id: this.id("src"), filename: file.name, media_type: "application/pdf", byte_count: file.size,
      sha256: await sha256Hex(bytes), upload_state: "complete", created_at: new Date(this.now()).toISOString(),
    };
    this.sources.set(source.source_id, source);
    return source;
  }

  async deleteSource(sourceId: string): Promise<void> {
    await this.latency();
    this.source(sourceId);
    const records = [...this.runs.values()].filter((r) => r.source.source_id === sourceId);
    if ((await Promise.all(records.map((r) => this.view(r)))).some(isActive)) {
      throw new ApiFailure({ code: "RUN_ACTIVE", message: "Für diese Zeichnung läuft noch ein Lauf." }, 409);
    }
    for (const r of records) this.runs.delete(r.runId);
    this.sources.delete(sourceId);
  }

  async getAnalysis(sourceId: string): Promise<ExtractResult> {
    await this.latency();
    return fixtureAnalysis(this.source(sourceId).filename);
  }

  async listRuns(sourceId: string): Promise<Run[]> {
    await this.latency();
    this.source(sourceId);
    const records = [...this.runs.values()].filter((r) => r.source.source_id === sourceId);
    return Promise.all(records.map((r) => this.view(r)));
  }

  async createRun(sourceId: string): Promise<Run> {
    await this.latency();
    const source = this.source(sourceId);
    const record: RunRecord = {
      runId: this.id("run"), source, failing: /fail/i.test(source.filename),
      part: {
        revision: 1, parameters: fixtureParameters(), operations: FIXTURE_OPERATIONS, capabilities: { parameter_edit: true },
      },
      startedAt: this.now(), firstPhase: 0, artifacts: [], note: { revision: 0, text: "" }, building: null,
    };
    this.runs.set(record.runId, record);
    return this.view(record);
  }

  async getRun(runId: string): Promise<Run> {
    await this.latency();
    return this.view(this.run(runId));
  }

  async changeParameters(runId: string, expectedRevision: number, changes: ParameterChange[]): Promise<Run> {
    await this.latency();
    const record = this.run(runId);
    if (expectedRevision !== record.part.revision) {
      throw new ApiFailure({
        code: "REVISION_CONFLICT", field: "expected_revision",
        message: `Erwartet Revision ${expectedRevision}, aktuell ist ${record.part.revision}.`,
      }, 409);
    }
    const parameters = record.part.parameters.map((p) => ({ ...p }));
    for (const change of changes) {
      const target = parameters.find((p) => p.name === change.name);
      if (!target?.editable) {
        throw new ApiFailure({ code: "INVALID_PARAMETER", field: change.name, message: `${change.name} ist nicht änderbar.` }, 422);
      }
      if (!Number.isFinite(change.value) || change.value <= 0) {
        throw new ApiFailure({ code: "INVALID_PARAMETER", field: change.name, message: `${change.name} muss größer als 0 sein.` }, 422);
      }
      target.value = change.value;
      target.origin = "user";
    }
    // A new revision restarts the model phases. Existing artifacts stay listed and become stale.
    record.part = { ...record.part, revision: record.part.revision + 1, parameters };
    record.startedAt = this.now();
    record.firstPhase = PHASES.indexOf("modeling");
    return this.view(record);
  }

  async getNote(runId: string): Promise<RunNote> {
    await this.latency();
    return { ...this.run(runId).note };
  }

  async saveNote(runId: string, expectedRevision: number, text: string): Promise<RunNote> {
    await this.latency();
    const record = this.run(runId);
    if (expectedRevision !== record.note.revision) {
      throw new ApiFailure({
        code: "REVISION_CONFLICT", field: "expected_revision",
        message: `Die Notiz hat Revision ${record.note.revision}, erwartet war ${expectedRevision}.`,
      }, 409);
    }
    record.note = { revision: record.note.revision + 1, text };
    return { ...record.note };
  }

  /** A simulated run has no agent trace and no MCP part state. */
  async listRunFiles(runId: string): Promise<RunFiles> {
    await this.latency();
    this.run(runId);
    return { files: [], archive_url: null };
  }

  async readArtifact(artifactId: string): Promise<Blob> {
    await this.latency();
    const content = this.contents.get(artifactId);
    if (!content) throw notFound("Artefakt", artifactId);
    return content;
  }

  stepPreview(): Promise<Blob> {
    return Promise.reject(new ApiFailure({ code: "CAPABILITY_UNAVAILABLE", message: "Keine 3D-Vorschau in simulierten Daten." }));
  }

  /** Derive the current phase from the elapsed time and create the outputs when a revision finishes. */
  private async view(record: RunRecord): Promise<Run> {
    const elapsed = this.now() - record.startedAt;
    const index = record.firstPhase + Math.floor(elapsed / this.phaseMs);
    const span = PHASES.length - record.firstPhase;
    const finished = index >= PHASES.length;
    const revision = record.part.revision;
    const phase: RunPhase = finished ? (record.failing ? "failed" : "done") : PHASES[index];

    if (finished && !record.failing && !record.artifacts.some((a) => a.model_revision === revision)) {
      record.building ??= this.outputs(record).then((artifacts) => {
        for (const old of record.artifacts) this.contents.delete(old.artifact_id);
        record.artifacts = artifacts;
        record.building = null;
      });
      await record.building;
    }
    const current = record.artifacts.length > 0 && record.artifacts.every((a) => a.model_revision === revision);
    const release_state = phase === "failed" ? "blocked" : phase === "done" && current ? "released"
      : record.artifacts.length ? "stale" : "draft";

    return {
      run_id: record.runId,
      source_id: record.source.source_id,
      phase,
      job: {
        job_id: `${record.runId}-r${revision}`,
        status: phase === "failed" ? "failed" : phase === "done" ? "succeeded" : phase === "queued" ? "queued" : "running",
        progress: finished ? 1 : Math.min(1, elapsed / (span * this.phaseMs)),
        started_at: new Date(record.startedAt).toISOString(),
        finished_at: finished ? new Date(record.startedAt + span * this.phaseMs).toISOString() : null,
      },
      part: structuredClone(record.part),
      artifacts: [...record.artifacts],
      review: {
        release_state,
        assumptions: FIXTURE_ASSUMPTIONS.map((a) => {
          const p = record.part.parameters.find((q) => q.name === a.parameter);
          return { ...a, value: p?.value ?? a.value };
        }).filter((a) => record.part.parameters.find((p) => p.name === a.parameter)?.origin === "assumed"),
        uncertainties: FIXTURE_UNCERTAINTIES,
        validation: finished ? fixtureValidation(record.failing) : [],
      },
      error: phase === "failed" ? {
        code: "STEP_REIMPORT_FAILED", field: "step",
        message: "Der STEP-Kandidat bestand den Reimport im frischen Worker nicht.",
        recovery: "Annahmen prüfen, Parameter anpassen und den Lauf neu erzeugen.",
      } : null,
      simulated: true,
    };
  }

  private async outputs(record: RunRecord): Promise<Artifact[]> {
    const revision = record.part.revision;
    const base = record.source.filename.replace(/\.pdf$/i, "");
    return Promise.all(OUTPUTS.map(async ([role, media_type, label]) => {
      const text = `SIMULATED ARTIFACT - not a CAD result.\nrole: ${role}\nsource_sha256: ${record.source.sha256}\nmodel_revision: ${revision}\n`;
      const blob = new Blob([text], { type: "text/plain" });
      const artifact: Artifact = {
        artifact_id: this.id("art"), role, media_type,
        filename: `${base}-${label}-r${revision}.simulated.${EXTENSION[role]}`,
        sha256: await sha256Hex(await blob.arrayBuffer()), byte_count: blob.size,
        source_sha256: record.source.sha256, model_revision: revision,
      };
      this.contents.set(artifact.artifact_id, blob);
      return artifact;
    }));
  }

  private source(sourceId: string): Source {
    const source = this.sources.get(sourceId);
    if (!source) throw notFound("Zeichnung", sourceId);
    return source;
  }

  private run(runId: string): RunRecord {
    const record = this.runs.get(runId);
    if (!record) throw notFound("Lauf", runId);
    return record;
  }

  private id(prefix: string): string {
    return `${prefix}_${(this.serial++).toString(36).padStart(4, "0")}`;
  }

  private latency(): Promise<void> {
    return new Promise((resolve) => setTimeout(resolve, this.latencyMs));
  }
}
