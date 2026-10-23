// The HTTP adapter sends the revisions of the model profile settings (ADR 0028).
import { afterEach, describe, expect, it, vi } from "vitest";
import { HttpApi } from "../httpApi";

const profiles = { active: null, profiles: [] };

function stubFetch() {
  const fetch = vi.fn(async () => new Response(JSON.stringify(profiles), { status: 200 }));
  vi.stubGlobal("fetch", fetch);
  return fetch;
}

afterEach(() => vi.unstubAllGlobals());

describe("model profile requests", () => {
  it("sends the revision of the selection", async () => {
    const fetch = stubFetch();
    await new HttpApi().selectAgentProfile("Local", 3);
    const [url, init] = fetch.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe("/api/agent/active");
    expect(JSON.parse(init.body as string)).toEqual({ name: "Local", revision: 3 });
  });

  it("sends the revision of a deleted profile as a query parameter, and none for an unknown revision", async () => {
    const fetch = stubFetch();
    await new HttpApi().deleteAgentProfile("Open Router", 2);
    await new HttpApi().deleteAgentProfile("Local");
    const urls = fetch.mock.calls.map((call) => (call as unknown as [string])[0]);
    expect(urls).toEqual(["/api/agent/profiles/Open%20Router?revision=2", "/api/agent/profiles/Local"]);
  });

  it("sends the limits and the revision of a saved profile", async () => {
    const fetch = stubFetch();
    await new HttpApi().saveAgentProfile("Local", {
      provider: "openai", endpoint: "https://llm.test/v1", model: "m", api: "chat", api_key: "", reasoning_effort: null,
      limits: { step_budget: 20, model_timeout_seconds: null }, revision: 4,
    });
    const [, init] = fetch.mock.calls[0] as unknown as [string, RequestInit];
    expect(JSON.parse(init.body as string)).toMatchObject({ limits: { step_budget: 20, model_timeout_seconds: null }, revision: 4 });
  });
});

describe("run start", () => {
  it("sends the selected profile, and no body without a selection", async () => {
    const fetch = stubFetch();
    await new HttpApi().createRun("src_1", "OpenRouter");
    await new HttpApi().createRun("src_1");
    const calls = fetch.mock.calls as unknown as [string, RequestInit][];
    expect(calls[0][0]).toBe("/api/sources/src_1/runs");
    expect(JSON.parse(calls[0][1].body as string)).toEqual({ profile: "OpenRouter" });
    expect(calls[1][1].body).toBeUndefined();
  });

  it("sends an empty profile name, so that the server rejects it", async () => {
    const fetch = stubFetch();
    await new HttpApi().createRun("src_1", "");
    const [, init] = fetch.mock.calls[0] as unknown as [string, RequestInit];
    expect(JSON.parse(init.body as string)).toEqual({ profile: "" });
  });
});

// The HTTP adapter preserves the service selection and reads historical files by opaque ID.
describe("last-result requests", () => {
  it("keeps the build revision, validation, blockers, and release status from the API", async () => {
    const value = { run_id: "run_failed", part: { revision: 2 }, artifacts: [{ artifact_id: "candidate/one", role: "step_candidate",
      released: false, release_status: "not_released", model_revision: 1 }], last_results: {
      released: false, failed_phase: "validating", reason: "Drawing verification failed.",
      blocking: [{ rule_id: "DIM-06", status: "fail", feature: null, message: "Dimension missing." }], artifact_ids: ["candidate/one"],
      model: { artifact_id: "candidate/one", model_revision: 1, validation: [{ check: "solid_validity", status: "pass", detail: "Valid." }] },
      no_model_reason: null,
    } };
    const fetch = vi.fn(async () => new Response(JSON.stringify(value), { status: 200 }));
    vi.stubGlobal("fetch", fetch);
    const api = new HttpApi();
    expect(await api.getRun("run_failed")).toEqual(value);
    await api.readArtifact("candidate/one");
    expect((fetch.mock.calls as unknown as [string][]).map(([url]) => url)).toEqual([
      "/api/runs/run_failed", "/api/artifacts/candidate%2Fone/content",
    ]);
  });
});
