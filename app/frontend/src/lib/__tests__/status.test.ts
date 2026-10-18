// Status labels of an analyzed drawing: only flags without a user decision count.
import { describe, expect, it } from "vitest";
import type { ExtractResult, FlagDecision, ReviewFlag } from "../drawing";
import { analysisStatus } from "../status";

const flag = (id: string, decision: FlagDecision | null = null): ReviewFlag =>
  ({ id, kind: "unclear_strokes", message: "1 stroke(s) without a certain meaning", bbox: [0, 0, 1, 1], stroke_ids: [1], text: null, decision });

const ignored: FlagDecision = { action: "ignore", stroke_class: null, text: null, note: null, decided_at: "2026-01-01T00:00:00Z" };
const analysis = { review: [flag("strokes-1"), flag("strokes-2")] } as ExtractResult;

describe("analysisStatus", () => {
  it("counts the flags of the analysis when no decisions are loaded", () => {
    expect(analysisStatus(analysis, false)).toEqual(["flag", "2 to review"]);
  });

  it("counts only open flags of the current decisions", () => {
    expect(analysisStatus(analysis, false, [flag("strokes-1", ignored), flag("strokes-2")])).toEqual(["flag", "1 to review"]);
    expect(analysisStatus(analysis, false, [flag("strokes-1", ignored), flag("strokes-2", ignored)])).toEqual(["done", "done"]);
  });
});
