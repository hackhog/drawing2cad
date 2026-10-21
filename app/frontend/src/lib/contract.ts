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

export type ArtifactRole = "drawing_pdf" | "drawing_diagnostic" | "drawing_dxf" | "step" | "part_description" | "manifest" | "trace" | "events" | "report"
  | "verification_report" | "verification_preview" | "projection_overlay" | "projection_report";

export type ProjectionStatus = "matches" | "deviates" | "not_tested";

/** The newest source-projection check of the current part revision. Limits and check results come from the MCP. */
export interface ProjectionCheck {
  status: ProjectionStatus;
  revision: number | null;
  reason: string | null;
  report_artifact_id: string | null;
  overlay_artifact_id: string | null;
  page: number | null;
  sheet_size_mm: [number, number] | null;
  views: ProjectionView[];
  simulated?: boolean;
}

export interface ProjectionView {
  view_id: string;
  status: "pass" | "fail" | "not_tested";
  reason: string | null;
  region_sheet_mm: Box;
  metrics: { p95_mm: number | null; max_mm: number | null; coverage: number | null };
  limits: { p95_mm: number | null; max_mm: number | null; coverage_min: number | null };
  checks: Record<"p95" | "max" | "coverage", "pass" | "fail" | "not_tested">;
  max_capped: boolean;
}

/** Drawing status that a STEP release records. The drawing does not gate the release. */
export interface ReleaseDrawing {
  status: "accepted" | "unverified" | "unreviewed" | "rejected" | "failed" | "missing";
  reason: string | null;
  /** False when the drawing changed after the release. Call export_step again to record the new status. */
  current: boolean;
  /** complete_service: the release needed a drawing verified against the released STEP bytes. Older records have none. */
  delivery?: "step_only" | "complete_service";
  /** True while the released STEP and drawing PDF are the verified pair; false after a change; null without a pair. */
  pair_current?: boolean | null;
}

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
  /** The current release names this file. Absent in the fixture service. */
  released?: boolean;
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
  /** Drawing status of the current release, or null without a release. */
  drawing?: ReleaseDrawing | null;
  /** Acceptance of the current drawing: review plus the gate of the final PDF verification. */
  drawing_acceptance?: DrawingAcceptance | null;
}

/** One mandatory verification finding that blocks the acceptance. */
export interface BlockingFinding {
  rule_id: string;
  status: "fail" | "needs_review" | "not_tested" | "not_applicable";
  feature: string | null;
  message: string;
}

/** The service decides the acceptance. The UI only shows it: automated results, review decisions, and untested rules stay distinct. */
export interface DrawingAcceptance {
  status: ReleaseDrawing["status"];
  reason: string | null;
  verification: {
    validity: "current" | "stale" | null;
    status: "pass" | "fail" | "needs_review" | null;
    gate_passed: boolean;
    blocking_count: number;
    blocking: BlockingFinding[];
    /** needs_review findings that the identified review decided. */
    reviewed_count: number;
  } | null;
}

/** The one note of a run, with its own revision. Revision 0 means that no note exists yet. */
export interface RunNote {
  revision: number;
  text: string;
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
  /** The model profile, its model and reasoning effort, and the skill and drawing2cad-mcp versions that execute an agent run.
   * Runs from before these fields were recorded have no `reasoning_effort` or `skill_version`; null means none is set. */
  agent?: { model: string; profile?: string; reasoning_effort?: string | null; skill_version?: string | null; mcp_version: string } | null;
  /** Model turns and tool requests of the agent loop so far, with the tool request budget. */
  iterations?: { model_turns: number; tool_requests: number; step_budget: number; mcp_calls?: number; blocked_requests?: number } | null;
  /** The phase in which a failed run stopped. */
  failed_phase?: RunPhase | null;
  job: Job;
  part: Part | null;
  artifacts: Artifact[];
  review: Review | null;
  error: ServiceError | null;
  simulated: boolean;
  /** Final text of the agent conversation, from its trace. It is also the first text of the run note (ADR 0018). */
  agent_report?: string | null;
  /** Separate from release and generated-PDF verification. Absent on older servers. */
  projection?: ProjectionCheck;
}

export interface ServiceError {
  code: string;
  message: string;
  field: string | null;
  recovery: string | null;
}

/** Actual capabilities of the connected service. The UI hides or explains every unavailable one. */
/** Who estimated the manual effort: a drafter (for example, from BCT), a guest or jury member, or the team. */
export type Estimator = "drafter" | "guest" | "team";

/** One review of one drawing: the stopwatch time and, optionally, the estimated time of a manual rebuild. */
export interface MeasurementInput {
  review_seconds: number;
  manual_hours: number | null;
  estimator: Estimator | null;
}

export interface Measurement extends MeasurementInput {
  measurement_id: string;
  source_id: string;
  recorded_at: string;
}

export interface Capabilities {
  contract_version: string;
  simulated: boolean;
  runs: boolean;
  parameter_edit: boolean;
  notes: boolean;
  /** Decisions on review flags and their feedback export. */
  flag_decisions: boolean;
  downloads: boolean;
  model_preview: boolean;
  step_preview_upload: boolean;
  max_pdf_bytes: number;
  /** True if runs can start with a usable profile, also when the active profile cannot. Older servers omit it. */
  agent_ready?: boolean;
  /** The model of the active agent profile, if the service starts agent runs. */
  agent_model?: string | null;
  /** The name of the active agent profile, if the service starts agent runs. */
  agent_profile?: string | null;
}

export type AgentProvider = "openrouter" | "azure" | "openai";
export type AgentApi = "chat" | "responses";

/** Run limits of the agent loop (ADR 0028). */
export type AgentLimitName =
  | "step_budget" | "max_turns" | "model_timeout_seconds" | "call_timeout_seconds" | "total_timeout_seconds" | "max_tool_text_chars";
/** Limits that a profile sets. A missing or null limit uses the server default. */
export type AgentLimits = Partial<Record<AgentLimitName, number | null>>;

/** A model profile of the server. The server keeps the key; `key_set` tells if one is stored. */
export interface AgentProfile {
  name: string;
  provider: AgentProvider;
  /** "env" profiles come from the server configuration and are read-only. */
  origin: "env" | "ui";
  base_url: string;
  model: string;
  api: AgentApi;
  reasoning_effort: string | null;
  key_set: boolean;
  /** The server cannot decrypt the stored key, for example after a change of its master key. */
  key_locked?: boolean;
  /** The limits that this profile sets. */
  limits?: AgentLimits;
  /** Revision of a stored profile; null for a profile from the server configuration. */
  revision?: number | null;
}

/** A profile as the web UI saves it. The server derives the base URL and the key header from the provider. */
export interface AgentProfileInput {
  provider: AgentProvider;
  /** Azure AI Foundry: any URL of the resource. OpenAI-compatible: the base URL. OpenRouter: not used. */
  endpoint: string;
  model: string;
  api: AgentApi;
  /** Empty keeps the stored key of a changed profile. */
  api_key: string;
  reasoning_effort: string | null;
  limits?: AgentLimits;
  /** The revision that the client read. A stale revision fails with REVISION_CONFLICT. */
  revision?: number | null;
}

/** Result of one short request without tools to the endpoint of a profile. */
export interface ConnectionCheck {
  ok: boolean;
  message: string;
  latency_ms?: number;
}

/** The configured model profiles. `active` is null when new runs use no agent. */
export interface AgentProfiles {
  active: string | null;
  /** Revision of the selection. A stale revision fails with REVISION_CONFLICT. */
  active_revision?: number;
  profiles: AgentProfile[];
  /** False when the server has no master key: it cannot store API keys from the web UI. */
  master_key_set?: boolean;
  limits?: { defaults: Record<AgentLimitName, number>; maximums: Record<AgentLimitName, number> };
}
