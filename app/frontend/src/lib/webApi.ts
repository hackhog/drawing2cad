// The one interface between the UI and a service. Components and routes use only this interface.
// `legacy` uses the current demo endpoints; `fixture` is a simulated service for UI work before #24 is available.
import type { Capabilities, Run, RunNote, Source } from "./contract";
import type { ExtractResult } from "./drawing";

export interface ParameterChange { name: string; value: number }

export interface WebApi {
  capabilities(): Promise<Capabilities>;
  listSources(): Promise<Source[]>;
  getSource(sourceId: string): Promise<Source>;
  /** Upload PDF bytes. The service returns the source identity; the browser assumes no local path. */
  uploadSource(file: File, onProgress: (fraction: number) => void): Promise<Source>;
  deleteSource(sourceId: string): Promise<void>;
  /** Drawing analysis of a source: strokes, views, texts, and review flags. */
  getAnalysis(sourceId: string): Promise<ExtractResult>;
  listRuns(sourceId: string): Promise<Run[]>;
  createRun(sourceId: string): Promise<Run>;
  getRun(runId: string): Promise<Run>;
  /** Change parameters through the shared revision API. A wrong expected revision fails with REVISION_CONFLICT. */
  changeParameters(runId: string, expectedRevision: number, changes: ParameterChange[]): Promise<Run>;
  listNotes(runId: string): Promise<RunNote[]>;
  addNote(runId: string, expectedRevision: number, text: string): Promise<RunNote>;
  /** Bounded artifact content by opaque ID. */
  readArtifact(artifactId: string): Promise<Blob>;
  /** Display-only STEP to GLB conversion for a STEP file that the user supplies. */
  stepPreview(file: File): Promise<Blob>;
}

export type ApiMode = "legacy" | "fixture";

// `vite --mode fixture` (npm run dev:fixture) selects the simulated service; every other mode uses the current backend.
export const API_MODE: ApiMode = import.meta.env.MODE === "fixture" ? "fixture" : "legacy";

export async function createApi(mode: ApiMode = API_MODE): Promise<WebApi> {
  // Load only the selected adapter, so the fixture data is not in the legacy bundle.
  return mode === "fixture"
    ? new (await import("./fixtureApi")).FixtureApi()
    : new (await import("./legacyApi")).LegacyApi();
}
