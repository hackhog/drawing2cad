// State of the run start in the CAD runs card: which model profile the next run uses and whether it can start.
import type { AgentProfile, AgentProfiles, AgentProvider, Capabilities } from "./contract";

export const PROVIDER_LABEL: Record<AgentProvider, string> = {
  openrouter: "OpenRouter", azure: "Azure AI Foundry", openai: "OpenAI-compatible",
};

export interface RunStartState {
  /** The profiles to choose from; empty for a service without profiles, for example the simulated service. */
  profiles: AgentProfile[];
  /** The selected profile name; null when the service has no active profile and the user chose none. */
  selected: string | null;
  profile: AgentProfile | undefined;
  canStart: boolean;
  /** The profile to send with the run start; null starts the run with the active profile. */
  send: string | null;
}

/** A profile can start a run if it has a key that the server can decrypt. */
export function usable(profile: AgentProfile): boolean {
  return profile.key_set && !profile.key_locked;
}

/** Why a profile cannot start a run, or null if it can. */
export function unusableReason(profile: AgentProfile): string | null {
  if (profile.key_locked) return "Key locked: enter the API key again in the settings.";
  if (!profile.key_set) return "No API key: enter it in the settings.";
  return null;
}

/**
 * What "Start run" in the CAD runs card does: open the profile dialog, start the run directly (a service without
 * profiles, for example the simulated service), or nothing because no run can start.
 */
export function startEntry(caps: Capabilities | undefined, agent: AgentProfiles | undefined): "dialog" | "direct" | "disabled" {
  const profiles = agent?.profiles ?? [];
  if (!profiles.length) return caps?.runs ? "direct" : "disabled";
  return caps?.agent_ready !== false && profiles.some(usable) ? "dialog" : "disabled";
}

/**
 * `chosen` is the selection of the user, or null for the active profile. Older servers do not report `agent_ready`;
 * then a usable profile can start. Without profiles, the capabilities decide, as before.
 */
export function runStartState(caps: Capabilities | undefined, agent: AgentProfiles | undefined, chosen: string | null): RunStartState {
  const profiles = agent?.profiles ?? [];
  const selected = chosen ?? agent?.active ?? null;
  const profile = profiles.find((p) => p.name === selected);
  const canStart = profiles.length ? !!profile && usable(profile) && caps?.agent_ready !== false : !!caps?.runs;
  return { profiles, selected, profile, canStart, send: profiles.length ? selected : null };
}
