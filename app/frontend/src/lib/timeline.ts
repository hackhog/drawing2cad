// Presentation of the run timeline (ADR 0038): layers, labels, problem groups, and plain explanations of each step.
// The steps come from the agent trace; this module adds no CAD, drawing, or release rule.
import type { RunLoopSummary, RunStep, StepProblem } from "./contract";

/** The four layers of a run: skill instructions, the agent loop with the model, the MCP server, and the CAD worker. */
export type Layer = "skill" | "loop" | "mcp" | "cad";

export const LAYERS: { id: Layer; title: string; text: string }[] = [
  { id: "skill", title: "Skill", text: "SKILL.md and its references are the instructions of the model. They set the order: read and record evidence, describe the part, build, draw, release. The loop supplies the references of each step." },
  { id: "loop", title: "Agent loop", text: "Each turn sends the conversation and the tool list to the model and executes the tool calls that it requests. After a failed call, the loop sends a correction and blocks identical repeats. After an answer without a tool call, it asks the model to continue until a release or a final report. If the model sends an object or array argument as JSON text, the loop decodes it before the MCP call." },
  { id: "mcp", title: "MCP server", text: "Checks each argument against the tool schema, reads the uploaded PDF (text, image, vectors, measurements), and stores part, drawing, and notes." },
  { id: "cad", title: "CAD worker and release", text: "build123d builds the solid in a sandbox without network and checks its geometry. export_step releases the STEP file only after re-import, geometry, and drawing checks pass." },
];

const CAD_TOOLS = new Set(["cad_worker_probe", "create_base_body", "add_hole", "add_pocket", "add_cut", "add_chamfer", "add_fillet",
  "build_from_description", "export_step", "part_export_review", "model_projection_check"]);

export function layerOf(step: RunStep): Layer {
  if (step.kind === "skill") return "skill";
  if (step.kind === "tool") return CAD_TOOLS.has(step.tool) ? "cad" : "mcp";
  return "loop";
}

export function stepLabel(step: RunStep): string {
  switch (step.kind) {
    case "skill": return "Skill references";
    case "model": return step.tool_calls.length ? `Model turn ${step.turn ?? ""}`.trim() : `Model answer ${step.turn ?? ""}`.trim();
    case "tool": return step.tool;
    case "correction": return `Correction after ${step.tool}`;
    case "continuation": return `Continuation request ${step.count ?? ""}`.trim();
    case "decoding": return `Decoded argument of ${step.tool}`;
  }
}

/** Plain explanation of a tool, for users who do not know the MCP. */
const TOOL_TEXT: [RegExp, string][] = [
  [/^(drawing2cad_status|cad_capabilities)$/, "Asks the MCP server which tools, CAD backend, and export profiles are available."],
  [/^cad_worker_probe$/, "Tests the CAD sandbox: no network, no file access outside the job, and limits for time and memory."],
  [/^(part_schema|drawing_schema|pmi_schema)$/, "Reads the JSON schema of the description, so that the model can write valid input."],
  [/^pdf_(info|read_text)$/, "Reads the page data and the embedded text of the uploaded PDF."],
  [/^pdf_(render_page|crop_region)$/, "Renders the PDF page or a region of it as an image. The model looks at this image."],
  [/^pdf_(calibrate|measure_distance|measure_circle)$/, "Measures in the PDF vectors with a calibrated scale."],
  [/^drawing_extract$/, "Extracts views, strokes, and dimension texts from the vector data of the PDF."],
  [/^part_validate$/, "Checks a part description against the schema and its evidence, without a build."],
  [/^part_(create|update)$/, "Stores a new revision of the part description: parameters, features, and evidence."],
  [/^part_read$/, "Reads the current part state: description, build result, and release."],
  [/^(build_from_description|create_base_body|add_\w+)$/, "The CAD worker builds the solid with build123d and checks the geometry against the description."],
  [/^drawing_derive_views$/, "Derives orthographic, isometric, and section views from the validated model."],
  [/^drawing_(validate|render|verify|review|read)$/, "Checks, renders, or verifies the technical drawing with its dimensions."],
  [/^export_step$/, "Exports STEP, re-imports it in a fresh worker, and releases it only if all checks pass."],
  [/^model_projection_check$/, "Compares a projection of the built model with the source drawing."],
  [/^notes_(read|update)$/, "Reads or writes the run note with the report of the agent."],
];

export function explanation(step: RunStep): string {
  switch (step.kind) {
    case "skill": return "The loop added these skill references to the conversation, because the next step needs them.";
    case "model": return step.tool_calls.length
      ? `The model read the conversation (${step.prompt_tokens?.toLocaleString("en-US") ?? "?"} tokens) and requested ${step.tool_calls.length} tool call(s).`
      : "The model answered without a tool call. This ends the run after a release or with a final report (first line FINAL REPORT). Otherwise the loop asks the model to continue.";
    case "correction": return "The previous tool call failed. The loop told the model the error and that an identical request stops the run.";
    case "continuation": return `The model answered without a tool call and without a final report, and no release exists. The loop asked the model to continue (request ${step.count ?? "?"} of ${step.limit ?? "?"}).`;
    case "decoding": return `The model sent the argument at ${step.path || "the argument root"} as a JSON text (a string). `
      + `The tool schema expects ${step.decoded_type === "array" ? "an array" : "an object"}, so the loop decoded the text and sent the value to the MCP server. `
      + "The MCP server checks the decoded value against the schema as usual.";
    case "tool": return TOOL_TEXT.find(([pattern]) => pattern.test(step.tool))?.[1] ?? "A tool of the MCP server.";
  }
}

export interface ProblemGroup {
  tool: string;
  code: string;
  count: number;
  sequences: number[];
  first: StepProblem;
}

/** Failed tool calls, grouped by tool and error code, in the order of their first occurrence. */
export function problemGroups(steps: RunStep[]): ProblemGroup[] {
  const groups = new Map<string, ProblemGroup>();
  for (const step of steps) {
    if (step.kind !== "tool" || step.status !== "failed" || !step.problem) continue;
    const key = `${step.tool}\u0000${step.problem.code}`;
    const group = groups.get(key) ?? { tool: step.tool, code: step.problem.code, count: 0, sequences: [], first: step.problem };
    group.count += 1;
    group.sequences.push(step.sequence);
    groups.set(key, group);
  }
  return [...groups.values()];
}

export interface Totals {
  modelSeconds: number; toolSeconds: number; turns: number; calls: number; failed: number; corrections: number; continuations: number; decodings: number;
}

export function totals(steps: RunStep[]): Totals {
  const result: Totals = { modelSeconds: 0, toolSeconds: 0, turns: 0, calls: 0, failed: 0, corrections: 0, continuations: 0, decodings: 0 };
  for (const step of steps) {
    if (step.kind === "model") { result.turns += 1; result.modelSeconds += step.seconds ?? 0; }
    if (step.kind === "tool") { result.calls += 1; result.toolSeconds += step.seconds ?? 0; if (step.status === "failed") result.failed += 1; }
    if (step.kind === "correction") result.corrections += 1;
    if (step.kind === "continuation") result.continuations += 1;
    if (step.kind === "decoding") result.decodings += 1;
  }
  return result;
}

/** Why the agent loop ended, in plain words. */
export function outcome(summary: RunLoopSummary | null, budget: number | undefined): string | null {
  if (!summary) return null;
  const text: Record<string, string> = {
    released: "The agent released a STEP model.",
    // Older traces have no continuations field. They used this status for each answer without a tool call.
    stopped_without_release: summary.continuations != null
      ? "The model gave its final report without a release."
      : "The model answered without a tool call. The run ended without a release.",
    // With the limit 0 the loop sends no continuation request, so the first answer without a tool call ends the run.
    stopped_without_tool_call: summary.continuations === 0
      ? "The model answered without a tool call and without a final report. Continuation requests are off (limit 0), so the run ended."
      : "The model stopped without a tool call: it answered again without a tool call or a final report after the last continuation request.",
    tool_budget_reached: `The agent used all ${budget ?? summary.tool_requests} tool calls of its budget before a release.`,
    turn_budget_reached: "The agent used all model turns of its budget before a release.",
    time_budget_reached: "The run used its time budget before a release.",
    no_progress: "The loop stopped the run: the model sent the same failed request again.",
    user_input_required: "The model asked a question that only a user can answer.",
    transport_failed: "The connection to the MCP server failed.",
    failed: "The agent loop stopped with an error.",
  };
  return text[summary.status] ?? `The agent loop ended with status ${summary.status}.`;
}
