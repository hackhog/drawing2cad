// Adapter for the web backend (app/backend, ADR 0018): stored sources, their analysis, agent runs, and artifacts.
// Parameter edits are not available yet; the capabilities report this, and the UI explains it.
import type { AgentProfileInput, AgentProfiles, Capabilities, ConnectionCheck, Measurement, MeasurementInput, Run, RunFiles, RunNote, Source } from "./contract";
import type { ExtractResult, FlagChange, FlagsPage } from "./drawing";
import { unavailable } from "./errors";
import { request, requestBlob, uploadFile } from "./http";
import type { ParameterChange, WebApi } from "./webApi";

const id = encodeURIComponent;

export class HttpApi implements WebApi {
  capabilities(): Promise<Capabilities> { return request("/api/capabilities"); }
  agentProfiles(): Promise<AgentProfiles> { return request("/api/agent/profiles"); }
  selectAgentProfile(name: string | null, revision?: number): Promise<AgentProfiles> {
    return request("/api/agent/active", {
      method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ name, revision }),
    });
  }
  saveAgentProfile(name: string, profile: AgentProfileInput): Promise<AgentProfiles> {
    return request(`/api/agent/profiles/${id(name)}`, {
      method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(profile),
    });
  }
  deleteAgentProfile(name: string, revision?: number | null): Promise<AgentProfiles> {
    const query = revision == null ? "" : `?revision=${revision}`;
    return request(`/api/agent/profiles/${id(name)}${query}`, { method: "DELETE" });
  }
  checkAgentProfile(name: string): Promise<ConnectionCheck> { return request(`/api/agent/profiles/${id(name)}/check`, { method: "POST" }); }
  listSources(): Promise<Source[]> { return request("/api/sources"); }
  getSource(sourceId: string): Promise<Source> { return request(`/api/sources/${id(sourceId)}`); }
  uploadSource(file: File, onProgress: (fraction: number) => void): Promise<Source> {
    return uploadFile<Source>("/api/sources", file, onProgress);
  }
  deleteSource(sourceId: string): Promise<void> { return request(`/api/sources/${id(sourceId)}`, { method: "DELETE" }); }
  getAnalysis(sourceId: string): Promise<ExtractResult> { return request(`/api/sources/${id(sourceId)}/analysis`); }
  getFlags(sourceId: string): Promise<FlagsPage> { return request(`/api/sources/${id(sourceId)}/flags`); }
  decideFlag(sourceId: string, flagId: string, change: FlagChange): Promise<FlagsPage> {
    return request(`/api/sources/${id(sourceId)}/flags/${id(flagId)}`, {
      method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(change),
    });
  }
  exportFeedback(): Promise<Blob> { return requestBlob("/api/feedback"); }
  listRuns(sourceId: string): Promise<Run[]> { return request(`/api/sources/${id(sourceId)}/runs`); }
  createRun(sourceId: string): Promise<Run> { return request(`/api/sources/${id(sourceId)}/runs`, { method: "POST" }); }
  getRun(runId: string): Promise<Run> { return request(`/api/runs/${id(runId)}`); }
  changeParameters(_runId: string, _expectedRevision: number, _changes: ParameterChange[]): Promise<Run> {
    return Promise.reject(unavailable("Changing parameters"));
  }
  getNote(runId: string): Promise<RunNote> { return request(`/api/runs/${id(runId)}/note`); }
  saveNote(runId: string, expectedRevision: number, text: string): Promise<RunNote> {
    return request(`/api/runs/${id(runId)}/note`, {
      method: "PUT", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ expected_revision: expectedRevision, text }),
    });
  }
  listRunFiles(runId: string): Promise<RunFiles> { return request(`/api/runs/${id(runId)}/files`); }
  readArtifact(artifactId: string): Promise<Blob> { return requestBlob(`/api/artifacts/${id(artifactId)}/content`); }
  listMeasurements(): Promise<Measurement[]> { return request("/api/measurements"); }
  addMeasurement(sourceId: string, measurement: MeasurementInput): Promise<Measurement> {
    return request(`/api/sources/${id(sourceId)}/measurements`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(measurement),
    });
  }
  stepPreview(file: File): Promise<Blob> { return uploadFile<Blob>("/api/model", file, () => {}, "blob"); }
}
