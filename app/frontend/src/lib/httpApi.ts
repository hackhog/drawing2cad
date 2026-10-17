// Adapter for the web backend (app/backend, ADR 0018): stored sources, their analysis, agent runs, and artifacts.
// Parameter edits and notes are not available yet; the capabilities report this, and the UI explains it.
import type { Capabilities, Run, RunFiles, RunNote, Source } from "./contract";
import type { ExtractResult } from "./drawing";
import { unavailable } from "./errors";
import { request, requestBlob, uploadFile } from "./http";
import type { ParameterChange, WebApi } from "./webApi";

const id = encodeURIComponent;

export class HttpApi implements WebApi {
  capabilities(): Promise<Capabilities> { return request("/api/capabilities"); }
  listSources(): Promise<Source[]> { return request("/api/sources"); }
  getSource(sourceId: string): Promise<Source> { return request(`/api/sources/${id(sourceId)}`); }
  uploadSource(file: File, onProgress: (fraction: number) => void): Promise<Source> {
    return uploadFile<Source>("/api/sources", file, onProgress);
  }
  getAnalysis(sourceId: string): Promise<ExtractResult> { return request(`/api/sources/${id(sourceId)}/analysis`); }
  listRuns(sourceId: string): Promise<Run[]> { return request(`/api/sources/${id(sourceId)}/runs`); }
  createRun(sourceId: string): Promise<Run> { return request(`/api/sources/${id(sourceId)}/runs`, { method: "POST" }); }
  getRun(runId: string): Promise<Run> { return request(`/api/runs/${id(runId)}`); }
  changeParameters(_runId: string, _expectedRevision: number, _changes: ParameterChange[]): Promise<Run> {
    return Promise.reject(unavailable("Das Ändern von Parametern"));
  }
  listNotes(): Promise<RunNote[]> { return Promise.reject(unavailable("Notizen")); }
  addNote(): Promise<RunNote> { return Promise.reject(unavailable("Notizen")); }
  listRunFiles(runId: string): Promise<RunFiles> { return request(`/api/runs/${id(runId)}/files`); }
  readArtifact(artifactId: string): Promise<Blob> { return requestBlob(`/api/artifacts/${id(artifactId)}/content`); }
  stepPreview(file: File): Promise<Blob> { return uploadFile<Blob>("/api/model", file, () => {}, "blob"); }
}
