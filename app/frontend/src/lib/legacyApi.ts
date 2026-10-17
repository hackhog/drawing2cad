// Adapter for the current demo backend (/api/extract, /api/model). The backend stores nothing,
// so this adapter keeps sources and their analysis in browser memory until the page reloads.
import type { Capabilities, Run, RunNote, Source } from "./contract";
import { CONTRACT_VERSION } from "./contract";
import type { ExtractResult } from "./drawing";
import { notFound, unavailable } from "./errors";
import { uploadFile } from "./http";
import type { ParameterChange, WebApi } from "./webApi";

const MAX_PDF_BYTES = 20 * 1024 * 1024; // Same limit as app/backend/src/drawing_demo/api.py.

interface Entry { source: Source; analysis: ExtractResult }

export class LegacyApi implements WebApi {
  private readonly entries = new Map<string, Entry>();
  private next = 1;

  async capabilities(): Promise<Capabilities> {
    return {
      contract_version: CONTRACT_VERSION, simulated: false, runs: false, parameter_edit: false, notes: false,
      downloads: false, model_preview: false, step_preview_upload: true, max_pdf_bytes: MAX_PDF_BYTES,
    };
  }

  async listSources(): Promise<Source[]> {
    return [...this.entries.values()].map((e) => e.source);
  }

  async getSource(sourceId: string): Promise<Source> {
    return this.entry(sourceId).source;
  }

  async uploadSource(file: File, onProgress: (fraction: number) => void): Promise<Source> {
    const analysis = await uploadFile<ExtractResult>("/api/extract", file, onProgress);
    // The legacy endpoint returns hash and size, but no stored identity. The ID is local to this page.
    const source: Source = {
      source_id: `local-${this.next++}`,
      filename: file.name,
      media_type: "application/pdf",
      byte_count: analysis.provenance?.source_size_bytes ?? file.size,
      sha256: analysis.provenance?.source_sha256 ?? "",
      upload_state: "complete",
      created_at: new Date().toISOString(),
    };
    this.entries.set(source.source_id, { source, analysis });
    return source;
  }

  async deleteSource(sourceId: string): Promise<void> {
    this.entry(sourceId);
    this.entries.delete(sourceId);
  }

  async getAnalysis(sourceId: string): Promise<ExtractResult> {
    return this.entry(sourceId).analysis;
  }

  async listRuns(): Promise<Run[]> {
    return [];
  }

  createRun(): Promise<Run> { return Promise.reject(unavailable("Ein CAD-Lauf")); }
  getRun(runId: string): Promise<Run> { return Promise.reject(notFound("Lauf", runId)); }
  changeParameters(_runId: string, _rev: number, _changes: ParameterChange[]): Promise<Run> {
    return Promise.reject(unavailable("Das Ändern von Parametern"));
  }
  listNotes(): Promise<RunNote[]> { return Promise.reject(unavailable("Notizen")); }
  addNote(): Promise<RunNote> { return Promise.reject(unavailable("Notizen")); }
  readArtifact(artifactId: string): Promise<Blob> { return Promise.reject(notFound("Artefakt", artifactId)); }

  stepPreview(file: File): Promise<Blob> {
    return uploadFile<Blob>("/api/model", file, () => {}, "blob");
  }

  private entry(sourceId: string): Entry {
    const entry = this.entries.get(sourceId);
    if (!entry) throw notFound("Zeichnung", sourceId);
    return entry;
  }
}
