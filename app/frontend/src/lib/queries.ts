// Query keys and options for all server data. Components use these through TanStack Query only.
import { queryOptions } from "@tanstack/react-query";
import { isActive } from "./release";
import type { JobStatus } from "./contract";
import type { WebApi } from "./webApi";

export const keys = {
  capabilities: ["capabilities"] as const,
  agentProfiles: ["agentProfiles"] as const,
  sources: ["sources"] as const,
  source: (id: string) => ["sources", id] as const,
  analysis: (id: string) => ["analysis", id] as const,
  flags: (id: string) => ["flags", id] as const,
  runs: (sourceId: string) => ["runs", { sourceId }] as const,
  run: (id: string) => ["run", id] as const,
  note: (runId: string) => ["note", runId] as const,
  runFiles: (runId: string) => ["runFiles", runId] as const,
  runSteps: (runId: string, status: JobStatus) => ["runSteps", runId, status] as const,
  runStep: (runId: string, sequence: number) => ["runStep", runId, sequence] as const,
  measurements: ["measurements"] as const,
};

const POLL_MS = 600;

export const capabilitiesQuery = (api: WebApi) =>
  queryOptions({ queryKey: keys.capabilities, queryFn: () => api.capabilities(), staleTime: Infinity });

export const agentProfilesQuery = (api: WebApi) =>
  queryOptions({ queryKey: keys.agentProfiles, queryFn: () => api.agentProfiles() });

export const sourcesQuery = (api: WebApi) =>
  queryOptions({ queryKey: keys.sources, queryFn: () => api.listSources() });

export const sourceQuery = (api: WebApi, id: string) =>
  queryOptions({ queryKey: keys.source(id), queryFn: () => api.getSource(id) });

// An analysis belongs to one immutable source, so it never becomes stale.
export const analysisQuery = (api: WebApi, id: string) =>
  queryOptions({ queryKey: keys.analysis(id), queryFn: () => api.getAnalysis(id), staleTime: Infinity });

export const flagsQuery = (api: WebApi, id: string) =>
  queryOptions({ queryKey: keys.flags(id), queryFn: () => api.getFlags(id) });

export const runsQuery = (api: WebApi, sourceId: string) =>
  queryOptions({
    queryKey: keys.runs(sourceId), queryFn: () => api.listRuns(sourceId),
    refetchInterval: (q) => (q.state.data?.some(isActive) ? POLL_MS : false),
  });

// Poll only while the job is active. A finished run changes only through a mutation.
export const runQuery = (api: WebApi, id: string) =>
  queryOptions({
    queryKey: keys.run(id), queryFn: () => api.getRun(id),
    refetchInterval: (q) => (q.state.data && isActive(q.state.data) ? POLL_MS : false),
  });

export const noteQuery = (api: WebApi, runId: string) =>
  queryOptions({ queryKey: keys.note(runId), queryFn: () => api.getNote(runId) });

// Loaded on request; the trace grows while the run is active, so each opening reads the current list.
export const runFilesQuery = (api: WebApi, runId: string) =>
  queryOptions({ queryKey: keys.runFiles(runId), queryFn: () => api.listRunFiles(runId), staleTime: 0 });

// The trace grows while the run is active. Each poll reads the condensed steps, not the trace files.
const STEPS_POLL_MS = 2000;

// The job status is part of the key: a run that ends between two polls still reads its final steps.
export const runStepsQuery = (api: WebApi, runId: string, status: JobStatus) =>
  queryOptions({
    queryKey: keys.runSteps(runId, status), queryFn: () => api.runSteps(runId),
    refetchInterval: status === "queued" || status === "running" ? STEPS_POLL_MS : false,
  });

// A step with a response never changes. A tool request without a response gets its response later.
export const runStepQuery = (api: WebApi, runId: string, sequence: number, complete: boolean) =>
  queryOptions({
    queryKey: keys.runStep(runId, sequence), queryFn: () => api.runStep(runId, sequence),
    staleTime: complete ? Infinity : 0,
  });

// Measurements change only through a mutation of this browser or a reload.
export const measurementsQuery = (api: WebApi) =>
  queryOptions({ queryKey: keys.measurements, queryFn: () => api.listMeasurements() });
