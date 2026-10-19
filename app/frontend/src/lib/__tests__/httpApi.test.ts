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
});
