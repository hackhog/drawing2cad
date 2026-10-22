// The one interface between the UI and a service. Components and routes use only this interface.
// `http` uses the web backend (app/backend); `fixture` is a simulated service for UI work without a backend.
import type { AgentProfileInput, AgentProfiles, Capabilities, ConnectionCheck, Measurement, MeasurementInput, Run, RunFiles, RunNote, RunStepDetail, RunSteps, Source } from "./contract";
import type { ExtractResult, FlagChange, FlagsPage } from "./drawing";

export interface ParameterChange { name: string; value: number }

export interface WebApi {
  capabilities(): Promise<Capabilities>;
  /** Model profiles of the server, without keys. */
  agentProfiles(): Promise<AgentProfiles>;
  /** Select the profile for new runs; null selects no agent. Queued and running runs keep their profile. */
  selectAgentProfile(name: string | null, revision?: number): Promise<AgentProfiles>;
  /** Create or change a profile. The key goes to the server and does not come back. */
  saveAgentProfile(name: string, profile: AgentProfileInput): Promise<AgentProfiles>;
  deleteAgentProfile(name: string, revision?: number | null): Promise<AgentProfiles>;
  /** Send one short request to the endpoint of a profile. It uses a few tokens. */
  checkAgentProfile(name: string): Promise<ConnectionCheck>;
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
  /** Start a run with the given model profile, or with the active profile. The active profile does not change. */
  createRun(sourceId: string, profile?: string | null): Promise<Run>;
  /** The run includes an optional warning when the release passed but the final report is missing. */
  getRun(runId: string): Promise<Run>;
  /** Change parameters through the shared revision API. A wrong expected revision fails with REVISION_CONFLICT. */
  changeParameters(runId: string, expectedRevision: number, changes: ParameterChange[]): Promise<Run>;
  getNote(runId: string): Promise<RunNote>;
  /** Replace the run note. A wrong expected revision fails with REVISION_CONFLICT. */
  saveNote(runId: string, expectedRevision: number, text: string): Promise<RunNote>;
  /** Diagnostic files of a run, for inspection in a browser tab. */
  listRunFiles(runId: string): Promise<RunFiles>;
  /** The agent trace of a run as timeline steps. A run without agent trace has no steps. */
  runSteps(runId: string): Promise<RunSteps>;
  /** Full details of one timeline step. */
  runStep(runId: string, sequence: number): Promise<RunStepDetail>;
  /** Bounded artifact content by opaque ID. */
  readArtifact(artifactId: string): Promise<Blob>;
  /** Review measurements of all sources, oldest first. Deleting a source deletes its measurements. */
  listMeasurements(): Promise<Measurement[]>;
  addMeasurement(sourceId: string, measurement: MeasurementInput): Promise<Measurement>;
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
