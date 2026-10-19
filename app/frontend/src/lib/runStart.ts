// State of the run start in the CAD runs card: which model profile the next run uses and whether it can start.
import type { AgentProfile, AgentProfiles, Capabilities } from "./contract";

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

/** The label of a profile in the selection: name, model, default mark, and key state. */
export function profileLabel(profile: AgentProfile, active: string | null | undefined): string {
  const state = profile.key_locked ? " – key locked" : !profile.key_set ? " – no key" : "";
  return `${profile.name} · ${profile.model}${profile.name === active ? " (default)" : ""}${state}`;
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
