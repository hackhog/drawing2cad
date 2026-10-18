// Settings entry of the sidebar footer: shows the active agent and selects the model profile for new runs.
// The server keeps endpoints and keys; the browser sends only a profile name.
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Settings } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";
import type { Capabilities } from "@/lib/contract";
import { useApi } from "@/lib/apiContext";
import { recoveryFor } from "@/lib/errors";
import { agentProfilesQuery, capabilitiesQuery, keys } from "@/lib/queries";
import type { Tone } from "@/lib/status";
import { cn } from "@/lib/utils";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle, DialogTrigger } from "./ui/dialog";
import { StatusDot } from "./Status";

const NO_AGENT = "Lokal, ohne KI";
const OPTION = "flex cursor-pointer items-center gap-2.5 rounded-lg border px-3 py-2 has-[:checked]:border-primary has-[:checked]:bg-highlight-bg";

function agentLabel(caps: Capabilities | undefined): [Tone, string] {
  if (caps?.simulated) return ["flag", "Simulierter Dienst"];
  if (caps?.agent_model) return ["done", `${caps.agent_profile ?? "KI-Agent"} · ${caps.agent_model}`];
  return ["wait", NO_AGENT];
}

export function AgentSettings() {
  const api = useApi();
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const { data: caps } = useQuery(capabilitiesQuery(api));
  const profiles = useQuery({ ...agentProfilesQuery(api), enabled: open });
  const select = useMutation({
    mutationFn: (name: string | null) => api.selectAgentProfile(name),
    onSuccess: async (data) => {
      queryClient.setQueryData(keys.agentProfiles, data);
      await queryClient.invalidateQueries({ queryKey: keys.capabilities });
    },
    onError: (err) => toast.error("Modellprofil nicht gewählt", { description: `${err.message} ${recoveryFor(err)}` }),
  });
  const [tone, label] = agentLabel(caps);
  const active = select.isPending ? select.variables : profiles.data?.active ?? null;

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger className="flex w-full items-center gap-2 border-t px-2 py-2.5 text-left text-xs text-muted-foreground hover:bg-accent">
        <Settings className="size-3.5 flex-none" aria-hidden="true" />
        <StatusDot tone={tone} />
        <span className="min-w-0 flex-1 truncate" title={label}>{label}</span>
        <span className="sr-only">Einstellungen öffnen</span>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Einstellungen</DialogTitle>
          <DialogDescription>
            KI-Agent für neue Läufe. Wartende und laufende Läufe behalten ihr Modell. Zugangsdaten bleiben auf dem Server.
          </DialogDescription>
        </DialogHeader>
        {caps?.simulated ? (
          <p className="text-sm">Simulierter Dienst: Läufe nutzen kein Modell.</p>
        ) : profiles.isError ? (
          <p className="text-sm text-flag">Modellprofile nicht geladen. {recoveryFor(profiles.error)}</p>
        ) : (
          <fieldset className="grid gap-2" disabled={!profiles.data || select.isPending}>
            <legend className="mb-1.5 text-[11px] font-semibold tracking-[.06em] text-faint uppercase">KI-Agent</legend>
            {profiles.data?.profiles.map((profile) => (
              <label key={profile.name} className={OPTION}>
                <input type="radio" name="agent-profile" className="accent-primary" checked={active === profile.name}
                  onChange={() => select.mutate(profile.name)} />
                <span className="min-w-0 flex-1">
                  <strong className="block text-sm font-semibold">{profile.name}</strong>
                  <small className="block truncate font-mono text-[11px] text-muted-foreground" title={profile.model}>{profile.model}</small>
                </span>
                <small className="text-[11px] text-muted-foreground">{profile.api === "responses" ? "Responses API" : "Chat Completions"}</small>
              </label>
            ))}
            <label className={cn(OPTION, !profiles.data && "opacity-60")}>
              <input type="radio" name="agent-profile" className="accent-primary" checked={!!profiles.data && active === null}
                onChange={() => select.mutate(null)} />
              <span className="flex-1 text-sm font-semibold">{NO_AGENT}</span>
            </label>
            {profiles.data && !profiles.data.profiles.length && (
              <p className="text-xs text-muted-foreground">Kein Modellprofil konfiguriert (DRAWING2CAD_AGENT_* auf dem Server).</p>
            )}
          </fieldset>
        )}
      </DialogContent>
    </Dialog>
  );
}
