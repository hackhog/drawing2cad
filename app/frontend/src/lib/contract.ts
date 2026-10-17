// Provisional frontend view of the shared service contract (docs/contracts/m2-service-v1.md).
// The shared service publishes the binding schemas. When they are available, replace these types
// with the published ones and keep the field names. Do not add domain rules here.
import type { Box } from "./drawing";

export const CONTRACT_VERSION = "0.1.0-provisional";

export type UploadState = "pending" | "complete" | "failed";

/** A stored PDF source. The browser never sees a server path. */
export interface Source {
  source_id: string;
  filename: string;
  media_type: string;
  byte_count: number;
  sha256: string;
  upload_state: UploadState;
  created_at: string;
}

export type RunPhase = "queued" | "analyzing" | "modeling" | "drawing" | "validating" | "done" | "failed" | "cancelled";
export type JobStatus = "queued" | "running" | "succeeded" | "failed" | "cancelled";
export type ReleaseState = "draft" | "stale" | "blocked" | "released";
export type ValueOrigin = "source" | "assumed" | "user";

export interface Parameter {
  name: string;
  value: number;
  unit: "mm" | "deg" | "";
  origin: ValueOrigin;
  editable: boolean;
  feature: string;
}

export interface Operation {
  index: number;
  kind: string;
  label: string;
  parameters: string[];
}

export interface Part {
  revision: number;
  parameters: Parameter[];
  operations: Operation[];
  capabilities: { parameter_edit: boolean };
}

export type ArtifactRole = "drawing_pdf" | "drawing_dxf" | "step" | "part_description" | "manifest" | "trace" | "events" | "report";

/** An output file. Content is read by `artifact_id` only. */
export interface Artifact {
  artifact_id: string;
  role: ArtifactRole;
  media_type: string;
  filename: string;
  sha256: string;
  byte_count: number;
  source_sha256: string;
  model_revision: number;
}

/** A diagnostic file of a run: trace, run record, or MCP part state. The service supplies root-relative URLs. */
export interface RunFile {
  path: string;
  byte_count: number;
  url: string;
}

export interface RunFiles {
  files: RunFile[];
  archive_url: string | null;
}

export interface Assumption {
  id: string;
  feature: string;
  parameter: string | null;
  value: number;
  unit: string;
  reason: string;
  source_region: Box | null;
}

export interface Uncertainty {
  id: string;
  feature: string;
  message: string;
  source_region: Box | null;
}

export interface ValidationResult {
  check: string;
  status: "pass" | "fail" | "not_tested";
  detail: string;
}

export interface Review {
  release_state: ReleaseState;
  assumptions: Assumption[];
  uncertainties: Uncertainty[];
  validation: ValidationResult[];
}

export interface RunNote {
  note_id: string;
  revision: number;
  author: string;
  text: string;
  created_at: string;
}

export interface Job {
  job_id: string;
  status: JobStatus;
  progress: number | null;
  started_at: string;
  finished_at: string | null;
}

export interface Run {
  run_id: string;
  source_id: string;
  phase: RunPhase;
  /** The model and the drawing2cad-mcp version that execute an agent run. */
  agent?: { model: string; mcp_version: string } | null;
  /** The phase in which a failed run stopped. */
  failed_phase?: RunPhase | null;
  job: Job;
  part: Part | null;
  artifacts: Artifact[];
  review: Review | null;
  error: ServiceError | null;
  simulated: boolean;
  /** Final text of the agent conversation, stored as the note of its part run (ADR 0018). */
  agent_report?: string;
}

export interface ServiceError {
  code: string;
  message: string;
  field: string | null;
  recovery: string | null;
}

/** Actual capabilities of the connected service. The UI hides or explains every unavailable one. */
export interface Capabilities {
  contract_version: string;
  simulated: boolean;
  runs: boolean;
  parameter_edit: boolean;
  notes: boolean;
  downloads: boolean;
  model_preview: boolean;
  step_preview_upload: boolean;
  max_pdf_bytes: number;
  /** The configured agent model, if the service starts agent runs. */
  agent_model?: string | null;
}
