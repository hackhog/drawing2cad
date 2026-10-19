// Which profile the next run uses and when it can start (CAD runs card).
import { describe, expect, it } from "vitest";
import type { AgentProfile, AgentProfiles, Capabilities } from "../contract";
import { runStartState, startEntry, unusableReason } from "../runStart";

const caps = (change: Partial<Capabilities> = {}) => ({ simulated: false, runs: true, agent_ready: true, ...change }) as Capabilities;
const profile = (name: string, change: Partial<AgentProfile> = {}): AgentProfile => ({
  name, provider: "openrouter", origin: "ui", base_url: "https://openrouter.ai/api/v1", model: `vendor/${name.toLowerCase()}`,
  api: "chat", reasoning_effort: null, key_set: true, key_locked: false, ...change,
});
const agent = (active: string | null, ...profiles: AgentProfile[]): AgentProfiles => ({ active, profiles });

describe("runStartState", () => {
  it("preselects the active profile and sends it", () => {
    const state = runStartState(caps(), agent("A", profile("A"), profile("B")), null);
    expect([state.selected, state.canStart, state.send]).toEqual(["A", true, "A"]);
  });

  it("uses the profile that the user chose", () => {
    const state = runStartState(caps({ runs: false }), agent("A", profile("A", { key_locked: true }), profile("B")), "B");
    expect([state.selected, state.canStart, state.send]).toEqual(["B", true, "B"]);
  });

  it("cannot start with a locked or key-less profile, or without a selection", () => {
    const profiles = agent(null, profile("A", { key_locked: true }), profile("B", { key_set: false }));
    expect(runStartState(caps(), profiles, "A").canStart).toBe(false);
    expect(runStartState(caps(), profiles, "B").canStart).toBe(false);
    expect(runStartState(caps(), profiles, null)).toMatchObject({ selected: null, canStart: false });
  });

  it("cannot start when the service is not ready for agent runs", () => {
    expect(runStartState(caps({ agent_ready: false }), agent("A", profile("A")), null).canStart).toBe(false);
    // Older servers do not report agent_ready.
    expect(runStartState(caps({ agent_ready: undefined }), agent("A", profile("A")), null).canStart).toBe(true);
  });

  it("follows the capabilities without profiles, for example in the simulated service", () => {
    expect(runStartState(caps({ simulated: true, runs: true }), undefined, null)).toMatchObject({ canStart: true, send: null });
    expect(runStartState(caps({ runs: false }), agent(null), null).canStart).toBe(false);
  });
});

describe("unusableReason", () => {
  it("names the reason why a profile cannot start a run", () => {
    expect(unusableReason(profile("A"))).toBeNull();
    expect(unusableReason(profile("B", { key_locked: true }))).toMatch(/^Key locked/);
    expect(unusableReason(profile("C", { key_set: false }))).toMatch(/^No API key/);
  });
});

describe("startEntry", () => {
  it("opens the dialog when a usable profile exists and the service is ready", () => {
    expect(startEntry(caps(), agent("A", profile("A")))).toBe("dialog");
    // The active profile is locked, but another one can start the run.
    expect(startEntry(caps({ runs: false }), agent("A", profile("A", { key_locked: true }), profile("B")))).toBe("dialog");
  });

  it("is disabled without a usable profile or when the service is not ready", () => {
    expect(startEntry(caps(), agent(null, profile("A", { key_locked: true })))).toBe("disabled");
    expect(startEntry(caps({ agent_ready: false }), agent("A", profile("A")))).toBe("disabled");
  });

  it("starts directly only in the simulated service", () => {
    expect(startEntry(caps({ simulated: true, runs: true }), undefined)).toBe("direct");
    expect(startEntry(caps({ simulated: true, runs: false }), undefined)).toBe("disabled");
    expect(startEntry(caps({ runs: false }), agent(null))).toBe("disabled");
  });

  it("starts no run of a real service while its profiles load, after a failed request, or before the capabilities", () => {
    expect(startEntry(caps({ runs: true }), undefined)).toBe("disabled");
    expect(startEntry(undefined, agent("A", profile("A")))).toBe("disabled");
  });
});
