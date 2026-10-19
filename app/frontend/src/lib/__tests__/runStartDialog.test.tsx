// Server rendering verifies the profile options of the run start dialog without a browser.
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { RunProfileOptions } from "../../components/run/RunStartDialog";
import type { AgentProfile } from "../contract";

const profile = (name: string, change: Partial<AgentProfile> = {}): AgentProfile => ({
  name, provider: "openrouter", origin: "ui", base_url: "https://openrouter.ai/api/v1", model: `vendor/${name.toLowerCase()}-long-model-name`,
  api: "chat", reasoning_effort: null, key_set: true, key_locked: false, ...change,
});

function render(selected: string | null, ...profiles: AgentProfile[]) {
  const html = renderToStaticMarkup(
    <RunProfileOptions profiles={profiles} active="A" selected={selected} onSelect={() => undefined} disabled={false} />,
  );
  // The test environment has no DOM: read each label and its radio input from the markup.
  return html.split("<label").slice(1).map((label) => {
    const input = /<input[^>]*>/.exec(label)?.[0] ?? "";
    return { value: /value="([^"]*)"/.exec(input)?.[1], checked: /\schecked=""/.test(input),
             disabled: /\sdisabled=""/.test(input), text: label.replace(/<[^>]+>/g, "") };
  });
}

describe("RunProfileOptions", () => {
  it("shows each profile with its complete model, the default mark, and the selection", () => {
    const rows = render("A", profile("A", { reasoning_effort: "low" }), profile("B", { provider: "azure" }));
    expect(rows.map((r) => [r.value, r.checked, r.disabled])).toEqual([["A", true, false], ["B", false, false]]);
    expect(rows[0].text).toContain("vendor/a-long-model-name · reasoning low");
    expect(rows[0].text).toContain("Default");
    expect(rows[1].text).toContain("Azure AI Foundry");
    expect(rows[1].text).not.toContain("Default");
  });

  it("disables a profile without a usable key and names the reason", () => {
    const rows = render("A", profile("A"), profile("L", { key_locked: true }), profile("N", { key_set: false }));
    expect(rows.map((r) => r.disabled)).toEqual([false, true, true]);
    expect(rows[1].text).toContain("Key locked");
    expect(rows[2].text).toContain("No API key");
  });
});
