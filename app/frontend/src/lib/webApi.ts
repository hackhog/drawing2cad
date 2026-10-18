// The one interface between the UI and a service. Components and routes use only this interface.
// `http` uses the web backend (app/backend); `fixture` is a simulated service for UI work without a backend.
import type { AgentProfiles, Capabilities, Run, RunFiles, RunNote, Source } from "./contract";
import type { ExtractResult, FlagChange, FlagsPage } from "./drawing";

export interface ParameterChange { name: string; value: number }

export interface WebApi {
  capabilities(): Promise<Capabilities>;
  /** Model profiles of the server, without endpoints or keys. */
  agentProfiles(): Promise<AgentProfiles>;
  /** Select the profile for new runs; null selects no agent. Queued and running runs keep their profile. */
  selectAgentProfile(name: string | null): Promise<AgentProfiles>;
  listSources(): Promise<Source[]>;
  getSource(sourceId: string): Promise<Source>;
  /** Upload PDF bytes. The service returns the source identity; the browser assumes no local path. */
  uploadSource(file: File, onProgress: (fraction: number) => void): Promise<Source>;
  /** Delete a source with its runs. An active run blocks the deletion with RUN_ACTIVE. */
  deleteSource(sourceId: string): Promise<void>;
  /** Drawing analysis of a source: strokes, views, texts, and review flags. */
  getAnalysis(sourceId: string): Promise<ExtractResult>;
  /** Review flags of a source with the decisions of the user. */
  getFlags(sourceId: string): Promise<FlagsPage>;
  /** Record or, with "reopen", remove the decision on one flag. */
  decideFlag(sourceId: string, flagId: string, change: FlagChange): Promise<FlagsPage>;
  /** All flag decisions as JSON feedback for the developers of the drawing analysis. */
  exportFeedback(): Promise<Blob>;
  listRuns(sourceId: string): Promise<Run[]>;
  createRun(sourceId: string): Promise<Run>;
  getRun(runId: string): Promise<Run>;
  /** Change parameters through the shared revision API. A wrong expected revision fails with REVISION_CONFLICT. */
  changeParameters(runId: string, expectedRevision: number, changes: ParameterChange[]): Promise<Run>;
  getNote(runId: string): Promise<RunNote>;
  /** Replace the run note. A wrong expected revision fails with REVISION_CONFLICT. */
  saveNote(runId: string, expectedRevision: number, text: string): Promise<RunNote>;
  /** Diagnostic files of a run, for inspection in a browser tab. */
  listRunFiles(runId: string): Promise<RunFiles>;
  /** Bounded artifact content by opaque ID. */
  readArtifact(artifactId: string): Promise<Blob>;
  /** Display-only STEP to GLB conversion for a STEP file that the user supplies. */
  stepPreview(file: File): Promise<Blob>;
}

export type ApiMode = "http" | "fixture";

// `vite --mode fixture` (npm run dev:fixture) selects the simulated service; every other mode uses the web backend.
export const API_MODE: ApiMode = import.meta.env.MODE === "fixture" ? "fixture" : "http";

export async function createApi(mode: ApiMode = API_MODE): Promise<WebApi> {
  // Load only the selected adapter, so the fixture data is not in the production bundle.
  return mode === "fixture"
    ? new (await import("./fixtureApi")).FixtureApi()
    : new (await import("./httpApi")).HttpApi();
}
