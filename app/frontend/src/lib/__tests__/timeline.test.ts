// Run timeline: layers, problem groups, totals, and the end of the agent loop in plain words.
import { describe, expect, it } from "vitest";
import type { RunLoopSummary, RunStep } from "../contract";
import { explanation, layerOf, outcome, problemGroups, stepLabel, totals } from "../timeline";

const base = { at: null, turn: 1 };
const model = (sequence: number, seconds: number, calls: string[] = ["pdf_info"]): RunStep =>
  ({ ...base, sequence, kind: "model", seconds, prompt_tokens: 1000, output_tokens: 10, text: "", tool_calls: calls });
const tool = (sequence: number, name: string, code: string | null = null, seconds = 1): RunStep => ({
  ...base, sequence, kind: "tool", tool: name, request_number: sequence, phase: "modeling", seconds, arguments: "{}", images: 0,
  status: code ? "failed" : "ok", problem: code ? { code, target: "head_stem_fillet", message: `${code} message` } : null,
});
const correction: RunStep = { ...base, sequence: 9, kind: "correction", tool: "build_from_description", code: "EDGE_SELECTION", text: "" };
const continuation: RunStep = { ...base, sequence: 11, kind: "continuation", count: 1, limit: 3, text: "No release exists." };

const steps: RunStep[] = [
  { ...base, sequence: 1, turn: 0, kind: "skill", paths: ["references/a.md"], text: "the first step" },
  model(2, 30), tool(3, "pdf_info"), tool(4, "build_from_description", "EDGE_SELECTION", 2),
  tool(5, "part_update", "PART_INVALID"), tool(6, "build_from_description", "EDGE_SELECTION", 3), correction,
];

describe("timeline", () => {
  it("assigns each step to its layer", () => {
    expect(steps.map(layerOf)).toEqual(["skill", "loop", "mcp", "cad", "mcp", "cad", "loop"]);
  });

  it("groups failed calls by tool and code in the order of the first occurrence", () => {
    expect(problemGroups(steps).map((g) => [g.tool, g.code, g.count, g.sequences])).toEqual([
      ["build_from_description", "EDGE_SELECTION", 2, [4, 6]],
      ["part_update", "PART_INVALID", 1, [5]],
    ]);
  });

  it("adds model time and tool time separately", () => {
    expect(totals(steps)).toEqual({ modelSeconds: 30, toolSeconds: 7, turns: 1, calls: 4, failed: 3, corrections: 1, continuations: 0 });
    expect(totals([...steps, model(10, 2, []), continuation]).continuations).toBe(1);
  });

  it("names steps and explains them for beginners", () => {
    expect(stepLabel(steps[1])).toBe("Model turn 1");
    expect(stepLabel(model(7, 1, []))).toBe("Model answer 1");
    expect(stepLabel(correction)).toBe("Correction after build_from_description");
    expect(explanation(steps[3])).toMatch(/CAD worker builds the solid/);
    expect(explanation(tool(8, "unknown_tool"))).toBe("A tool of the MCP server.");
  });

  it("shows a continuation request as a loop step of its own", () => {
    expect(layerOf(continuation)).toBe("loop");
    expect(stepLabel(continuation)).toBe("Continuation request 1");
    expect(explanation(continuation)).toBe("The model answered without a tool call and without a final report, and no release exists. "
      + "The loop asked the model to continue (request 1 of 3).");
    // An answer without a tool call ends the run only after a release or with a final report.
    expect(explanation(model(10, 2, []))).toBe("The model answered without a tool call. This ends the run after a release "
      + "or with a final report (first line FINAL REPORT). Otherwise the loop asks the model to continue.");
  });

  it("explains why the loop ended", () => {
    const summary = { status: "tool_budget_reached", tool_requests: 45 } as RunLoopSummary;
    expect(outcome(summary, 45)).toBe("The agent used all 45 tool calls of its budget before a release.");
    expect(outcome({ ...summary, status: "released" }, 45)).toBe("The agent released a STEP model.");
    expect(outcome({ ...summary, status: "stopped_without_release" }, 45)).toBe("The model gave its final report without a release.");
    expect(outcome({ ...summary, status: "stopped_without_tool_call" }, 45)).toMatch(/^The model stopped without a tool call/);
    expect(outcome({ ...summary, status: "new_status" }, 45)).toBe("The agent loop ended with status new_status.");
    expect(outcome(null, 45)).toBeNull();
  });
});
